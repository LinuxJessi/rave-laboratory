"""Lab mode charts: the editable note model, .ssc saving, the starter-chart generator, and the edit actions
the AI assistant (and the editor) use.

Positions are ticks, 48 per beat (4ths, 8ths, 12ths, 16ths, 24ths, 32nds and 48ths all land on a tick).
Measures are numbered from 1 everywhere a person or the AI sees them, same as the gameplay measure lines.

The generator follows what this household's most-played 4-7 charts look like (see chart-feel notes):
a quarter-note spine, few syncopated off-beats at low levels, rhythms and arrows reused when the music
repeats, jacks allowed, no crossovers or quick Up/Down swaps below level 8, feet drifting back to Left/Right.
"""
import json
import os
import random
import re
import zlib

import numpy as np

import paths
import simfile

TICKS = 48
MEASURE = TICKS * 4
COLS = 'LDUR'
DIFFS = ['Beginner', 'Easy', 'Medium', 'Hard', 'Challenge']
DEFAULT_METER = {'Beginner': 2, 'Easy': 4, 'Medium': 7, 'Hard': 10, 'Challenge': 12}
SNAPS = [4, 8, 12, 16, 24, 32, 48]          # notes per beat x 4 (StepMania naming: 4th, 8th, ...)
KINDS = ['tap', 'hold', 'roll', 'mine']
STEPS_PER_S = {1: .7, 2: 1.0, 3: 1.3, 4: 1.6, 5: 1.9, 6: 2.2, 7: 2.6, 8: 3.1, 9: 3.7, 10: 4.3, 11: 5.0, 12: 5.8,
               13: 6.6, 14: 7.4, 15: 8.2, 16: 9.0, 17: 9.8, 18: 10.6, 19: 11.4}


class LNote:
    __slots__ = ('tick', 'col', 'kind', 'length')

    def __init__(self, tick, col, kind='tap', length=0):
        self.tick, self.col, self.kind, self.length = int(tick), int(col), kind, int(length)

    @property
    def end(self):
        return self.tick + (self.length if self.kind in ('hold', 'roll') else 0)

    def copy(self):
        return LNote(self.tick, self.col, self.kind, self.length)

    def astuple(self):
        return (self.tick, self.col, self.kind, self.length)


class LChart:
    def __init__(self, diff, meter, desc='', notes=None):
        self.diff, self.meter, self.desc = diff, int(meter), desc
        self.notes = notes or []

    def sort(self):
        self.notes.sort(key=lambda n: (n.tick, n.col))

    def at(self, tick, col):
        """The note covering this tick in this column (a freeze counts along its whole length)."""
        for n in self.notes:
            if n.col == col and (n.tick == tick or (n.kind in ('hold', 'roll') and n.tick <= tick <= n.end)):
                return n
        return None

    def place(self, note):
        """Add a note, removing anything it overlaps in its column."""
        self.notes = [n for n in self.notes if not (n.col == note.col and n.tick <= note.end and n.end >= note.tick)]
        self.notes.append(note)
        self.sort()
        return note

    def in_measures(self, m_from, m_to):
        """Notes whose head is in measures m_from..m_to (1-based, inclusive)."""
        a, b = (m_from - 1) * MEASURE, m_to * MEASURE
        return [n for n in self.notes if a <= n.tick < b]

    def last_measure(self):
        return max([n.end // MEASURE + 1 for n in self.notes] or [0])

    def stats(self, bpm):
        rows = {}
        for n in self.notes:
            if n.kind != 'mine':
                rows.setdefault(n.tick, []).append(n)
        ticks = sorted(rows)
        if not ticks:
            return {'steps': 0}
        secs = max(1e-6, (ticks[-1] - ticks[0]) / TICKS * 60.0 / bpm)
        jacks = sum(1 for a, b in zip(ticks, ticks[1:]) if len(rows[a]) == 1 and len(rows[b]) == 1
                    and rows[a][0].col == rows[b][0].col)
        return {'steps': len(ticks), 'jumps': sum(1 for t in ticks if len(rows[t]) > 1),
                'freezes': sum(1 for n in self.notes if n.kind in ('hold', 'roll')),
                'mines': sum(1 for n in self.notes if n.kind == 'mine'),
                'steps_per_s': round(len(ticks) / secs, 2) if len(ticks) > 1 else 0,
                'on_beat_pct': round(100 * sum(1 for t in ticks if t % TICKS == 0) / len(ticks)),
                'eighths_pct': round(100 * sum(1 for t in ticks if t % TICKS == TICKS // 2) / len(ticks)),
                'jack_pct': round(100 * jacks / max(1, len(ticks) - 1))}


# ---------------------------------------------------------------------------- project

class Project:
    """A song folder in Songs/Rave Lab/ plus lab.json (analysis and chat history)."""

    def __init__(self, folder):
        self.folder = folder
        self.title = self.artist = ''
        self.music = self.video = self.background = ''
        self.bpm, self.offset = 120.0, 0.0
        self.sample_start, self.sample_length = 30.0, 15.0
        self.analysis = None
        self.charts = []
        self.chat = []
        self.gen_count = 0

    @property
    def rel(self):
        return '%s/%s' % (os.path.basename(os.path.dirname(self.folder)), os.path.basename(self.folder))

    @property
    def lab_path(self):
        return os.path.join(self.folder, 'lab.json')

    @property
    def ssc_path(self):
        return os.path.join(self.folder, 'chart.ssc')

    def music_path(self):
        return os.path.join(self.folder, self.music) if self.music else ''

    def timing(self):
        return simfile.Timing(self.offset, [(0.0, self.bpm)])

    def time_of_tick(self, tick):
        return -self.offset + tick / float(TICKS) * 60.0 / self.bpm

    def tick_of_time(self, t):
        return (t + self.offset) * self.bpm / 60.0 * TICKS

    def chart(self, diff):
        return next((c for c in self.charts if c.diff == diff), None)

    def get_or_add(self, diff, meter=None):
        c = self.chart(diff)
        if c is None:
            c = LChart(diff, meter or DEFAULT_METER.get(diff, 5))
            self.charts.append(c)
            self.charts.sort(key=lambda c: DIFFS.index(c.diff) if c.diff in DIFFS else 9)
        return c

    # ---------------------------------------------------------- disk

    @classmethod
    def load(cls, folder):
        p = cls(folder)
        try:
            with open(p.lab_path, encoding='utf-8') as f:
                d = json.load(f)
        except (FileNotFoundError, ValueError):
            d = {}
        for k in ('title', 'artist', 'music', 'video', 'background', 'bpm', 'offset', 'sample_start', 'sample_length',
                  'analysis', 'chat', 'gen_count'):
            if k in d:
                setattr(p, k, d[k])
        if os.path.isfile(p.ssc_path):
            song = simfile.load_song(folder, p.rel)
            if song and song.timing:
                p.bpm, p.offset = song.timing.bpms[0][1], song.timing.offset
                for c in song.charts:
                    simfile.parse_chart(song, c)
                    notes = []
                    for n in c.notes:
                        length = int(round((n.end_beat - n.beat) * TICKS)) if n.kind in ('hold', 'roll') else 0
                        notes.append(LNote(int(round(n.beat * TICKS)), n.col, n.kind, length))
                    p.charts.append(LChart(c.diff, c.meter, c.desc, notes))
        return p

    def save(self):
        os.makedirs(self.folder, exist_ok=True)
        _write(self.ssc_path, self.ssc_text())
        d = {k: getattr(self, k) for k in ('title', 'artist', 'music', 'video', 'background', 'bpm', 'offset',
                                           'sample_start', 'sample_length', 'analysis', 'gen_count')}
        d['chat'] = self.chat[-200:]
        _write(self.lab_path, json.dumps(d, ensure_ascii=False, indent=1))
        paths.drop_outfox_cache(self.rel)        # OutFox's FastLoad would keep showing the old chart otherwise

    def ssc_text(self):
        def esc(s):
            return str(s).replace(';', '').replace(':', ' ').replace('#', '')
        spb = 60.0 / self.bpm
        head = [('VERSION', '0.83'), ('TITLE', esc(self.title)), ('SUBTITLE', ''), ('ARTIST', esc(self.artist)),
                ('GENRE', ''), ('CREDIT', 'Rave Laboratory Lab'), ('MUSIC', self.music), ('BANNER', ''),
                ('BACKGROUND', self.background), ('JACKET', self.background), ('OFFSET', '%.3f' % self.offset),
                ('SAMPLESTART', '%.3f' % self.sample_start), ('SAMPLELENGTH', '%.3f' % self.sample_length),
                ('SELECTABLE', 'YES'), ('BPMS', '0.000=%.3f' % self.bpm), ('STOPS', ''), ('DELAYS', ''), ('WARPS', '')]
        if self.video:
            # the video starts with the music: put it at the beat that falls on song time 0
            head.append(('BGCHANGES', '%.3f=%s=1.000=0=0=0' % (self.offset / spb, self.video)))
        out = ['#%s:%s;' % kv for kv in head]
        for c in self.charts:
            out += ['', '//---------------dance-single - %s----------------' % c.diff, '#NOTEDATA:;', '#STEPSTYPE:dance-single;',
                    '#DESCRIPTION:%s;' % esc(c.desc), '#DIFFICULTY:%s;' % c.diff, '#METER:%d;' % c.meter,
                    '#CREDIT:Rave Laboratory Lab;', '#NOTES:', notes_text(c) + ';']
        return '\n'.join(out) + '\n'


def _write(path, text):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)
    os.replace(tmp, path)


def notes_text(chart):
    rows = {}
    for n in chart.notes:
        ch = {'tap': '1', 'hold': '2', 'roll': '4', 'mine': 'M'}[n.kind]
        rows.setdefault(n.tick, ['0'] * 4)[n.col] = ch
        if n.kind in ('hold', 'roll'):
            rows.setdefault(n.end, ['0'] * 4)[n.col] = '3'
    measures = max([t // MEASURE + 1 for t in rows] or [1])
    out = []
    for m in range(measures):
        ticks = [t - m * MEASURE for t in rows if m * MEASURE <= t < (m + 1) * MEASURE]
        per = next(r for r in (4, 8, 12, 16, 24, 32, 48, 64, 96, 192) if all(t % (MEASURE // r) == 0 for t in ticks))
        lines = [''.join(rows.get(m * MEASURE + i * MEASURE // per, '0000')) for i in range(per)]
        out.append('\n'.join(lines))
    return '\n' + '\n,\n'.join(out) + '\n'


# ---------------------------------------------------------------------------- text form (for the AI and the chat)

def _beat_label(t):
    b = t / float(TICKS) + 1
    for d in (1, 2, 4, 3, 6, 8, 12):
        if abs(b * d - round(b * d)) < 1e-6:
            if d == 1:
                return '%d' % round(b)
            if d in (2, 4, 8):
                return ('%.3f' % b).rstrip('0').rstrip('.')
            whole = int(b)
            return '%d+%d/%d' % (whole, round((b - whole) * d), d)
    return '%.3f' % b


def measure_text(chart, m):
    """'1 L | 1.5 D | 2 UR~2 | 4 R^1 | 3 *D' (beat in the measure, panels, ~freeze or ^roll length in beats, * mine)."""
    rows = {}
    for n in chart.in_measures(m, m):
        rows.setdefault(n.tick - (m - 1) * MEASURE, []).append(n)
    parts = []
    for t in sorted(rows):
        group = sorted(rows[t], key=lambda n: n.col)
        taps = ''.join(COLS[n.col] for n in group if n.kind == 'tap')
        bits = [taps] if taps else []
        for n in group:
            if n.kind in ('hold', 'roll'):
                bits.append('%s%s%s' % (COLS[n.col], '~' if n.kind == 'hold' else '^', _num(n.length / float(TICKS))))
            elif n.kind == 'mine':
                bits.append('*' + COLS[n.col])
        parts.append('%s %s' % (_beat_label(t), ' '.join(bits)))
    return ' | '.join(parts) if parts else '-'


def _num(x):
    return ('%.3f' % x).rstrip('0').rstrip('.')


_TOKEN = re.compile(r'^\*?[LDUR]+(?:[~^][0-9.]+)?$')


def parse_measure_text(text, m):
    """The reverse of measure_text. Returns notes for measure m, or raises ValueError with a readable reason."""
    notes = []
    text = (text or '').strip()
    if text in ('', '-'):
        return notes
    for part in text.split('|'):
        bits = part.split()
        if not bits:
            continue
        beat = bits[0]
        try:
            if '+' in beat:
                whole, frac = beat.split('+')
                a, b = frac.split('/')
                val = int(whole) + int(a) / float(b)
            else:
                val = float(beat)
        except ValueError:
            raise ValueError('measure %d: "%s" is not a beat number' % (m, beat))
        if not 1 <= val < 5:
            raise ValueError('measure %d: beat %s is outside 1-4.99' % (m, beat))
        tick = (m - 1) * MEASURE + int(round((val - 1) * TICKS))
        if not bits[1:]:
            raise ValueError('measure %d: beat %s has no arrows' % (m, beat))
        for tok in bits[1:]:
            tok = tok.upper()
            if not _TOKEN.match(tok):
                raise ValueError('measure %d: cannot read "%s"' % (m, tok))
            mine = tok.startswith('*')
            tok = tok.lstrip('*')
            kind, length = ('mine' if mine else 'tap'), 0
            m2 = re.match(r'^([LDUR]+)([~^])([0-9.]+)$', tok)
            if m2:
                tok, kind, length = m2.group(1), 'hold' if m2.group(2) == '~' else 'roll', int(round(float(m2.group(3)) * TICKS))
                if length <= 0:
                    kind = 'tap'
            for ch in tok:
                notes.append(LNote(tick, COLS.index(ch), kind, length))
    return notes


def song_map(project):
    """Per-measure loudness (0-9) and repeats, so the AI can see the song's shape."""
    an = project.analysis or {}
    loud = an.get('loudness') or []
    same = an.get('same_as') or []
    if not loud:
        return 'not analysed'
    top = np.percentile([x for x in loud if x > 0] or [1], 90) or 1
    out = []
    for m, v in enumerate(loud):
        s = 'm%d:%d' % (m + 1, min(9, int(v / top * 9)))
        if m < len(same) and same[m] >= 0:
            s += '=m%d' % (same[m] + 1)
        out.append(s)
    return ' '.join(out)


def chart_digest(project, chart, focus_measure=None, max_chars=14000):
    lines = []
    last = max(chart.last_measure(), 1)
    for m in range(1, last + 1):
        lines.append('m%d: %s' % (m, measure_text(chart, m)))
    text = '\n'.join(lines)
    if len(text) > max_chars and focus_measure:
        a, b = max(1, focus_measure - 16), min(last, focus_measure + 16)
        text = '(showing measures %d-%d of %d; ask with {"do":"show","from_measure":..,"to_measure":..} for others)\n' % (a, b, last)
        text += '\n'.join(lines[a - 1:b])
    return text


# ---------------------------------------------------------------------------- generator

def style_defaults(meter):
    return {
        'density': 1.0,                                                        # x steps per second for the level
        'offbeats': 0.0 if meter <= 3 else 0.12 if meter <= 5 else 0.35 if meter <= 8 else 0.6,
        'sixteenths': 0.0 if meter <= 7 else 0.15 if meter <= 9 else 0.4,
        'jumps': 0.0 if meter <= 2 else 0.04 if meter <= 5 else 0.08 if meter <= 8 else 0.12,
        'freezes': 0.5 if meter <= 8 else 0.35,
        'jacks': 0.15 if meter <= 7 else 0.08,
        'repeat': 0.85,
        'mirror_repeats': 0.25,
        'crossovers': meter >= 11,
        'mines': 0.0,
    }


def generate(project, chart, style=None, seed=None, m_from=None, m_to=None):
    """Replace the notes of `chart` (or only measures m_from..m_to) with a generated pattern. Returns a summary string."""
    an = project.analysis
    if not an:
        raise ValueError('the song has not been analysed yet')
    meter = max(1, min(19, chart.meter))
    st = style_defaults(meter)
    for k, v in (style or {}).items():
        if k in st:
            st[k] = type(st[k])(v) if not isinstance(st[k], bool) else bool(v)
    if seed is None:
        seed = zlib.crc32(('%s|%s|%d|%d' % (project.title, chart.diff, meter, project.gen_count)).encode('utf-8'))
    rng = random.Random(seed)
    grid = np.array(an['grid'], dtype=np.float32)
    loud = np.array(an['loudness'], dtype=np.float32)
    same = an.get('same_as') or [-1] * len(grid)
    pitch = an.get('pitch') or []
    total = len(grid)
    lo_m = max(1, m_from or 1)
    hi_m = min(total, m_to or total)
    measure_s = 4 * 60.0 / project.bpm
    ref = float(np.percentile(loud[loud > 0], 90)) if (loud > 0).any() else 1.0
    target = STEPS_PER_S.get(meter, 8.0) * max(0.2, st['density'])

    # 1) rhythm per measure, as 16th slots 0..15
    rhythm, copied = {}, {}
    for m in range(lo_m - 1, hi_m):
        rel = loud[m] / ref if ref else 0
        if rel < 0.08 or grid[m].max() < 0.15:
            rhythm[m] = []
            continue
        src = same[m] if m < len(same) else -1
        if src >= 0 and src in rhythm and rng.random() < st['repeat']:
            rhythm[m] = list(rhythm[src])
            copied[m] = src
            continue
        scored = []
        for k in range(16):
            g = float(grid[m, k])
            if k % 4 == 0:
                s = g + 0.45 + (0.25 if k == 0 else 0.1 if k == 8 else 0)
            elif k % 2 == 0:
                if st['offbeats'] <= 0 or g < 0.35 * (1 - st['offbeats']) + 0.1:
                    continue
                s = g - 0.35 * (1 - st['offbeats'])
            else:
                if st['sixteenths'] <= 0 or g < 0.55 * (1 - st['sixteenths']) + 0.15:
                    continue
                s = g - 0.5 * (1 - st['sixteenths'])
            if g < 0.08 and not (k % 4 == 0 and rel > 0.3 and meter <= 6):
                continue
            scored.append((s + rng.random() * 0.05, k))
        n = int(round(target * measure_s * min(1.2, 0.45 + 0.75 * rel)))
        rhythm[m] = sorted(k for _, k in sorted(scored, reverse=True)[:max(0, n)])

    events = []                   # [tick, measure, slot]
    for m in sorted(rhythm):
        events += [[m * MEASURE + k * 12, m, k] for k in rhythm[m]]
    ticks = [e[0] for e in events]

    # 2) freezes over sustained gaps, 3) jumps on the strongest downbeats
    # freezes go where the music holds: a gap after the step with no onsets in it. The best candidates win,
    # up to a share of the steps, so "more freezes" can't turn every arrow into one.
    holds = {}
    min_gap = TICKS if st['freezes'] >= 0.7 or meter > 8 else TICKS * 3 // 2
    cands = []
    for i, (t, m, k) in enumerate(events):
        nxt = ticks[i + 1] if i + 1 < len(ticks) else t + 4 * TICKS
        gap = nxt - t
        if gap >= min_gap:
            inner = [grid[t2 // MEASURE, (t2 % MEASURE) // 12] for t2 in range(t + 12, nxt, 12) if t2 // MEASURE < total]
            quiet = float(np.mean(inner)) if inner else 0.0
            if loud[m] / ref > 0.3 and quiet < 0.35 + 0.3 * st['freezes']:
                cands.append((gap - quiet * TICKS, t, gap))
    cands.sort(reverse=True)
    for _, t, gap in cands[:int(round(len(events) * 0.05 + len(events) * 0.25 * st['freezes']))]:
        length = gap - (TICKS // 2 if gap <= 2 * TICKS else TICKS)
        holds[t] = max(12, length // 12 * 12)
    jumps = set()
    if st['jumps'] > 0:
        need = int(round(st['jumps'] * len(events)))
        space = TICKS if meter <= 5 else TICKS // 2
        cands = sorted(((grid[m, k], t) for i, (t, m, k) in enumerate(events)
                        if k in (0, 8) and t not in holds
                        and (i == 0 or t - ticks[i - 1] >= space) and (i + 1 == len(ticks) or ticks[i + 1] - t >= space)),
                       reverse=True)
        jumps = {t for _, t in cands[:need]}

    # 4) arrows with a simple two-foot model
    arrows = {}
    feet = {'L': 0, 'R': 3}
    foot = 'L' if rng.random() < 0.5 else 'R'
    last_t, last_p, last_pitch = -10 ** 9, None, None
    mirror_measure = {}
    for t, m, k in events:
        gap = t - last_t
        if m in copied:
            src_t = copied[m] * MEASURE + (t - m * MEASURE)
            if src_t in arrows:
                if m not in mirror_measure:
                    mirror_measure[m] = rng.random() < st['mirror_repeats']
                ps = arrows[src_t]
                if mirror_measure[m]:
                    ps = tuple(sorted(3 - p for p in ps))
                arrows[t] = ps
                if len(ps) > 1:
                    feet = {'L': min(ps), 'R': max(ps)}
                else:
                    f = 'L' if ps[0] == 0 else 'R' if ps[0] == 3 else foot
                    feet[f] = ps[0]
                    foot = 'R' if f == 'L' else 'L'
                last_t, last_p = t, ps[-1]
                continue
        if t in jumps:
            pairs = [((0, 3), 6), ((0, 1), 1), ((0, 2), 1), ((1, 3), 1), ((2, 3), 1)] + ([((1, 2), 0.5)] if meter >= 8 else [])
            ps = _weighted(rng, pairs)
            arrows[t] = ps
            feet = {'L': ps[0], 'R': ps[1]}
            foot = 'L' if rng.random() < 0.5 else 'R'
            last_t, last_p = t, None
            continue
        if last_p is not None and gap <= 2 * TICKS and rng.random() < st['jacks']:
            arrows[t] = (last_p,)
            last_t = t
            continue
        other = feet['R' if foot == 'L' else 'L']
        opts = {0: 1.0, 1: 0.8, 2: 0.8} if foot == 'L' else {3: 1.0, 1: 0.8, 2: 0.8}
        if st['crossovers']:
            opts[3 if foot == 'L' else 0] = 0.15
        opts.pop(other, None)
        if meter <= 7 and gap < TICKS and last_p in (1, 2):
            opts.pop(3 - last_p, None)                          # no quick Up/Down swaps at easier levels
        if gap < TICKS and last_p is not None and last_p in opts and len(opts) > 1:
            opts[last_p] *= 0.3
        if pitch and m < len(pitch):
            p_now = pitch[m][k]
            if last_pitch and p_now:
                if p_now - last_pitch >= 3 and 2 in opts:
                    opts[2] *= 1.6
                elif last_pitch - p_now >= 3 and 1 in opts:
                    opts[1] *= 1.6
            last_pitch = p_now or last_pitch
        if not opts:
            opts = {feet[foot]: 1.0}
        p = _weighted(rng, list(opts.items()))
        arrows[t] = (p,)
        feet[foot] = p
        foot = 'R' if foot == 'L' else 'L'
        last_t, last_p = t, p

    a, b = (lo_m - 1) * MEASURE, hi_m * MEASURE
    chart.notes = [n for n in chart.notes if not a <= n.tick < b]
    for t, ps in arrows.items():
        for p in ps:
            if t in holds and len(ps) == 1:
                chart.notes.append(LNote(t, p, 'hold', holds[t]))
            else:
                chart.notes.append(LNote(t, p))
    if st['mines'] > 0:
        for t, ps in list(arrows.items()):
            if len(ps) == 1 and rng.random() < st['mines'] * 0.2:
                col = rng.choice([c for c in range(4) if c != ps[0]])
                mt = t + TICKS // 2
                if not any(n.tick == mt for n in chart.notes):
                    chart.notes.append(LNote(mt, col, 'mine'))
    _fix_overlaps(chart)
    project.gen_count += 1
    s = chart.stats(project.bpm)
    where = 'measures %d-%d' % (lo_m, hi_m) if (m_from or m_to) else 'the whole song'
    return 'generated %s %d over %s: %d steps, %d jumps, %d freezes, %.1f steps/s' % (
        simfile.DIFF_NAMES.get(chart.diff, chart.diff), chart.meter, where, s['steps'], s.get('jumps', 0),
        s.get('freezes', 0), s.get('steps_per_s', 0))


def _weighted(rng, items):
    total = sum(w for _, w in items)
    r = rng.random() * total
    for v, w in items:
        r -= w
        if r <= 0:
            return v
    return items[-1][0]


def _fix_overlaps(chart):
    chart.sort()
    keep = []
    for n in chart.notes:
        if any(k.col == n.col and k.tick <= n.tick <= k.end for k in keep[-12:]):
            continue
        keep.append(n)
    chart.notes = keep


# ---------------------------------------------------------------------------- transforms

def transform(chart, op, m_from, m_to):
    notes = chart.in_measures(m_from, m_to)
    swap = {'mirror': {0: 3, 3: 0, 1: 2, 2: 1}, 'flip_lr': {0: 3, 3: 0}, 'flip_ud': {1: 2, 2: 1}}
    if op in swap:
        for n in notes:
            n.col = swap[op].get(n.col, n.col)
    elif op == 'remove_jumps':
        rows = {}
        for n in notes:
            if n.kind != 'mine':
                rows.setdefault(n.tick, []).append(n)
        drop = {id(n) for row in rows.values() if len(row) > 1 for n in row[1:]}
        chart.notes = [n for n in chart.notes if id(n) not in drop]
    elif op == 'remove_freezes':
        for n in notes:
            if n.kind in ('hold', 'roll'):
                n.kind, n.length = 'tap', 0
    elif op == 'remove_mines':
        ids = {id(n) for n in notes if n.kind == 'mine'}
        chart.notes = [n for n in chart.notes if id(n) not in ids]
    elif op == 'remove_offbeats':
        ids = {id(n) for n in notes if n.tick % TICKS}
        chart.notes = [n for n in chart.notes if id(n) not in ids]
    elif op == 'remove_16ths':
        ids = {id(n) for n in notes if n.tick % (TICKS // 2)}
        chart.notes = [n for n in chart.notes if id(n) not in ids]
    else:
        raise ValueError('unknown transform "%s"' % op)
    _fix_overlaps(chart)


# ---------------------------------------------------------------------------- actions (from the AI)

ACTION_HELP = """\
{"do":"generate","difficulty":"Easy","meter":5,"from_measure":1,"to_measure":40,"seed":7,
 "style":{"density":1.0,"offbeats":0.12,"sixteenths":0,"jumps":0.04,"freezes":0.5,"jacks":0.15,"repeat":0.85,"mirror_repeats":0.25,"crossovers":false,"mines":0}}
    builds a chart from the song's analysed rhythm (from/to/seed/style optional; style values 0-1 except density, a multiplier)
{"do":"add","measure":20,"notes":"1 LR | 3 L~2"}
    adds arrows to a measure, keeping what is there (panels are only L, D, U, R; a jump is two letters like LR)
{"do":"remove","measure":20,"notes":"2 D | 4 U"}
    removes those arrows
{"do":"write","measure":12,"notes":"1 L | 2 D | 2.5 U | 3 LR | 4 R~2"}
    replaces one measure with exactly these notes ("-" empties it)
{"do":"clear","from_measure":a,"to_measure":b}
{"do":"copy","from_measure":a,"to_measure":b,"to":c,"mirror":false}    copies measures a-b so they start at measure c
{"do":"transform","op":"mirror|flip_lr|flip_ud|remove_jumps|remove_freezes|remove_mines|remove_offbeats|remove_16ths","from_measure":a,"to_measure":b}
{"do":"chart","difficulty":"Medium","meter":7}      switch to (or create) that difficulty; meter optional
{"do":"set_meter","meter":6}
{"do":"delete_chart","difficulty":"Hard"}
{"do":"set_song","bpm":128.0,"offset":0.052,"title":"...","artist":"..."}   any subset
{"do":"show","from_measure":a,"to_measure":b}       see measures that were left out of the digest"""


def apply_actions(project, current_diff, actions):
    """Run AI actions. Returns (log lines, current difficulty, extra text for the AI to see next turn)."""
    log, extra = [], []
    diff = current_diff
    for act in actions or []:
        if not isinstance(act, dict):
            continue
        do = str(act.get('do', '')).lower()
        chart = project.chart(diff)
        try:
            def rng_of(default_all=True):
                last = max((chart.last_measure() if chart else 0), len((project.analysis or {}).get('grid') or []), 1)
                a = int(act.get('from_measure') or act.get('measure') or 1)
                b = int(act.get('to_measure') or act.get('measure') or last)
                return max(1, min(a, b)), max(a, b)
            if do in ('add', 'remove', 'write') and chart is None:
                chart = project.get_or_add(diff)
            if do == 'chart':
                d = _norm_diff(act.get('difficulty'))
                chart = project.get_or_add(d, act.get('meter'))
                if act.get('meter'):
                    chart.meter = int(act['meter'])
                diff = d
                log.append('switched to %s %d' % (simfile.DIFF_NAMES[d], chart.meter))
            elif do == 'generate':
                d = _norm_diff(act.get('difficulty') or diff)
                chart = project.get_or_add(d, act.get('meter'))
                if act.get('meter'):
                    chart.meter = int(act['meter'])
                diff = d
                a = act.get('from_measure')
                b = act.get('to_measure')
                log.append(generate(project, chart, act.get('style') or {}, act.get('seed'),
                                    int(a) if a else None, int(b) if b else None))
            elif chart is None:
                log.append('skipped %s: make a chart first' % do)
            elif do == 'write':
                m = int(act['measure'])
                notes = parse_measure_text(act.get('notes', ''), m)
                chart.notes = [n for n in chart.notes if not (m - 1) * MEASURE <= n.tick < m * MEASURE]
                chart.notes += notes
                _fix_overlaps(chart)
                log.append('wrote measure %d (%d arrows)' % (m, len(notes)))
            elif do == 'add':
                m = int(act['measure'])
                notes = parse_measure_text(act.get('notes', ''), m)
                for n in notes:
                    chart.place(n)
                log.append('added %d arrows in measure %d' % (len(notes), m))
            elif do == 'remove':
                m = int(act['measure'])
                gone = {(n.tick, n.col) for n in parse_measure_text(act.get('notes', ''), m)}
                before = len(chart.notes)
                chart.notes = [n for n in chart.notes if (n.tick, n.col) not in gone]
                log.append('removed %d arrows in measure %d' % (before - len(chart.notes), m))
            elif do == 'clear':
                a, b = rng_of()
                chart.notes = [n for n in chart.notes if not (a - 1) * MEASURE <= n.tick < b * MEASURE]
                log.append('cleared measures %d-%d' % (a, b))
            elif do == 'copy':
                a, b = rng_of()
                dest = int(act['to'])
                shift = (dest - a) * MEASURE
                src = [n.copy() for n in chart.in_measures(a, b)]
                span_a, span_b = (dest - 1) * MEASURE, (dest + b - a) * MEASURE
                chart.notes = [n for n in chart.notes if not span_a <= n.tick < span_b]
                for n in src:
                    n.tick += shift
                    if act.get('mirror'):
                        n.col = 3 - n.col
                    chart.notes.append(n)
                _fix_overlaps(chart)
                log.append('copied measures %d-%d to %d' % (a, b, dest))
            elif do == 'transform':
                a, b = rng_of()
                transform(chart, str(act.get('op')), a, b)
                log.append('%s on measures %d-%d' % (act.get('op'), a, b))
            elif do == 'set_meter':
                chart.meter = max(1, min(20, int(act['meter'])))
                log.append('level set to %d' % chart.meter)
            elif do == 'delete_chart':
                d = _norm_diff(act.get('difficulty') or diff)
                project.charts = [c for c in project.charts if c.diff != d]
                log.append('deleted the %s chart' % simfile.DIFF_NAMES[d])
                if d == diff:
                    diff = project.charts[0].diff if project.charts else 'Easy'
            elif do == 'show':
                a, b = rng_of()
                extra.append('\n'.join('m%d: %s' % (m, measure_text(chart, m)) for m in range(a, b + 1)))
                log.append('looked at measures %d-%d' % (a, b))
            elif do == 'set_song':
                if do and 'bpm' in act:
                    project.bpm = max(20.0, min(400.0, float(act['bpm'])))
                if 'offset' in act:
                    project.offset = float(act['offset'])
                for k in ('title', 'artist'):
                    if act.get(k):
                        setattr(project, k, str(act[k])[:120])
                log.append('song settings updated')
            else:
                log.append('unknown action "%s"' % do)
        except (KeyError, ValueError, TypeError) as e:
            log.append('could not %s: %s' % (do or 'do that', e))
    return log, diff, '\n\n'.join(extra)


def _norm_diff(name):
    d = simfile.norm_diff(str(name or ''))
    if d not in DIFFS:
        raise ValueError('unknown difficulty "%s" (use Beginner, Easy, Medium, Hard or Challenge)' % name)
    return d
