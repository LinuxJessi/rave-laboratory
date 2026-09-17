"""Gameplay: arcade-DDR-style judging and money score (1,000,000 max)."""
import math
import statistics
import time

import pygame

import bgvideo
import wavestrip
import chartstats
import gfx
import simfile
from gfx import COLORS, u

JUDGES = ['marvelous', 'perfect', 'great', 'good', 'miss']
GRADES = [(990000, 'AAA'), (950000, 'AA+'), (900000, 'AA'), (890000, 'AA-'), (850000, 'A+'), (800000, 'A'),
          (790000, 'A-'), (750000, 'B+'), (700000, 'B'), (690000, 'B-'), (650000, 'C+'), (600000, 'C'),
          (590000, 'C-'), (550000, 'D+'), (0, 'D')]
LAMPS = ['FAILED', 'CLEAR', 'LIFE4 CLEAR', 'GOOD FULL COMBO', 'GREAT FULL COMBO', 'PERFECT FULL COMBO', 'MARVELOUS FULL COMBO']


def grade_for(score, failed):
    if failed:
        return 'E'
    return next(g for s, g in GRADES if score >= s)


def speed_multiplier(cfg, main_bpm):
    """main_bpm is the tempo the song spends most of its time at, so a short BPM spike
    or gimmick section doesn't slow the whole song down."""
    if cfg.scroll_mode == 'multiplier':
        return cfg.multiplier
    step = cfg.mult_step
    m = cfg.target_speed / max(1.0, main_bpm)
    return round(max(step, round(m / step) * step), 2)


class Step:
    """A row of notes at one time (a jump is one step)."""
    __slots__ = ('time', 'notes', 'hits', 'judge', 'offset')

    def __init__(self, t):
        self.time = t
        self.notes = []
        self.hits = {}
        self.judge = None
        self.offset = None


class Gameplay:
    name = 'gameplay'

    def __init__(self, app, song, chart, start_at=0.0):
        """start_at > 0 (Lab mode playtest from a measure): arrows before it are left out and the run isn't scored."""
        self.app = app
        self.start_at = max(0.0, start_at)
        self.cfg = app.cfg
        self.sync_ms = getattr(song, 'sync_ms', 0)
        self.song = song
        self.chart = simfile.parse_chart(song, chart)
        self.timing = chart.timing or song.timing
        notes = self.chart.notes
        last_beat = max([n.end_beat or n.beat for n in notes] or [4.0])
        self.bpm_main = chartstats.bpm_estimate(self.timing, last_beat)['dominant']
        taps, self.holds, self.mine_rows = [], [], []
        by_time, mines_by_time = {}, {}
        for n in self.chart.notes:
            if n.time < self.start_at - 0.01:
                continue
            if n.kind == 'mine':
                key = round(n.time, 4)
                if key not in mines_by_time:
                    mines_by_time[key] = {'time': n.time, 'notes': [], 'done': False}
                    self.mine_rows.append(mines_by_time[key])
                mines_by_time[key]['notes'].append(n)
                continue
            key = round(n.time, 4)
            if key not in by_time:
                by_time[key] = Step(n.time)
                taps.append(by_time[key])
            by_time[key].notes.append(n)
            if n.kind in ('hold', 'roll'):
                self.holds.append({'note': n, 'state': 'pending', 'released_at': None, 'last_press': -99.0})
        self.hold_of = {id(h['note']): h for h in self.holds}
        self.step_of = {id(n): st for st in taps for n in st.notes}
        self.steps = taps
        self.col_queue = [[] for _ in range(4)]
        for st in self.steps:
            for n in st.notes:
                self.col_queue[n.col].append((n, st))
        self.col_ptr = [0, 0, 0, 0]
        self.miss_ptr = 0
        self.total = len(self.steps) + len(self.holds) + len(self.mine_rows)
        self.unit = 1000000.0 / max(1, self.total)
        self.raw_score = 0.0
        self.counts = {k: 0 for k in JUDGES}
        self.counts.update(ok=0, ng=0, shock_ok=0, shock_hit=0)
        self.fast = self.slow = 0
        self.combo = self.max_combo = 0
        self.life = 50.0
        self.battery = 4
        self.failed = False
        self.offsets = []
        self.recent = []
        self.releases = []
        self.pending_release = [None] * 4
        self.flickers = 0
        self.events = []
        self.flash = [0.0] * 4
        self.pressed = [False] * 4
        self.judge_show = None
        self.hold_msgs = [None] * 4
        self.end_time = max([n.end_time or n.time for n in self.chart.notes] or [0]) + 2.0
        self.back_held_since = None
        self.updown_since = None
        self.autoplayed = False
        self.done = False
        self.bg = None
        self.volume = self.cfg.game_volume / 100.0
        self._start_clock()
        self.wave = wavestrip.WaveStrip(song.music) if self.cfg.waveform and song.music else None
        self.background = bgvideo.Background(app, song, getattr(song, 'simfile_path', None),
                                              getattr(song, 'orig_timing', None) or song.timing, self.now)

    # ------------------------------------------------------------ clock

    def _start_clock(self):
        pygame.mixer.music.stop()
        self.music_ok = False
        try:
            pygame.mixer.music.load(self.song.music)
            self.music_ok = True
        except Exception as e:
            self.app.toast('Could not load music: %s' % e)
        first = (self.steps[0].time if self.steps else self.start_at) - self.start_at
        lead = max(self.cfg.lead_in_s, 1.5 - first)
        self.music_started = False
        self.planned_start = time.perf_counter() + lead - self.start_at

    def now(self, at=None):
        at = time.perf_counter() if at is None else at
        return at - self.planned_start

    def _maybe_start_music(self):
        if self.music_started:
            return
        if self.now() >= self.start_at:
            if self.music_ok:
                pygame.mixer.music.set_volume(self.volume)
                pygame.mixer.music.play(start=self.start_at)
            # re-anchor the clock to the moment playback was requested
            self.planned_start = time.perf_counter() - self.start_at
            self.music_started = True

    # ------------------------------------------------------------ input

    def on_action(self, action, down, stamp):
        if action in ('left', 'down', 'up', 'right'):
            col = ['left', 'down', 'up', 'right'].index(action)
            debounce = self.cfg.input_debounce_ms / 1000.0
            if not down and debounce > 0:
                self.pending_release[col] = stamp          # applied in update() unless the panel comes back
                return
            if down and self.pending_release[col] is not None:
                self.pending_release[col] = None           # flicker: the foot never really left
                self.flickers += 1
                return
            self.pressed[col] = down
            if not down:
                self.releases.append((round(self.now(stamp) - self.cfg.audio_offset_ms / 1000.0, 4), col))
            if down:
                self.flash[col] = time.perf_counter()
                self._press(col, stamp)
            return
        if action == 'back':
            self.back_held_since = time.perf_counter() if down else None

    def _press(self, col, stamp):
        t = self.now(stamp) - self.cfg.audio_offset_ms / 1000.0
        self.events.append((round(t, 4), col))
        for h in self.holds:
            if h['note'].col == col and h['note'].kind == 'roll':
                h['last_press'] = t
        good = self.cfg.win_good_ms / 1000.0
        q = self.col_queue[col]
        i = self.col_ptr[col]
        while i < len(q) and (q[i][0].col in q[i][1].hits or q[i][1].judge is not None):
            i += 1
        self.col_ptr[col] = i
        best = None
        j = i
        while j < len(q):
            n, st = q[j]
            dt = t - n.time
            if dt < -good:
                break
            if n.col not in st.hits and st.judge is None and abs(dt) <= good:
                if best is None or abs(dt) < abs(best[2]):
                    best = (n, st, dt)
            j += 1
        if best:
            n, st, dt = best
            st.hits[n.col] = dt
            if len(st.hits) == len(st.notes):
                self._judge_step(st)

    def _engaged(self, h):
        """A freeze whose head was stepped on and that hasn't failed yet."""
        if h['state'] in ('ok', 'ng'):
            return False
        n = h['note']
        st = self.step_of.get(id(n))
        return h['state'] == 'active' and h['released_at'] is None or (st is not None and n.col in st.hits)

    def _window(self, dt):
        a = abs(dt) * 1000.0
        c = self.cfg
        if a <= c.win_marvelous_ms:
            return 'marvelous'
        if a <= c.win_perfect_ms:
            return 'perfect'
        if a <= c.win_great_ms:
            return 'great'
        return 'good'

    def _judge_step(self, st):
        offs = list(st.hits.values())
        mode = self.cfg.jump_judge
        if mode == 'average':
            dt = sum(offs) / len(offs)
        elif mode == 'last':
            dt = max(offs)
        else:
            dt = max(offs, key=abs)
        name = self._window(dt)
        st.judge, st.offset = name, dt
        self.offsets.append(dt)
        self.recent.append((dt, time.perf_counter(), name))
        del self.recent[:-24]
        self._apply(name, dt)

    def _apply(self, name, dt=None):
        self.counts[name] += 1
        u_ = self.unit
        self.raw_score += {'marvelous': u_, 'perfect': u_ - 10, 'great': u_ * 0.6 - 10, 'good': u_ * 0.2 - 10, 'miss': 0}[name]
        if name in ('marvelous', 'perfect', 'great'):
            self.combo += 1
        elif name == 'good' and not self.cfg.good_breaks_combo:
            self.combo += 1
        else:
            self.combo = 0
        self.max_combo = max(self.max_combo, self.combo)
        if name == 'miss':
            self._hurt()
        elif name in ('marvelous', 'perfect'):
            self.life = min(100.0, self.life + self.cfg.life_gain)
        elif name == 'great':
            self.life = min(100.0, self.life + self.cfg.life_gain * 0.5)
        early_late = None
        if dt is not None and name != 'marvelous':
            early_late = 'FAST' if dt < 0 else 'SLOW'
            if dt < 0:
                self.fast += 1
            else:
                self.slow += 1
        self.judge_show = (name, time.perf_counter(), early_late, self.combo)

    def close(self):
        self.background.close()

    def _autoplay(self, t):
        i = self.miss_ptr
        while i < len(self.steps) and self.steps[i].time <= t:
            st = self.steps[i]
            if st.judge is None:
                for n in st.notes:
                    st.hits[n.col] = 0.0
                    self.flash[n.col] = time.perf_counter()
                self._judge_step(st)
            i += 1
        for col in range(4):
            self.pressed[col] = any(h['note'].col == col and h['note'].time <= t < h['note'].end_time for h in self.holds)
        for h in self.holds:
            h['last_press'] = t

    def _hurt(self):
        mode = self.cfg.life_mode
        if mode == 'life4':
            self.battery -= 1
            if self.battery <= 0:
                self.failed = True
        elif mode in ('normal', 'no fail', 'fail at end'):
            self.life = max(0.0, self.life - self.cfg.life_miss)
            if self.life <= 0 and mode == 'normal':
                self.failed = True

    # ------------------------------------------------------------ update

    def _apply_releases(self):
        debounce = self.cfg.input_debounce_ms / 1000.0
        pc = time.perf_counter()
        for col, stamp in enumerate(self.pending_release):
            if stamp is not None and pc - stamp >= debounce:
                self.pending_release[col] = None
                self.pressed[col] = False
                self.releases.append((round(self.now(stamp) - self.cfg.audio_offset_ms / 1000.0, 4), col))

    def update(self):
        self._apply_releases()
        self._maybe_start_music()
        now = self.now()
        t = now - self.cfg.audio_offset_ms / 1000.0
        if self.cfg.autoplay:
            self.autoplayed = True
            self._autoplay(t)
        good = self.cfg.win_good_ms / 1000.0
        while self.miss_ptr < len(self.steps) and self.steps[self.miss_ptr].time + good < t:
            st = self.steps[self.miss_ptr]
            if st.judge is None:
                st.judge = 'miss'
                self._apply('miss')
            self.miss_ptr += 1
        grace = self.cfg.hold_grace_ms / 1000.0
        for h in self.holds:
            if h['state'] in ('ok', 'ng'):
                continue
            n = h['note']
            if t < n.time:
                continue
            if n.kind == 'roll':
                ok_now = t - max(h['last_press'], n.time) <= grace
            else:
                ok_now = self.pressed[n.col]
            if ok_now:
                h['released_at'] = None
            elif h['released_at'] is None:
                h['released_at'] = t if h['state'] == 'active' else n.time
            h['state'] = 'active'
            if h['released_at'] is not None and t - h['released_at'] > grace and t < n.end_time:
                h['state'] = 'ng'
                # remember where the freeze was when it failed, so it scrolls off from there
                h['ng_beat'] = self.timing.beat_at(self.now() - self.cfg.visual_offset_ms / 1000.0)
                self.counts['ng'] += 1
                self.combo = 0
                self._hurt()
                self.hold_msgs[n.col] = ('N.G.', time.perf_counter())
            elif t >= n.end_time:
                h['state'] = 'ok'
                self.counts['ok'] += 1
                self.raw_score += self.unit
                self.hold_msgs[n.col] = ('O.K.', time.perf_counter())
        for row in self.mine_rows:
            if row['done'] or t < row['time']:
                continue
            row['done'] = True
            hit = [n.col for n in row['notes'] if self.pressed[n.col]]
            if hit:
                self.counts['shock_hit'] += 1
                self.combo = 0
                self._hurt()
                for col in hit:
                    self.hold_msgs[col] = ('SHOCK', time.perf_counter())
            else:
                self.counts['shock_ok'] += 1
                self.raw_score += self.unit
        # 4-panel pads: stand on Up+Down for 2 s to quit, unless a freeze needs those panels
        if self.pressed[1] and self.pressed[2] and not any(
                h['state'] == 'active' and h['note'].col in (1, 2) for h in self.holds):
            if self.updown_since is None:
                self.updown_since = time.perf_counter()
            elif time.perf_counter() - self.updown_since > 2.0:
                pygame.mixer.music.fadeout(300)
                self.app.to_select()
                return
        else:
            self.updown_since = None
        if self.back_held_since and time.perf_counter() - self.back_held_since > 1.0:
            pygame.mixer.music.fadeout(300)
            self.app.to_select()
            return
        if now > self.end_time and not self.done:
            self.done = True
            pygame.mixer.music.fadeout(800)
            self.app.to_results(self.result())

    # ------------------------------------------------------------ results

    def result(self):
        score = int(self.raw_score // 10 * 10)
        if self.counts['miss'] == 0 and self.counts['ng'] == 0 and self.counts['shock_hit'] == 0:
            score = min(score, 1000000)
        c = self.counts
        mode = self.cfg.life_mode
        failed = (self.failed and mode in ('normal', 'life4')) or (mode == 'fail at end' and self.life <= 0)
        clean = c['miss'] == 0 and c['ng'] == 0 and c['shock_hit'] == 0
        if failed:
            lamp = 0
        elif clean and c['good'] == 0 and c['great'] == 0 and c['perfect'] == 0:
            lamp = 6
        elif clean and c['good'] == 0 and c['great'] == 0:
            lamp = 5
        elif clean and c['good'] == 0:
            lamp = 4
        elif clean:
            lamp = 3
        elif self.cfg.life_mode == 'life4':
            lamp = 2
        else:
            lamp = 1
        ex = c['marvelous'] * 3 + c['perfect'] * 2 + c['great'] + c['ok'] * 3 + c['shock_ok'] * 3
        taps = self.offsets
        stats = {}
        if taps:
            ms = [o * 1000 for o in taps]
            stats = {'mean_ms': round(statistics.fmean(ms), 1), 'median_ms': round(statistics.median(ms), 1),
                     'stdev_ms': round(statistics.pstdev(ms), 1), 'n': len(ms)}
        return {
            'song': self.song, 'chart': self.chart, 'score': score, 'grade': grade_for(score, failed), 'ex': ex,
            'ex_max': self.total * 3, 'counts': dict(c), 'max_combo': self.max_combo, 'fast': self.fast, 'slow': self.slow,
            'cleared': not failed, 'lamp': LAMPS[lamp], 'lamp_rank': lamp, 'offsets_ms': [round(o * 1000, 1) for o in taps],
            'timing': stats, 'audio_offset_ms': self.cfg.audio_offset_ms, 'sync_ms': self.sync_ms,
            'visual_offset_ms': self.cfg.visual_offset_ms, 'events': self.events, 'releases': self.releases, 'flickers': self.flickers, 'autoplay': self.autoplayed or self.start_at > 0,
        }

    # ------------------------------------------------------------ drawing

    def field_x(self):
        c = self.cfg
        size, gap = u(c.arrow_size), u(c.lane_gap)
        width = size * 4 + gap * 3
        if c.field_x == 'left':
            return u(140), width
        if c.field_x == 'right':
            return gfx.W - u(140) - width, width
        return (gfx.W - width) // 2, width

    def draw(self, surf):
        c = self.cfg
        surf.fill(COLORS['bg'])
        bg = self.background.current() if c.bg_brightness > 0 else None
        if bg is not None:
            surf.blit(bg, bg.get_rect(center=(gfx.W // 2, gfx.H // 2)))
            if c.bg_brightness < 100:
                shade = self.app.shade(int(255 * (1 - c.bg_brightness / 100.0)))
                surf.blit(shade, (0, 0))

        now = self.now()
        vis_t = now - c.visual_offset_ms / 1000.0
        size, gap = u(c.arrow_size), u(c.lane_gap)
        x0, width = self.field_x()
        pitch = size + gap
        ry = u(c.receptor_y)
        direction = 1
        if c.reverse:
            ry = gfx.H - ry
            direction = -1
        mult = speed_multiplier(c, self.bpm_main)
        cur_beat = self.timing.beat_at(vis_t)
        constant = c.scroll_mode == 'constant'
        px_beat = size * mult
        px_sec = size * c.target_speed / 60.0

        def y_of(note_time, note_beat):
            if constant:
                return ry + direction * (note_time - vis_t) * px_sec
            return ry + direction * (note_beat - cur_beat) * px_beat

        lane = self.app.shade(110, (width + u(16), gfx.H))
        surf.blit(lane, (x0 - u(8), 0))
        if c.measure_lines or c.eighth_lines:
            self._draw_beat_lines(surf, x0, width, y_of, cur_beat, direction)
        if c.waveform:
            if self.wave is None and self.song.music:
                self.wave = wavestrip.WaveStrip(self.song.music)
            if self.wave is not None:
                self.wave.draw(surf, self.timing, cur_beat, vis_t, ry, direction, px_beat, px_sec, constant, x0)

        pc = time.perf_counter()
        beat_phase = cur_beat % 1.0
        pulse = max(0.0, 1.0 - beat_phase / 0.3)          # 1 on the beat, gone by 30% of the beat
        on_measure = int(math.floor(cur_beat + 1e-6)) % 4 == 0
        upcoming = self._next_note_beats(cur_beat) if c.approach_glow else {}
        for col in range(4):
            cx = x0 + col * pitch
            lit = self.pressed[col] or pc - self.flash[col] < 0.08
            surf.blit(gfx.arrow(size, col, (0, 0, 0), 'receptor_lit' if lit else 'receptor'), (cx, ry - size // 2))
            if not lit and c.beat_flash and pulse > 0:
                strength = pulse * (0.75 if on_measure else 0.45)
                surf.blit(gfx.faded(gfx.arrow(size, col, (0, 0, 0), 'receptor_lit'), strength), (cx, ry - size // 2))
            if col in upcoming:
                # grows over the last beat before the arrow reaches the receptor
                closeness = 1.0 - min(1.0, max(0.0, upcoming[col] - cur_beat))
                if closeness > 0:
                    glow = gfx.arrow(size, col, (255, 255, 255), 'glow')
                    surf.blit(gfx.faded(glow, closeness ** 2 * 0.9), (cx, ry - size // 2))
        arrow_lit = c.arrow_flash and beat_phase < 0.2

        # holds (bodies under heads). Once the head is hit, the freeze stays pinned to the
        # receptor until it ends or goes N.G., even through a brief lift or sensor flicker.
        for h in self.holds:
            n = h['note']
            if h['state'] == 'ok' or n.end_time < vis_t - 0.2:
                continue
            y1 = y_of(n.time, n.beat)
            y2 = y_of(n.end_time, n.end_beat)
            pinned = self._engaged(h)
            if h['state'] == 'ng' and h.get('ng_beat', -1e9) > n.beat:
                y1 = y_of(self.timing.time_at(h['ng_beat']), h['ng_beat'])
            if pinned and (y1 - ry) * direction < 0:
                y1 = ry
            if pinned and (y2 - ry) * direction < 0:
                continue
            if (y1 < -size and y2 < -size) or (y1 > gfx.H + size and y2 > gfx.H + size):
                continue
            cx = x0 + n.col * pitch
            body = self.app.hold_body(size, h['state'], n.kind)
            tail = size // 2
            top, bot = (y1, y2 + tail) if direction > 0 else (y2 - tail, y1)
            if bot - top > 0:
                clip = surf.get_clip()
                surf.set_clip(pygame.Rect(cx, int(top), size, int(bot - top)).clip(clip))
                yy = int(top)
                while yy < bot:
                    surf.blit(body, (cx, yy))
                    yy += body.get_height()
                surf.set_clip(clip)
            if pinned:
                held = h['released_at'] is None and self.pressed[n.col]
                color = (120, 255, 140) if held else gfx.quant_color(n.quant, c.note_colors)
                if arrow_lit:
                    color = gfx.lighter(color)
                surf.blit(gfx.arrow(size, n.col, color), (cx, int(y1) - size // 2))

        # taps and hold heads
        for st in self.steps[max(0, self.miss_ptr - 8):]:
            y = y_of(st.time, st.notes[0].beat)
            if (direction > 0 and y > gfx.H + size) or (direction < 0 and y < -size):
                break
            if st.judge not in (None, 'miss') or (direction > 0 and y < -size) or (direction < 0 and y > gfx.H + size):
                continue
            for n in st.notes:
                if n.col in st.hits:
                    continue
                h = self.hold_of.get(id(n))
                if h and self._engaged(h):
                    continue
                color = (255, 140, 40) if n.kind == 'roll' else gfx.quant_color(n.quant, c.note_colors)
                if arrow_lit:
                    color = gfx.lighter(color)
                surf.blit(gfx.arrow(size, n.col, color), (x0 + n.col * pitch, int(y) - size // 2))

        for row in self.mine_rows:
            if row['done']:
                continue
            y = y_of(row['time'], row['notes'][0].beat)
            if (direction > 0 and y > gfx.H + size) or (direction < 0 and y < -size):
                break
            for n in row['notes']:
                surf.blit(gfx.mine(size), (x0 + n.col * pitch, int(y) - size // 2))

        # hit glow + freeze OK/NG
        for col in range(4):
            msg = self.hold_msgs[col]
            if msg and pc - msg[1] < 0.5:
                colr = COLORS['ok'] if msg[0] == 'O.K.' else COLORS['ng']
                s = gfx.outlined(msg[0], 22, colr)
                surf.blit(s, s.get_rect(center=(x0 + col * pitch + size // 2, ry + direction * u(70))))

        self._draw_judgment(surf, x0, width, pc)
        if c.timing_meter:
            self._draw_timing_meter(surf, x0, width, pc)
        self._draw_hud(surf, x0, width, mult, now)

    def _next_note_beats(self, cur_beat):
        """Beat of the next arrow still to be stepped in each column (within the next 2 beats)."""
        out = {}
        for st in self.steps[self.miss_ptr:]:
            beat = st.notes[0].beat
            if beat > cur_beat + 2.0:
                break
            if st.judge is not None:
                continue
            for n in st.notes:
                if n.col not in out and n.col not in st.hits and beat >= cur_beat - 0.1:
                    out[n.col] = beat
            if len(out) == 4:
                break
        return out

    def _draw_beat_lines(self, surf, x0, width, y_of, cur_beat, direction):
        c = self.cfg
        start = int(math.floor(cur_beat)) - 2
        left, right = x0 - u(8), x0 + width + u(8)
        subs = (0.0, 0.5) if c.eighth_lines else (0.0,)
        for b in range(start, start + 64):
            for sub in subs:
                beat = b + sub
                y = y_of(self.timing.time_at(beat), beat)
                if (direction > 0 and y > gfx.H + 4) or (direction < 0 and y < -4):
                    return
                if not -4 <= y <= gfx.H + 4:
                    continue
                y = int(y)
                if sub:
                    for xx in range(left, right, u(12)):
                        pygame.draw.line(surf, (70, 90, 150), (xx, y), (xx + u(5), y), 1)
                elif not c.measure_lines:
                    continue
                elif b % 4 == 0:
                    pygame.draw.line(surf, (190, 200, 235), (left, y), (right, y), max(1, u(2)))
                    gfx.blit_text(surf, str(b // 4 + 1), 13, (left - u(6), y), (190, 200, 235), True, 'midright')
                else:
                    pygame.draw.line(surf, (85, 95, 130), (left, y), (right, y), 1)

    def _draw_timing_meter(self, surf, x0, width, pc):
        c = self.cfg
        # bottom of the screen (top when arrows scroll downward, so it stays clear of the receptors)
        cy = gfx.H - u(52) if not c.reverse else u(78)
        span = c.win_good_ms
        bar = pygame.Rect(x0, cy - u(5), width, u(10))
        scale = (width / 2.0) / span

        def zone(ms, colr):
            r = pygame.Rect(0, bar.y, int(ms * scale * 2), bar.h)
            r.centerx = bar.centerx
            pygame.draw.rect(surf, colr, r)
        zone(span, (40, 60, 110))
        zone(c.win_great_ms, (40, 110, 60))
        zone(c.win_perfect_ms, (150, 130, 40))
        zone(c.win_marvelous_ms, (200, 200, 215))
        pygame.draw.line(surf, (255, 255, 255), (bar.centerx, bar.y - u(6)), (bar.centerx, bar.bottom + u(6)), max(1, u(2)))
        live = [(dt, when, name) for dt, when, name in self.recent if pc - when < 6.0]
        for dt, when, name in live:
            age = pc - when
            x = bar.centerx + max(-span, min(span, dt * 1000.0)) * scale
            h = u(16) if age < 0.25 else u(11)
            fade = max(0.25, 1.0 - age / 6.0)
            colr = tuple(int(v * fade) for v in COLORS[name])
            pygame.draw.line(surf, colr, (x, bar.centery - h), (x, bar.centery + h), max(2, u(3)))
        if len(live) >= 4:
            avg = sum(dt for dt, _, _ in live) / len(live) * 1000.0
            ax = bar.centerx + max(-span, min(span, avg)) * scale
            pygame.draw.polygon(surf, COLORS['accent'], [(ax, bar.bottom + u(8)), (ax - u(7), bar.bottom + u(18)), (ax + u(7), bar.bottom + u(18))])
            gfx.blit_text(surf, '%+d ms' % round(avg), 13, (ax, bar.bottom + u(20)), COLORS['accent'], True, 'midtop')
        gfx.blit_text(surf, 'EARLY', 11, (bar.x, bar.bottom + u(4)), COLORS['dim'], True)
        gfx.blit_text(surf, 'LATE', 11, (bar.right, bar.bottom + u(4)), COLORS['dim'], True, 'topright')

    def _draw_judgment(self, surf, x0, width, pc):
        if not self.judge_show:
            return
        name, when, el, combo = self.judge_show
        age = pc - when
        if age > 0.9:
            return
        c = self.cfg
        cy = u(c.judge_y) if not c.reverse else gfx.H - u(c.judge_y)
        pop = 1.0 + max(0.0, 0.18 - age) * 1.2
        label = name.upper()
        s = gfx.outlined(label, 46, COLORS[name])
        if pop != 1.0:
            s = pygame.transform.smoothscale(s, (int(s.get_width() * pop), int(s.get_height() * pop)))
        if age > 0.6:
            s = s.copy()
            s.set_alpha(int(255 * (0.9 - age) / 0.3))
        surf.blit(s, s.get_rect(center=(x0 + width // 2, cy)))
        if combo >= 4 and name != 'miss':
            cs = gfx.outlined('%d COMBO' % combo, 26, COLORS['text'])
            surf.blit(cs, cs.get_rect(center=(x0 + width // 2, cy + u(46))))
        if el and c.show_early_late:
            es = gfx.outlined(el, 20, (90, 170, 255) if el == 'FAST' else (255, 120, 80))
            surf.blit(es, es.get_rect(center=(x0 + width // 2, cy - u(40))))

    def _draw_life(self, surf, bar):
        c = self.cfg
        t = time.perf_counter()
        if c.life_mode == 'off':
            return
        if c.life_mode == 'life4':
            full, danger, level = self.battery >= 4, self.battery == 1, self.battery / 4.0
        else:
            full, danger, level = self.life >= 100, 0 < self.life < 25, self.life / 100.0
        edge = (0, 0, 0)
        if danger:
            # flash faster as the bar empties
            rate = 3.0 + (1.0 - level / 0.25) * 5.0 if c.life_mode != 'life4' else 6.0
            pulse = 0.5 + 0.5 * math.sin(t * rate * math.pi)
            edge = (int(90 + 165 * pulse), int(20 * pulse), int(30 * pulse))
        pygame.draw.rect(surf, edge, bar.inflate(u(6), u(6)), border_radius=u(4))
        pygame.draw.rect(surf, (40, 44, 60), bar)
        if c.life_mode == 'life4':
            seg = (bar.w - u(9)) // 4
            fills = [pygame.Rect(bar.x + i * (seg + u(3)), bar.y, seg, bar.h) for i in range(self.battery)]
        else:
            fills = [pygame.Rect(bar.x, bar.y, int(bar.w * min(1.0, self.life / 100.0)), bar.h)]
        if full:
            colr = None
        elif danger:
            pulse = 0.5 + 0.5 * math.sin(t * 8 * math.pi)
            colr = (255, int(60 + 150 * pulse), int(70 + 150 * pulse))
        else:
            colr = (80, 230, 255)
        for r in fills:
            if colr is None:
                # animated rainbow when the gauge is full
                strip = self.app.rainbow(bar.w, bar.h)
                shift = int((t * 0.35 % 1.0) * bar.w)
                clip = surf.get_clip()
                surf.set_clip(r.clip(clip))
                surf.blit(strip, (r.x - shift, r.y))
                surf.set_clip(clip)
            else:
                pygame.draw.rect(surf, colr, r)
        if full:
            # a light sweep plus twinkling sparkles
            sweep_x = bar.x + int(((t * 0.9) % 1.4 - 0.2) * bar.w)
            glow = self.app.shade(0, (u(60), bar.h)).copy()
            glow.fill((255, 255, 255, 0))
            for i in range(u(60)):
                a = int(150 * (1 - abs(i - u(30)) / float(u(30))))
                pygame.draw.line(glow, (255, 255, 230, max(0, a)), (i, 0), (i, bar.h))
            clip = surf.get_clip()
            surf.set_clip(bar)
            surf.blit(glow, (sweep_x - u(30), bar.y))
            surf.set_clip(clip)
            for i in range(14):
                phase = (t * 1.7 + i * 0.37) % 1.0
                seed = (i * 7919 + int(t * 1.7 + i * 0.37) * 104729) % 1000
                sx = bar.x + seed / 1000.0 * bar.w
                sy = bar.y + ((seed * 37) % 1000) / 1000.0 * bar.h
                size = u(6) * math.sin(phase * math.pi)
                if size < 1:
                    continue
                col = (255, 255, 255)
                pygame.draw.line(surf, col, (sx - size, sy), (sx + size, sy), max(1, u(2)))
                pygame.draw.line(surf, col, (sx, sy - size), (sx, sy + size), max(1, u(2)))
        elif danger:
            pulse = 0.5 + 0.5 * math.sin(t * 8 * math.pi)
            flash = pygame.Surface(bar.size, pygame.SRCALPHA)
            flash.fill((255, 40, 60, int(70 * pulse)))
            surf.blit(flash, bar)
            gfx.blit_text(surf, 'DANGER', 14, (bar.centerx, bar.centery), (255, 255, 255) if pulse > 0.5 else (255, 120, 130), True, 'center')

    def _draw_hud(self, surf, x0, width, mult, now):
        c = self.cfg
        # life bar across the top of the playfield
        bar = pygame.Rect(x0, u(18), width, u(22))
        self._draw_life(surf, bar)
        if self.failed:
            gfx.blit_text(surf, 'FAILED (playing on)', 16, (bar.centerx, bar.bottom + u(6)), COLORS['miss'], True, 'midtop')
        elif c.life_mode == 'fail at end' and self.life <= 0:
            gfx.blit_text(surf, 'EMPTY: recover before the end to pass', 16, (bar.centerx, bar.bottom + u(6)), COLORS['miss'], True, 'midtop')
        # score
        score = int(self.raw_score // 10 * 10)
        sx = x0 + width + u(40) if c.field_x != 'right' else x0 - u(40)
        anchor = 'topleft' if c.field_x != 'right' else 'topright'
        gfx.blit_text(surf, '{:,}'.format(score).replace(',', ' '), 40, (sx, gfx.H - u(80)), COLORS['text'], True, anchor)
        s = self.song
        gfx.blit_text(surf, s.title, 20, (sx, u(18)), COLORS['text'], True, anchor, max_w=u(380))
        diff = self.chart
        gfx.blit_text(surf, '%s %d' % (simfile.DIFF_NAMES.get(diff.diff, diff.diff), diff.meter), 18,
                      (sx, u(46)), COLORS[diff.diff], True, anchor)
        speed = 'CMOD %d' % c.target_speed if c.scroll_mode == 'constant' else 'x%g  (read %d)' % (mult, round(mult * self.bpm_main))
        gfx.blit_text(surf, speed, 16, (sx, u(72)), COLORS['dim'], False, anchor)
        if now < self.start_at:
            gfx.blit_text(surf, 'To quit: stand on Up+Down 2 s, or hold Back / Esc 1 s', 16, (sx, u(96)), COLORS['dim'], False, anchor)
        # progress
        total = max(1.0, self.end_time)
        p = max(0.0, min(1.0, now / total))
        pygame.draw.rect(surf, (40, 44, 60), (0, gfx.H - u(4), gfx.W, u(4)))
        pygame.draw.rect(surf, COLORS['cyan'], (0, gfx.H - u(4), int(gfx.W * p), u(4)))
