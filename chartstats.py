"""Per-chart statistics: Sensory rating (ported from the STARLiGHT Jessi's House theme),
DDR-style groove radar, BPM estimate, length and step counts."""
import os
import re

import paths
import simfile

# Official DDR groove radar values ship with some STARLiGHT-family themes (Other/ddr_groove_data.lua).
RADAR_TABLES = paths.theme_files('ddr_groove_data.lua') + [paths.resource(os.path.join('data-static', 'ddr_groove_data.lua'))]

# same weights as Scripts/00 AInit.lua in the theme
SENSORY_W = {'peak': 7, 'avg': 3, 'jump': 25, 'gimmick': 12}
_RADAR_DIFF = {'beginner': 'Beginner', 'basic': 'Easy', 'difficult': 'Medium', 'expert': 'Hard', 'challenge': 'Challenge'}


def music_length(path):
    try:
        import mutagen
        f = mutagen.File(path)
        if f is not None and f.info and f.info.length:
            return float(f.info.length)
    except Exception:
        pass
    return 0.0


def bpm_estimate(timing, last_beat):
    """Duration-weighted dominant/average BPM and the real min-max over the chart."""
    segs = timing.bpms
    weights, total, wsum = {}, 0.0, 0.0
    lo, hi = float('inf'), 0.0
    for i, (b, bpm) in enumerate(segs):
        end = min(segs[i + 1][0] if i + 1 < len(segs) else last_beat, last_beat)
        if bpm <= 0 or end <= b:
            continue
        secs = (end - b) * 60.0 / bpm
        weights[round(bpm)] = weights.get(round(bpm), 0) + secs
        total += secs
        wsum += bpm * secs
        lo, hi = min(lo, bpm), max(hi, bpm)
    if not total:
        lo, hi = timing.bpm_range()
        return {'dominant': round(hi), 'average': round(hi), 'min': lo, 'max': hi, 'constant': round(lo) == round(hi)}
    return {'dominant': max(weights, key=weights.get), 'average': round(wsum / total), 'min': lo, 'max': hi,
            'constant': round(lo) == round(hi)}


def speed_tier(bpm):
    for limit, name in ((100, 'SLOW'), (140, 'MODERATE'), (180, 'FAST'), (220, 'VERY FAST')):
        if bpm < limit:
            return name
    return 'EXTREME'


def variability(est):
    if est['constant']:
        return 'STEADY'
    if est['min'] > 0 and est['max'] >= est['min'] * 2:
        return 'GIMMICK'
    return 'VARIABLE'


def _knee(x, knee, add, span):
    """DDR X radar curve: linear up to 100 at the knee, flatter above it."""
    return x * 100.0 / knee if x < knee else (x + add) * 100.0 / span


def compute(song, chart, song_len):
    simfile.parse_chart(song, chart)
    timing = chart.timing or song.timing
    notes = [n for n in chart.notes if n.kind != 'mine']
    if not notes:
        return None
    rows = {}
    for n in notes:
        rows.setdefault(round(n.beat, 4), []).append(n)
    row_beats = sorted(rows)
    n_rows = len(row_beats)
    jumps = sum(1 for b in row_beats if len(rows[b]) >= 2)
    hands = sum(1 for b in row_beats if len(rows[b]) >= 3)
    holds = [n for n in notes if n.kind in ('hold', 'roll')]
    mines = sum(1 for n in chart.notes if n.kind == 'mine')
    first_t = notes[0].time
    last_t = max(n.end_time if n.kind in ('hold', 'roll') else n.time for n in notes)
    last_beat = max(n.end_beat if n.kind in ('hold', 'roll') else n.beat for n in notes)
    dur = max(1.0, last_t - first_t)

    # ---- Sensory (theme formula)
    peak = 0.0
    per_measure = {}
    for b in row_beats:
        per_measure[int(b // 4)] = per_measure.get(int(b // 4), 0) + 1
    for m, c in per_measure.items():
        secs = timing.time_at((m + 1) * 4) - timing.time_at(m * 4)
        if secs > 0.2:
            peak = max(peak, c / secs)
    avg = n_rows / dur
    jump_ratio = (jumps + 2 * hands) / n_rows
    gim, labels = 0.0, []
    lo, hi = timing.bpm_range()
    for cond, w, label in ((bool(timing.stops), 0.15, 'STOP'), (bool(timing.warps), 0.25, 'WARP'),
                           (any(v < 0 for _, v in timing.bpms), 0.20, 'NEG'), (bool(timing.delays), 0.05, None),
                           (lo > 0 and hi >= lo * 2, 0.20, 'BPM')):
        if cond:
            gim += w
            if label:
                labels.append(label)
    gim = min(gim, 1.0)
    sensory = int(peak * SENSORY_W['peak'] + avg * SENSORY_W['avg'] + jump_ratio * SENSORY_W['jump']
                  + gim * SENSORY_W['gimmick'] + 0.5)
    quants = [rows[b][0].quant for b in row_beats]
    tech = sum(1 for q in quants if q > 8) / n_rows
    if tech >= 0.5:
        mix = '16th-heavy'
    elif tech >= 0.25:
        mix = '16th bursts'
    elif max(quants) >= 12:
        mix = 'some 12/16ths'
    else:
        mix = 'mostly 4/8ths'

    # ---- DDR groove radar (DDR X formulas)
    length = song_len if song_len > last_t * 0.8 else last_t + 2.0
    total_beats = max(4.0, last_beat)
    avg_bpm = 60.0 * total_beats / max(1.0, last_t - timing.time_at(0))
    win, j = 0, 0
    for i, b in enumerate(row_beats):
        while row_beats[j] <= b - 4 + 1e-6:
            j += 1
        win = max(win, i - j + 1)
    fb, cur = 0.0, None
    for s, e in sorted((n.beat, n.end_beat) for n in holds):
        if cur and s <= cur[1]:
            cur[1] = max(cur[1], e)
        else:
            if cur:
                fb += cur[1] - cur[0]
            cur = [s, e]
    if cur:
        fb += cur[1] - cur[0]
    # chaos: weights fitted to 1,887 official DDR charts (mean error about 5 points)
    qc = {}
    for b in row_beats:
        qc[rows[b][0].quant] = qc.get(rows[b][0].quant, 0) + 1
    gaps = [row_beats[i] - row_beats[i - 1] for i in range(1, n_rows)]
    chaos_x = (3.75 * qc.get(8, 0) + 9.2 * (qc.get(12, 0) + qc.get(24, 0)) + 5.24 * qc.get(16, 0)
               + 34.56 * sum(v for q, v in qc.items() if q > 16 and q != 24)
               + 4.4 * sum(1 for g in gaps if g < 0.5 - 1e-3)
               + 3.16 * sum(1 for i in range(1, len(timing.bpms)) if timing.bpms[i][0] < last_beat)
               + 148.51 * sum(1 for sb, _ in timing.stops if sb < last_beat))
    raw = {'npm': 60.0 * n_rows / length, 'volt': win * avg_bpm / 4.0, 'air': 60.0 * jumps / length,
           'freeze': 10000.0 * fb / total_beats, 'chaos': chaos_x * 100.0 / length}
    radar = [_knee(raw['npm'], 300, -139, 161), _knee(raw['volt'], 600, 594, 1194), _knee(raw['air'], 55, 36, 91),
             _knee(raw['freeze'], 3500, 2484, 5984), _knee(raw['chaos'], 2000, 21605, 23605)]
    radar = [max(0, int(round(v))) for v in radar]
    return {
        'sensory': sensory, 'avg_nps': round(avg, 2), 'peak_nps': round(peak, 2), 'gimmicks': labels, 'mix': mix,
        'steps': n_rows, 'jumps': jumps, 'holds': len(holds), 'mines': mines, 'radar': radar, 'radar_official': False,
        'bpm': bpm_estimate(timing, last_beat), 'chart_end': round(last_t, 2),
    }


_official = None


def _norm(s):
    return re.sub(r'[^a-z0-9]+', '', s.lower())


def official_radar(folder_name, title, diff):
    """Official DDR radar values from the theme's table, or None."""
    global _official
    if _official is None:
        _official = {}
        text = ''
        for table in RADAR_TABLES:
            try:
                text = open(table, encoding='utf-8', errors='replace').read()
                break
            except OSError:
                continue
        song = None
        for line in text.splitlines():
            m = re.match(r'^\t\t\["(.*)"\] = \{', line)
            if m:
                song = _norm(m.group(1))
                continue
            m = re.match(r'^\t\t\t\["single-(\w+)"\] = \{\s*([-\d]+),\s*([-\d]+),\s*([-\d]+),\s*([-\d]+),\s*([-\d]+)', line)
            if m and song and m.group(1) in _RADAR_DIFF:
                _official.setdefault(song, {}).setdefault(_RADAR_DIFF[m.group(1)], [max(0, int(x)) for x in m.groups()[1:]])
    for key in (_norm(folder_name), _norm(title)):
        if key in _official and diff in _official[key]:
            return _official[key][diff]
    return None
