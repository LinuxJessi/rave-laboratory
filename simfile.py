"""Readers for .ssc, .sm and .dwi simfiles (dance-single only) plus beat/time conversion."""
import os
import re
from dataclasses import dataclass, field

DIFF_ORDER = ['Beginner', 'Easy', 'Medium', 'Hard', 'Challenge', 'Edit']
DIFF_NAMES = {'Beginner': 'BEGINNER', 'Easy': 'BASIC', 'Medium': 'DIFFICULT', 'Hard': 'EXTREME', 'Challenge': 'CHALLENGE', 'Edit': 'EDIT'}
_DIFF_ALIASES = {
    'beginner': 'Beginner', 'easy': 'Easy', 'basic': 'Easy', 'light': 'Easy',
    'medium': 'Medium', 'another': 'Medium', 'standard': 'Medium', 'trick': 'Medium', 'difficult': 'Medium',
    'hard': 'Hard', 'maniac': 'Hard', 'heavy': 'Hard', 'expert': 'Hard', 'extreme': 'Hard',
    'challenge': 'Challenge', 'smaniac': 'Challenge', 'oni': 'Challenge', 'edit': 'Edit',
}


def norm_diff(name):
    return _DIFF_ALIASES.get((name or '').strip().lower(), 'Edit')


@dataclass
class Note:
    time: float
    beat: float
    col: int
    kind: str            # tap, hold, roll, mine
    end_time: float = 0.0
    end_beat: float = 0.0
    quant: int = 4       # 4, 8, 12, 16, ... used for arrow colour


@dataclass
class Chart:
    diff: str
    meter: int
    desc: str
    raw: object = None   # note text (sm/ssc) or step string (dwi); parsed on demand
    timing: object = None  # chart-level Timing override (ssc)
    fmt: str = 'sm'
    notes: list = field(default_factory=list)
    step_count: int = 0

    @property
    def key(self):
        return '%s|%s' % (self.diff, self.desc)


@dataclass
class Song:
    folder: str
    rel: str
    title: str = ''
    subtitle: str = ''
    artist: str = ''
    music: str = ''
    banner: str = ''
    background: str = ''
    jacket: str = ''
    sample_start: float = 0.0
    sample_length: float = 15.0
    display_bpm: str = ''
    timing: object = None
    charts: list = field(default_factory=list)


class Timing:
    """Piecewise beat<->seconds map with BPM changes, stops, delays and warps skipped."""

    def __init__(self, offset=0.0, bpms=None, stops=None, delays=None, warps=None):
        self.offset = offset
        bpms = sorted(bpms or [(0.0, 120.0)])
        if not bpms or bpms[0][0] > 0:
            bpms.insert(0, (0.0, bpms[0][1] if bpms else 120.0))
        warps = [(b, length) for b, length in (warps or []) if length > 0]
        stops = sorted(stops or [])
        # Old .sm gimmicks spell a warp as a negative stop or a negative BPM; turn both into real warps.
        self.bpms = []
        for i, (b, v) in enumerate(bpms):
            if v < 0 and i + 1 < len(bpms):
                nb, nv = bpms[i + 1]
                warps.append((b, (nb - b) * (1.0 + abs(nv) / abs(v))))
                continue
            self.bpms.append((b, abs(v) or 120.0))
        if not self.bpms:
            self.bpms = [(0.0, 120.0)]
        self.stops = []
        for b, v in stops:
            if v < 0:
                warps.append((b, -v * self._bpm_at(b) / 60.0))
            elif v > 0:
                self.stops.append((b, v))
        self.delays = sorted(d for d in (delays or []) if d[1] > 0)
        self.warps = sorted(warps)
        self._build()

    def _bpm_at(self, beat):
        bpm = self.bpms[0][1]
        for b, v in self.bpms:
            if b <= beat:
                bpm = v
        return bpm

    def _build(self):
        events = [(b, 1, v) for b, v in self.bpms[1:]]
        events += [(b, 0, v) for b, v in self.delays]      # delays happen before the note on that beat
        events += [(b, 2, v) for b, v in self.stops]       # stops after it
        events += [(b, 3, v) for b, v in self.warps]       # warps skip beats without taking time
        events.sort()
        b0, t0, bpm = 0.0, -self.offset, self.bpms[0][1]
        pieces = [(b0, t0, bpm)]
        for b, kind, v in events:
            if b > b0:
                t0 += (b - b0) * 60.0 / bpm
                b0 = b
            inside_warp = b < b0
            if kind == 1:
                bpm = v
                if inside_warp:                          # tempo change hidden inside a warp
                    pieces[-1] = (pieces[-1][0], pieces[-1][1], bpm)
                else:
                    pieces.append((b0, t0, bpm))
            elif kind == 3:
                end = b + v
                if end > b0:
                    if not inside_warp:
                        pieces.append((b0, t0, 0.0))
                    b0 = end
                    pieces.append((b0, t0, bpm))
            elif not inside_warp:
                pieces.append((b0, t0, 0.0))
                t0 += v
                pieces.append((b0, t0, bpm))
        self.pieces = pieces

    def time_at(self, beat):
        p = self.pieces[0]
        for q in self.pieces[1:]:
            if q[0] < beat:
                p = q
            else:
                break
        t = p[1] + (beat - p[0]) * 60.0 / p[2] if p[2] else p[1]
        # a delay on this exact beat pushes the note after the pause
        return t + sum(v for b, v in self.delays if abs(b - beat) < 1e-6)

    def beat_at(self, t):
        p = self.pieces[0]
        for q in self.pieces:
            if q[1] <= t:
                p = q
            else:
                break
        return p[0] + (t - p[1]) * p[2] / 60.0

    def in_warp(self, beat):
        """Notes strictly inside a warp are skipped (StepMania treats them as fakes)."""
        return any(b < beat < b + length for b, length in self.warps)

    def bpm_range(self):
        vals = [v for _, v in self.bpms if 0 < v < 2000]
        return (min(vals), max(vals)) if vals else (120.0, 120.0)


# ---------------------------------------------------------------- helpers

def read_text(path):
    raw = open(path, 'rb').read()
    for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('latin-1', 'replace')


def _strip_comments(text):
    return re.sub(r'//[^\n]*', '', text)


def _tags(text):
    """Yield (NAME, value) for every #NAME:value; in order."""
    for m in re.finditer(r'#([A-Za-z0-9]+):(.*?)(?:;|(?=\n\s*#[A-Za-z0-9]+:))', text, re.S):
        yield m.group(1).upper(), m.group(2)


def _pairs(s, n=2):
    out = []
    for part in (s or '').split(','):
        bits = [x.strip() for x in part.split('=')]
        if len(bits) < n:
            continue
        try:
            out.append(tuple(float(x) for x in bits[:n]))
        except ValueError:
            pass
    return out


def _float(s, default=0.0):
    try:
        return float(str(s).strip())
    except ValueError:
        return default


def _find_file(folder, name, exts, hints=()):
    files = os.listdir(folder)
    if name:
        path = os.path.join(folder, name.replace('\\', '/').split('/')[-1])
        if os.path.isfile(path):
            return path
        low = name.lower().split('/')[-1]
        for f in files:
            if f.lower() == low:
                return os.path.join(folder, f)
    cands = [f for f in files if os.path.splitext(f)[1].lower() in exts]
    for hint in hints:
        for f in cands:
            if hint(f.lower()):
                return os.path.join(folder, f)
    return os.path.join(folder, cands[0]) if cands and not hints else ''


AUDIO = ('.ogg', '.mp3', '.wav', '.flac', '.oga')
IMAGES = ('.png', '.jpg', '.jpeg', '.bmp', '.gif')


def pick_simfile(folder):
    files = os.listdir(folder)
    for ext in ('.ssc', '.sm', '.dwi'):
        found = sorted(f for f in files if f.lower().endswith(ext))
        if found:
            return os.path.join(folder, found[0])
    return None


# ---------------------------------------------------------------- loading

def load_song(folder, rel):
    path = pick_simfile(folder)
    if not path:
        return None
    text = read_text(path)
    ext = os.path.splitext(path)[1].lower()
    song = Song(folder=folder, rel=rel)
    song.simfile_path = path
    if ext == '.dwi':
        _load_dwi(song, text)
    else:
        _load_sm(song, _strip_comments(text), ext == '.ssc')
    song.title = song.title.strip() or os.path.basename(folder)
    song.music = _find_file(folder, song.music, AUDIO)
    song.banner = _find_file(folder, song.banner, IMAGES, (lambda f: 'bn' in f or 'banner' in f,))
    song.background = _find_file(folder, song.background, IMAGES, (lambda f: 'bg' in f or 'background' in f,))
    song.jacket = _find_file(folder, song.jacket, IMAGES, (lambda f: 'jacket' in f or 'jk' in f,))
    if not song.banner:
        song.banner = _find_file(folder, '', IMAGES)
    song.charts.sort(key=lambda c: (DIFF_ORDER.index(c.diff), c.meter, c.desc))
    return song


def _load_sm(song, text, ssc):
    head = {}
    charts = []
    cur = None
    for name, val in _tags(text):
        if name == 'NOTEDATA':
            cur = {}
            charts.append(cur)
            continue
        if name == 'NOTES' and not ssc:
            parts = val.split(':')
            if len(parts) >= 6:
                charts.append({'STEPSTYPE': parts[0], 'DESCRIPTION': parts[1], 'DIFFICULTY': parts[2],
                               'METER': parts[3], 'NOTES': ':'.join(parts[5:])})
            continue
        (cur if cur is not None else head)[name] = val
    song.title = head.get('TITLE', '')
    song.subtitle = head.get('SUBTITLE', '').strip()
    song.artist = head.get('ARTIST', '').strip()
    song.music = head.get('MUSIC', '').strip()
    song.banner = head.get('BANNER', '').strip()
    song.background = head.get('BACKGROUND', '').strip()
    song.jacket = head.get('JACKET', '').strip()
    song.sample_start = _float(head.get('SAMPLESTART', 0))
    song.sample_length = _float(head.get('SAMPLELENGTH', 15), 15) or 15
    song.display_bpm = head.get('DISPLAYBPM', '').strip()
    song.timing = _timing_from(head, None)
    for c in charts:
        if c.get('STEPSTYPE', '').strip().lower() != 'dance-single' or 'NOTES' not in c:
            continue
        own = _timing_from(c, song.timing) if any(k in c for k in ('BPMS', 'STOPS', 'OFFSET', 'DELAYS', 'WARPS')) else None
        song.charts.append(Chart(diff=norm_diff(c.get('DIFFICULTY')), meter=int(_float(c.get('METER', 1), 1)),
                                 desc=(c.get('DESCRIPTION', '') or c.get('CHARTNAME', '')).strip(),
                                 raw=c['NOTES'], timing=own, fmt='sm'))


def _timing_from(tags, base):
    def get(name, n=2):
        if name in tags:
            return _pairs(tags[name], n)
        return None
    offset = _float(tags['OFFSET']) if 'OFFSET' in tags else (base.offset if base else 0.0)
    bpms = get('BPMS') or (base.bpms if base else [(0.0, 120.0)])
    stops = get('STOPS') if 'STOPS' in tags else (base.stops if base else [])
    delays = get('DELAYS') if 'DELAYS' in tags else (base.delays if base else [])
    warps = get('WARPS') if 'WARPS' in tags else (base.warps if base else [])
    return Timing(offset, bpms, stops, delays, warps)


def _quant(row, rows):
    for q in (4, 8, 12, 16, 24, 32, 48, 64):
        if (row * q) % rows == 0:
            return q
    return 192


def parse_chart(song, chart):
    """Fill chart.notes (sorted by time) and chart.step_count."""
    if chart.notes:
        return chart
    timing = chart.timing or song.timing
    if chart.fmt == 'dwi':
        rows = _dwi_rows(chart.raw)
    else:
        rows = []
        for mi, measure in enumerate(chart.raw.split(',')):
            lines = [ln.strip() for ln in measure.split() if ln.strip()]
            for ri, line in enumerate(lines):
                if any(ch != '0' for ch in line[:4]):
                    rows.append((mi * 4 + ri * 4.0 / len(lines), line[:4], _quant(ri, len(lines))))
    notes, open_holds = [], {}
    for beat, line, q in rows:
        if timing.in_warp(beat):
            continue
        t = timing.time_at(beat)
        for c, ch in enumerate(line):
            if ch in '1':
                notes.append(Note(t, beat, c, 'tap', quant=q))
            elif ch in '24':
                n = Note(t, beat, c, 'hold' if ch == '2' else 'roll', t, beat, quant=q)
                notes.append(n)
                open_holds[c] = n
            elif ch == '3' and c in open_holds:
                n = open_holds.pop(c)
                n.end_beat, n.end_time = beat, t
            elif ch == 'M':
                notes.append(Note(t, beat, c, 'mine', quant=q))
    for n in notes:
        if n.kind in ('hold', 'roll') and n.end_time <= n.time:
            n.kind = 'tap'
    notes.sort(key=lambda n: (n.time, n.col))
    chart.notes = notes
    chart.step_count = len({round(n.time, 4) for n in notes if n.kind != 'mine'})
    return chart


# ---------------------------------------------------------------- DWI

_DWI_ARROWS = {'0': '', '1': 'LD', '2': 'D', '3': 'DR', '4': 'L', '6': 'R', '7': 'LU', '8': 'U', '9': 'UR', 'A': 'UD', 'B': 'LR'}
_COLS = {'L': 0, 'D': 1, 'U': 2, 'R': 3}
_DWI_DIFF = {'BEGINNER': 'Beginner', 'BASIC': 'Easy', 'ANOTHER': 'Medium', 'MANIAC': 'Hard', 'SMANIAC': 'Challenge'}


def _load_dwi(song, text):
    tags = dict(_tags(text))
    song.title = tags.get('TITLE', '')
    song.artist = tags.get('ARTIST', '').strip()
    ss = tags.get('SAMPLESTART', '0').strip()
    if ':' in ss:
        m, s = ss.split(':', 1)
        song.sample_start = _float(m) * 60 + _float(s)
    else:
        song.sample_start = _float(ss)
    song.sample_length = _float(tags.get('SAMPLELENGTH', 15), 15) or 15
    if song.sample_start > 1000:
        song.sample_start /= 1000.0
    song.display_bpm = tags.get('DISPLAYBPM', '').strip()
    bpm = _float(tags.get('BPM', 120), 120)
    bpms = [(0.0, bpm)] + [(b / 4.0, v) for b, v in _pairs(tags.get('CHANGEBPM', ''))]
    stops = [(b / 4.0, v / 1000.0) for b, v in _pairs(tags.get('FREEZE', ''))]
    song.timing = Timing(-_float(tags.get('GAP', 0)) / 1000.0, bpms, stops)
    song.music = tags.get('FILE', '').strip()
    for m in re.finditer(r'#SINGLE:([A-Za-z]+):(\d+):([^;]*);', text):
        song.charts.append(Chart(diff=_DWI_DIFF.get(m.group(1).upper(), 'Edit'), meter=int(m.group(2)),
                                 desc='', raw=re.sub(r'\s+', '', m.group(3)), fmt='dwi'))


def _dwi_rows(data):
    """Return (beat, 'xxxx' sm-style row, quant) from a DWI step string."""
    rows = []
    step = 0.5          # beats per character: 8ths by default
    beat = 0.0
    held = set()
    i = 0
    n = len(data)
    sizes = {'(': 0.25, '[': 1 / 6.0, '{': 1 / 16.0, '`': 1 / 48.0}   # 16ths, 24ths, 64ths, 192nds
    closers = {')', ']', '}', "'"}

    def add(chars, hold_chars):
        cols = [0, 0, 0, 0]
        for ch in chars:
            for a in _DWI_ARROWS.get(ch.upper(), ''):
                cols[_COLS[a]] = 1
        line = ['0'] * 4
        for c in range(4):
            if cols[c]:
                if c in held:
                    line[c] = '3'
                    held.discard(c)
                else:
                    line[c] = '1'
        for ch in hold_chars:
            for a in _DWI_ARROWS.get(ch.upper(), ''):
                c = _COLS[a]
                if line[c] == '1':
                    line[c] = '2'
                    held.add(c)
        if any(x != '0' for x in line):
            frac = beat % 1.0
            q = 4 if frac < 1e-6 else 8 if abs(frac - 0.5) < 1e-6 else 16 if abs(frac * 4 - round(frac * 4)) < 1e-6 else 12 if abs(frac * 3 - round(frac * 3)) < 1e-6 else 48
            rows.append((round(beat, 6), ''.join(line), q))

    while i < n:
        ch = data[i]
        if ch in sizes:
            step = sizes[ch]
            i += 1
            continue
        if ch in closers:
            step = 0.5
            i += 1
            continue
        if ch == '<':
            j = data.find('>', i)
            if j < 0:
                break
            chars = data[i + 1:j]
            i = j + 1
        else:
            chars = ch
            i += 1
        hold_chars = ''
        if i < n and data[i] == '!':
            hold_chars = data[i + 1] if i + 1 < n else ''
            i += 2
        add(chars, hold_chars)
        beat += step
    return rows


def chart_meta_only(song):
    """Lightweight chart summary for the library cache."""
    return [(c.diff, c.meter, c.desc) for c in song.charts]
