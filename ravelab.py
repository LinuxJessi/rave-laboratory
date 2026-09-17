"""Rave Laboratory: a DDR-style player for your Project OutFox song folders, plus Lab mode for charting your own songs.

Run:  python ravelab.py            (or double-click "Rave Laboratory.pyw" / .command / .sh, or the built app)
      --windowed  --outfox PATH  --selftest  --bench
Pad:  Left/Right choose, Up/Down difficulty, Start or Left+Right together = choose (hold = favorite), Back or Up+Down = back
Keys: arrows, Enter, Esc, Space x2 or / search, F favorite, Tab sort, -/= speed, [/] offset, F1 design, F2 note
Lab mode (Who's playing? > Lab mode): chart your own songs and videos with an AI assistant, see lab_screen.py
"""
import colorsys
import ctypes
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')

import pygame  # noqa: E402

import gfx  # noqa: E402
import chartsync  # noqa: E402
import coach  # noqa: E402
import library  # noqa: E402
import pads  # noqa: E402
import paths  # noqa: E402
import profiles  # noqa: E402
from pad_screen import PadSetupScreen  # noqa: E402
from profile_screen import ProfileScreen  # noqa: E402
import settings  # noqa: E402
import simfile  # noqa: E402
from design import DesignOverlay, NoteBox  # noqa: E402
from gameplay import GRADES, Gameplay  # noqa: E402
from gfx import COLORS, u  # noqa: E402
from select_screen import SelectScreen  # noqa: E402

VERSION = '1.0.0'
ARROW_KEYS = {pygame.K_LEFT: 'left', pygame.K_DOWN: 'down', pygame.K_UP: 'up', pygame.K_RIGHT: 'right',
              pygame.K_KP4: 'left', pygame.K_KP2: 'down', pygame.K_KP8: 'up', pygame.K_KP6: 'right',
              pygame.K_RETURN: 'start', pygame.K_KP_ENTER: 'start', pygame.K_ESCAPE: 'back', pygame.K_BACKSPACE: 'back'}


# ==================================================================== results

class ResultsScreen:
    name = 'results'

    def __init__(self, app, res):
        self.app = app
        self.res = res
        song, chart = res['song'], res['chart']
        detail = {k: v for k, v in res.items() if k not in ('song', 'chart')}
        detail.update(rel=song.rel, title=song.title, diff=chart.diff, meter=chart.meter, desc=chart.desc,
                      time=time.strftime('%Y-%m-%d %H:%M:%S'),
                      settings={k: app.cfg.values[k] for k in app.cfg.values if k.startswith(('win_', 'audio', 'visual', 'hold', 'life', 'target', 'scroll', 'auto_sync'))})
        if res['autoplay']:
            self.is_best, self.prev = False, None
        else:
            self.is_best, self.prev = app.scores.record(song.rel, chart.key, res, detail)
        t = res['timing']
        self.suggest = None
        if t and t['n'] >= 20 and abs(t['median_ms']) >= 6 and not res['autoplay']:
            self.suggest = int(round((app.cfg.audio_offset_ms + t['median_ms']) / 5.0) * 5)
        self.applied = False
        self.opened = time.perf_counter()
        self.coach = None             # CoachRequest while asking / after answering
        self.coach_open = False
        if app.cfg.coach != 'off' and app.cfg.coach_auto and not res['autoplay']:
            self.ask_coach()

    def ask_coach(self):
        if self.app.cfg.coach == 'off':
            self.app.toast('The coach is off: F1 > Coach to turn it on')
            return
        if self.coach is None or (self.coach.done and self.coach.error):
            res = self.res
            history = []
            runs = self.app.scores.runs_dir
            try:
                for name in sorted(os.listdir(runs))[:-1]:          # the newest file is this run
                    with open(os.path.join(runs, name), encoding='utf-8') as f:
                        h = json.load(f)
                    if h.get('rel') == res['song'].rel and h.get('diff') == res['chart'].diff:
                        history.append(h)
            except (OSError, ValueError):
                pass
            summary = coach.summarize(res, history)
            self.coach = coach.CoachRequest(self.app.cfg.coach, self.app.cfg.coach_claude_model, summary, self._save_coach,
                                            self.app.cfg.claude_code_model)
        self.coach_open = True

    def _save_coach(self, req):
        entry = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'song': self.res['song'].rel, 'chart': self.res['chart'].key,
                 'provider': req.label, 'text': req.text, 'error': req.error, 'summary': req.summary}
        path = os.path.join(os.path.dirname(self.app.scores.path), 'coach.jsonl')
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def on_action(self, action, down, stamp):
        if not down or time.perf_counter() - self.opened < 0.8:
            return
        if action == 'up' and self.app.cfg.coach != 'off':
            if self.coach_open and self.coach and self.coach.done:
                self.coach_open = False
            else:
                self.ask_coach()
            return
        self.app.to_select()

    def key(self, ev):
        if ev.key == pygame.K_o and self.suggest is not None and not self.applied:
            self.apply()
        elif ev.key == pygame.K_c:
            if self.coach_open and self.coach and self.coach.done:
                self.coach_open = False
            else:
                self.ask_coach()

    def apply(self):
        self.app.cfg.set('audio_offset_ms', max(-300, min(300, self.suggest)))
        self.applied = True
        self.app.toast('Judge offset set to %+d ms for every player' % self.app.cfg.audio_offset_ms)

    def update(self):
        pass

    def draw(self, surf):
        r = self.res
        surf.fill(COLORS['bg'])
        song, chart = r['song'], r['chart']
        gfx.blit_text(surf, song.title, 30, (u(40), u(28)), COLORS['text'], True, max_w=u(800))
        gfx.blit_text(surf, '%s %d' % (simfile.DIFF_NAMES.get(chart.diff, chart.diff), chart.meter), 22,
                      (u(40), u(70)), COLORS[chart.diff], True)
        gcol = COLORS['accent'] if r['grade'].startswith('AA') else COLORS['cyan'] if r['grade'][0] in 'AB' else COLORS['miss'] if r['grade'] == 'E' else COLORS['text']
        g = gfx.outlined(r['grade'], 150, gcol, px=4)
        surf.blit(g, g.get_rect(center=(u(230), u(250))))
        gfx.blit_text(surf, r['lamp'], 22, (u(230), u(345)), COLORS['accent'] if r['lamp_rank'] >= 3 else COLORS['text'], True, 'center')
        gfx.blit_text(surf, '{:,}'.format(r['score']), 54, (u(230), u(400)), COLORS['text'], True, 'center')
        gfx.blit_text(surf, 'EX %d / %d' % (r['ex'], r['ex_max']), 20, (u(230), u(460)), COLORS['dim'], False, 'center')
        if self.is_best and self.prev:
            gfx.blit_text(surf, 'NEW BEST  (+{:,})'.format(r['score'] - self.prev.get('score', 0)), 20, (u(230), u(492)), COLORS['accent'], True, 'center')
        elif self.prev:
            gfx.blit_text(surf, 'Best {:,}'.format(self.prev.get('score', 0)), 18, (u(230), u(492)), COLORS['dim'], False, 'center')
        if r['grade'] not in ('AAA', 'E'):
            nxt = min((s, g) for s, g in GRADES if s > r['score'])
            gfx.blit_text(surf, 'Next grade %s at {:,}'.format(nxt[0]) % nxt[1], 16, (u(230), u(522)), COLORS['dim'], False, 'center')

        c = r['counts']
        rows = [('MARVELOUS', c['marvelous'], 'marvelous'), ('PERFECT', c['perfect'], 'perfect'), ('GREAT', c['great'], 'great'),
                ('GOOD', c['good'], 'good'), ('MISS', c['miss'], 'miss'), ('O.K. (freeze)', c['ok'], 'ok'), ('N.G.', c['ng'], 'ng')]
        if c['shock_ok'] or c['shock_hit']:
            rows.append(('SHOCK hit', c['shock_hit'], 'miss'))
        x, y = u(470), u(120)
        for label, n, key in rows:
            gfx.blit_text(surf, label, 24, (x, y), COLORS[key], True)
            gfx.blit_text(surf, str(n), 26, (x + u(330), y), COLORS['text'], True, 'topright')
            y += u(38)
        y += u(8)
        gfx.blit_text(surf, 'MAX COMBO', 20, (x, y), COLORS['dim'], True)
        gfx.blit_text(surf, str(r['max_combo']), 22, (x + u(330), y), COLORS['text'], True, 'topright')
        y += u(32)
        gfx.blit_text(surf, 'FAST / SLOW', 20, (x, y), COLORS['dim'], True)
        gfx.blit_text(surf, '%d / %d' % (r['fast'], r['slow']), 22, (x + u(330), y), COLORS['text'], True, 'topright')

        self.draw_timing(surf, pygame.Rect(u(860), u(120), u(380), u(300)))
        coach_hint = '   Up (or C) ask the coach' if self.app.cfg.coach != 'off' else ''
        gfx.blit_text(surf, 'Step Left/Right/Down (or Enter) to continue%s   F2 leave a note' % coach_hint, 18,
                      (gfx.W // 2, gfx.H - u(40)), COLORS['dim'], False, 'center')
        if self.coach_open and self.coach:
            self.draw_coach(surf)

    def draw_coach(self, surf):
        req = self.coach
        box = pygame.Rect(u(840), u(100), u(420), u(560))
        bg = pygame.Surface(box.size, pygame.SRCALPHA)
        bg.fill((10, 12, 28, 245))
        surf.blit(bg, box)
        pygame.draw.rect(surf, (255, 140, 220), box, max(1, u(3)), border_radius=u(10))
        x, y = box.x + u(18), box.y + u(14)
        gfx.blit_text(surf, 'COACH', 22, (x, y), (255, 140, 220), True)
        gfx.blit_text(surf, req.label, 13, (box.right - u(18), y + u(8)), COLORS['dim'], anchor='topright', max_w=u(260))
        y += u(40)
        if not req.done:
            dots = '.' * (1 + int((time.perf_counter() - req.started) * 2) % 3)
            gfx.blit_text(surf, 'Looking at your steps' + dots, 18, (x, y), COLORS['text'])
            gfx.blit_text(surf, 'You can move on; the answer is saved either way.', 14, (x, y + u(30)), COLORS['dim'])
            return
        body = req.text or req.error or ''
        colr = COLORS['text'] if req.text else COLORS['miss']
        for para in body.split('\n'):
            for line in _wrap_px(para, 16, box.w - u(36)) or ['']:
                if y > box.bottom - u(56):
                    break
                gfx.blit_text(surf, line, 16, (x, y), colr)
                y += u(22)
            y += u(4)
        gfx.blit_text(surf, 'Up (or C) hides this. Saved to your player coach log.', 13, (x, box.bottom - u(28)), COLORS['dim'])


    def draw_timing(self, surf, box):
        r = self.res
        pygame.draw.rect(surf, COLORS['panel'], box, border_radius=u(8))
        gfx.blit_text(surf, 'Timing (ms, early ← → late)', 18, (box.x + u(14), box.y + u(10)), COLORS['text'], True)
        offs = r['offsets_ms']
        plot = pygame.Rect(box.x + u(14), box.y + u(46), box.w - u(28), u(140))
        pygame.draw.line(surf, COLORS['line'], (plot.centerx, plot.y), (plot.centerx, plot.bottom))
        cfg = self.app.cfg
        span = cfg.win_good_ms
        bins = 29
        counts = [0] * bins
        for o in offs:
            i = int((o + span) / (2 * span) * bins)
            counts[max(0, min(bins - 1, i))] += 1
        peak = max(counts) or 1
        bw = plot.w / bins
        for i, n in enumerate(counts):
            mid = -span + (i + 0.5) * 2 * span / bins
            a = abs(mid)
            colr = COLORS['marvelous'] if a <= cfg.win_marvelous_ms else COLORS['perfect'] if a <= cfg.win_perfect_ms else COLORS['great'] if a <= cfg.win_great_ms else COLORS['good']
            h = int(plot.h * n / peak)
            pygame.draw.rect(surf, colr, (plot.x + int(i * bw) + 1, plot.bottom - h, max(1, int(bw) - 2), h))
        gfx.blit_text(surf, '-%d' % span, 13, (plot.x, plot.bottom + u(4)), COLORS['dim'])
        gfx.blit_text(surf, '+%d' % span, 13, (plot.right, plot.bottom + u(4)), COLORS['dim'], anchor='topright')
        t = r['timing']
        y = plot.bottom + u(28)
        if t:
            gfx.blit_text(surf, 'median %+.0f   mean %+.0f   spread %.0f' % (t['median_ms'], t['mean_ms'], t['stdev_ms']), 16, (box.x + u(14), y), COLORS['text'])
            y += u(26)
        if self.suggest is not None:
            lo = 'late' if t['median_ms'] > 0 else 'early'
            note = pygame.Rect(box.x, box.bottom + u(16), box.w, u(96))
            pygame.draw.rect(surf, COLORS['panel2'], note, border_radius=u(8))
            pygame.draw.rect(surf, COLORS['great'] if self.applied else COLORS['accent'], note, max(1, u(3)), border_radius=u(8))
            if self.applied:
                gfx.blit_text(surf, 'Judge offset now %+d ms (all players)' % self.app.cfg.audio_offset_ms, 20, (note.x + u(16), note.y + u(14)), COLORS['great'], True)
                gfx.blit_text(surf, 'Try this song again to compare.', 16, (note.x + u(16), note.y + u(52)), COLORS['text'])
            else:
                gfx.blit_text(surf, 'Your steps were %d ms %s' % (abs(t['median_ms']), lo), 20, (note.x + u(16), note.y + u(10)), COLORS['accent'], True)
                gfx.blit_text(surf, 'One song is not enough to change the game-wide offset.', 15, (note.x + u(16), note.y + u(42)), COLORS['text'])
                gfx.blit_text(surf, 'O on the keyboard sets it to %+d ms for every player' % self.suggest, 14, (note.x + u(16), note.y + u(66)), COLORS['dim'])


def _wrap_px(text, size, width):
    words, lines, cur = text.split(), [], ''
    for w in words:
        trial = (cur + ' ' + w).strip()
        if gfx.text(trial, size).get_width() > width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


# ==================================================================== app

class App:
    def __init__(self, windowed=False):
        if sys.platform == 'win32':
            try:
                ctypes.windll.user32.SetProcessDPIAware()
                # own taskbar entry and icon instead of grouping under pythonw
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('RaveLaboratory.Game')
            except Exception:
                pass
        self.cfg = settings.Settings()
        pygame.mixer.pre_init(44100, -16, 2, 512)
        pygame.init()
        pygame.display.set_caption('Rave Laboratory')
        for icon in ('Rave Laboratory.png', 'Rave Laboratory.ico'):
            try:
                pygame.display.set_icon(pygame.image.load(paths.resource(icon)))
                break
            except (pygame.error, FileNotFoundError):
                continue
        h = int(self.cfg.render_height)
        w = h * 16 // 9
        flags = pygame.SCALED | (pygame.FULLSCREEN if self.cfg.fullscreen and not windowed else 0)
        self.vsync = bool(self.cfg.vsync)
        try:
            self.screen = pygame.display.set_mode((w, h), flags, vsync=1 if self.vsync else 0)
        except pygame.error:
            self.vsync = False
            self.screen = pygame.display.set_mode((w, h), flags)
        gfx.setup(w, h)
        pygame.key.stop_text_input()
        self.pads = pads.PadManager(self.cfg)
        for i in range(pygame.joystick.get_count()):
            try:
                j = pygame.joystick.Joystick(i)
                if j.get_instance_id() not in self.pads.pads:
                    self.pads.add(j)
            except pygame.error:
                pass
        self.images = gfx.Images()
        self.library = library.Library()
        self.sync = chartsync.SyncBook()
        self.profiles = profiles.Profiles()
        self.profiles.migrate_legacy(self.cfg.machine)
        start = next((p for p in self.profiles.all() if p.id == self.profiles.index.get('last')), None)
        self.profile = start or self.profiles.all()[0] if self.profiles.all() else self.profiles.create('Player 1', {})
        self.cfg.use_profile(self.profile)
        self.scores = library.ScoreBook(self.profile.scores_path, self.profile.runs_dir)
        self.design = DesignOverlay(self)
        self.notes = NoteBox(self)
        self.select = SelectScreen(self)
        self.screen_obj = ProfileScreen(self)
        self.toasts = []
        self._shades = {}
        self._bodies = {}
        self.clock = pygame.time.Clock()
        self.fps_hist = []
        self.last_poll = 0.0
        self.bench = None
        self.lab_return = None        # Lab mode editor to go back to after a playtest

    # ---------------------------------------------------------- helpers

    def toast(self, msg):
        self.toasts.append((msg, time.perf_counter()))
        self.toasts = self.toasts[-4:]

    def shade(self, alpha, size=None):
        size = size or (gfx.W, gfx.H)
        key = (alpha, size)
        if key not in self._shades:
            s = pygame.Surface(size, pygame.SRCALPHA)
            s.fill((0, 0, 0, max(0, min(255, alpha))))
            self._shades[key] = s
        return self._shades[key]

    def rainbow(self, w, h):
        """A seamless rainbow strip twice as wide as the bar, for scrolling."""
        key = ('rainbow', w, h)
        if key not in self._bodies:
            s = pygame.Surface((w * 2, h))
            for x in range(w * 2):
                r, g, b = colorsys.hsv_to_rgb((x / float(w)) % 1.0, 0.75, 1.0)
                pygame.draw.line(s, (int(r * 255), int(g * 255), int(b * 255)), (x, 0), (x, h))
            shine = pygame.Surface((w * 2, max(1, h // 3)), pygame.SRCALPHA)
            shine.fill((255, 255, 255, 70))
            s.blit(shine, (0, 0))
            self._bodies[key] = s.convert()
        return self._bodies[key]

    def hold_body(self, size, state, kind):
        key = (size, state, kind)
        if key not in self._bodies:
            s = pygame.Surface((size, size), pygame.SRCALPHA)
            if kind == 'roll':
                base = (255, 150, 50)
            else:
                base = (90, 230, 120)
            if state == 'ng':
                base = (110, 110, 120)
            alpha = 230 if state == 'active' else 170
            inset = size // 5
            pygame.draw.rect(s, base + (alpha,), (inset, 0, size - 2 * inset, size))
            pygame.draw.rect(s, (255, 255, 255, 90), (inset + size // 10, 0, size // 12, size))
            if kind == 'roll':
                for yy in range(0, size, size // 4):
                    pygame.draw.line(s, (120, 60, 10, 200), (inset, yy), (size - inset, yy + size // 8), max(2, size // 20))
            self._bodies[key] = s
        return self._bodies[key]

    def settings_changed(self, key):
        if key in ('fullscreen', 'vsync', 'render_height'):
            self.toast('Restart the game to apply that one')

    # ---------------------------------------------------------- pads and Design Mode buttons

    def start_hint(self):
        return 'Start or ←+→' if self.pads.any_start() else '←+→'

    def back_hint(self):
        return 'Back or ↑+↓' if any(p.bindings.get('back') for p in self.pads.pads.values()) else '↑+↓'

    def open_pad_setup(self, pad=None):
        if isinstance(self.screen_obj, Gameplay):
            self.toast('Finish the song first, then set up the pad')
            return
        if isinstance(self.screen_obj, PadSetupScreen):
            return
        self.screen_obj = PadSetupScreen(self, self.screen_obj, pad)

    def maybe_pad_setup(self):
        """A pad we can't make sense of was plugged in: ask the player to step on its panels."""
        if not self.pads.new_unmapped or self.design.open or self.notes.open:
            return
        if isinstance(self.screen_obj, (Gameplay, PadSetupScreen)) or not self.library.ready:
            return
        pad = self.pads.new_unmapped[0]
        self.toast('New pad: %s. Step on each panel to set it up (Esc skips).' % pad.name)
        self.open_pad_setup(pad)

    def import_outfox(self):
        report = self.profiles.import_outfox(self.library, self.cfg.machine)
        self.scores = library.ScoreBook(self.profile.scores_path, self.profile.runs_dir)
        if report:
            self.toast('Imported from OutFox: ' + ', '.join('%s (%d charts)' % r for r in report))
        else:
            self.toast('No OutFox profiles found at ' + paths.LOCAL_PROFILES)
        return report

    def design_button(self, key):
        if key == 'pad_setup':
            self.open_pad_setup()
        elif key == 'outfox_import':
            self.import_outfox()
        elif key == 'rescan':
            self.library.rescan()
            self.toast('Looking for songs in ' + ', '.join(self.library.roots))

    def design_button_label(self, key):
        if key == 'pad_setup':
            names = [p.summary() for p in self.pads.pads.values()]
            return '; '.join(names) if names else 'no pad connected (keyboard arrows work)'
        if key == 'outfox_import':
            if not os.path.isdir(paths.LOCAL_PROFILES):
                return 'OutFox profiles not found'
            return 'last import %s' % (self.profiles.index.get('outfox_imported') or 'never')[:16]
        if key == 'rescan':
            return '%d songs' % len(self.library.by_rel)
        return ''

    def context(self):
        ctx = {'screen': self.screen_obj.name, 'player': self.profile.name}
        if isinstance(self.screen_obj, Gameplay):
            g = self.screen_obj
            ctx.update(song=g.song.rel, chart='%s %d %s' % (g.chart.diff, g.chart.meter, g.chart.desc), song_time=round(g.now(), 2))
        elif isinstance(self.screen_obj, SelectScreen) and self.select.entry():
            e = self.select.entry()
            ctx.update(song=e['rel'], chart=' '.join(str(x) for x in e['charts'][self.select.chart_i]))
        elif isinstance(self.screen_obj, ResultsScreen):
            r = self.screen_obj.res
            ctx.update(song=r['song'].rel, chart='%s %d' % (r['chart'].diff, r['chart'].meter), score=r['score'])
        return ctx

    # ---------------------------------------------------------- screens

    def start_song(self, entry, chart_sig):
        pygame.mixer.music.fadeout(200)
        song = simfile.load_song(entry.get('dir') or os.path.join(library.SONGS, *entry['rel'].split('/')), entry['rel'])
        if not song:
            self.toast('Could not read that song')
            return
        song.orig_timing = song.timing        # backgrounds follow the music, not the sync-corrected chart
        song.sync_ms = self.sync.correction_ms(entry, compute_now=True) if self.cfg.auto_sync else 0
        if song.sync_ms:
            # the music is ahead of (lag < 0) or behind the chart: move every note by that much
            shift = song.sync_ms / 1000.0
            for obj in [song] + song.charts:
                t = obj.timing
                if t is not None:
                    obj.timing = simfile.Timing(t.offset - shift, t.bpms, t.stops, t.delays, t.warps)
        d, m, desc = chart_sig
        chart = next((c for c in song.charts if (c.diff, c.meter, c.desc) == (d, m, desc)), None) or song.charts[0]
        self.sync.paused = True
        self.screen_obj = Gameplay(self, song, chart)

    def leave_screen(self):
        self.sync.paused = False
        close = getattr(self.screen_obj, 'close', None)
        if close:
            close()

    def set_profile(self, profile):
        if profile is self.profile or (self.profile and profile.id == self.profile.id and self.select.built):
            self.screen_obj = self.select          # same player: go back to the song list where it was
            self.select.preview_rel = None
            self.select.on_cursor()
            return
        self.profile = profile
        self.cfg.use_profile(profile)
        self.scores = library.ScoreBook(profile.scores_path, profile.runs_dir)
        self.profiles.set_last(profile)
        pygame.mixer.music.fadeout(300)
        self.select = SelectScreen(self)
        self.screen_obj = self.select
        self.toast('Playing as %s' % profile.name)

    def to_profiles(self):
        self.leave_screen()
        pygame.mixer.music.fadeout(300)
        self.screen_obj = ProfileScreen(self)

    def to_results(self, res):
        self.leave_screen()
        self.screen_obj = ResultsScreen(self, res)

    def to_lab(self):
        from lab_screen import LabScreen
        self.leave_screen()
        pygame.mixer.music.fadeout(300)
        self.screen_obj = LabScreen(self)

    def playtest(self, editor, folder, rel, diff, start_at):
        """Play a Lab mode chart; quitting or the results screen comes back to the editor."""
        song = simfile.load_song(folder, rel)
        chart = next((c for c in song.charts if c.diff == diff), None) if song else None
        if not chart:
            self.toast('Save a chart with arrows first')
            return
        pygame.mixer.music.stop()
        song.orig_timing = song.timing
        song.sync_ms = 0
        self.lab_return = editor
        self.sync.paused = True
        self.screen_obj = Gameplay(self, song, chart, start_at=start_at)

    def to_select(self):
        if self.lab_return is not None:
            editor, self.lab_return = self.lab_return, None
            self.leave_screen()
            pygame.mixer.music.fadeout(300)
            self.screen_obj = editor
            editor.resume()
            return
        self.leave_screen()
        pygame.mixer.music.fadeout(300)
        self.select.preview_rel = None
        self.select.preview_due = time.perf_counter() + 0.6
        self.select.build(self.select.entry()['rel'] if self.select.entry() else None)
        self.screen_obj = self.select

    # ---------------------------------------------------------- input

    def handle(self, ev, stamp):
        in_game = isinstance(self.screen_obj, Gameplay)
        if ev.type == pygame.QUIT:
            return False
        if ev.type == pygame.JOYDEVICEADDED:
            try:
                j = pygame.joystick.Joystick(ev.device_index)
            except pygame.error:
                return True
            if j.get_instance_id() not in self.pads.pads:
                pad = self.pads.add(j)
                self.toast('Pad connected: ' + pad.summary())
            return True
        if ev.type == pygame.JOYDEVICEREMOVED:
            pad = self.pads.remove(ev.instance_id)
            if pad:
                self.toast('Pad removed: ' + pad.name)
            return True
        if self.notes.open and ev.type in (pygame.KEYDOWN, pygame.TEXTINPUT):
            self.notes.key(ev)
            return True
        wants_text = getattr(self.screen_obj, 'wants_text', None)
        if wants_text and wants_text() and ev.type in (pygame.KEYDOWN, pygame.TEXTINPUT)                 and not (ev.type == pygame.KEYDOWN and ev.key in (pygame.K_F1, pygame.K_F2)):
            self.screen_obj.text_event(ev)
            return True
        if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP, pygame.MOUSEMOTION, pygame.MOUSEWHEEL, pygame.DROPFILE):
            if hasattr(self.screen_obj, 'mouse') and not self.design.open:
                self.screen_obj.mouse(ev)
            return True
        if getattr(self.screen_obj, 'raw_keys', False) and ev.type in (pygame.KEYDOWN, pygame.KEYUP)                 and not (ev.key in (pygame.K_F1, pygame.K_F2) or self.design.open):
            self.screen_obj.key(ev)
            return True
        if ev.type in (pygame.JOYBUTTONDOWN, pygame.JOYBUTTONUP, pygame.JOYHATMOTION, pygame.JOYAXISMOTION):
            raw = self.pads.raw_events(ev)
            if not raw:
                return True
            if hasattr(self.screen_obj, 'raw_pad'):
                for pad, code, down in raw:
                    self.screen_obj.raw_pad(pad, code, down)
                return True
            if self.design.open and settings.SECTIONS[self.design.section] == 'Controls':
                for pad, code, down in raw:
                    if down:
                        self.toast('%s: %s' % (pad.name, pads.describe_code(code)))
            for pad, code, down in raw:
                for action in pad.lookup.get(code, ()):
                    if self.design.open and not in_game:
                        if down:
                            self.design.pad(action)
                    else:
                        self.screen_obj.on_action(action, down, stamp)
            return True
        if ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_F1:
                self.design.toggle()
                return True
            if ev.key == pygame.K_F2:
                self.notes.start(self.context())
                return True
            if self.design.open and self.design.key(ev):
                return True
            if ev.key in ARROW_KEYS:
                self.screen_obj.on_action(ARROW_KEYS[ev.key], True, stamp)
            elif hasattr(self.screen_obj, 'key'):
                self.screen_obj.key(ev)
        elif ev.type == pygame.KEYUP and ev.key in ARROW_KEYS and not self.notes.open:
            self.screen_obj.on_action(ARROW_KEYS[ev.key], False, stamp)
        return True

    # ---------------------------------------------------------- loop

    def run(self):
        running = True
        prev_pump = time.perf_counter()
        while running:
            now = time.perf_counter()
            # with VSync the loop sleeps in flip(); events arrived somewhere since the last pump
            stamp = (prev_pump + now) / 2 if self.vsync else now
            prev_pump = now
            for ev in pygame.event.get():
                if not self.handle(ev, stamp):
                    running = False
                    break
            if now - self.last_poll > 0.5:
                self.last_poll = now
                if self.cfg.poll():
                    self.toast('Settings reloaded from file')
                self.maybe_pad_setup()
            self.screen_obj.update()
            self.screen_obj.draw(self.screen)
            self.design.draw(self.screen)
            self.notes.draw(self.screen)
            self.draw_overlay()
            pygame.display.flip()
            if not self.vsync and self.cfg.fps_cap:
                self.clock.tick_busy_loop(self.cfg.fps_cap)
            else:
                self.clock.tick()
        self.leave_screen()
        pygame.quit()

    def draw_overlay(self):
        now = time.perf_counter()
        y = u(12)
        for msg, t in self.toasts:
            if now - t < 2.5:
                gfx.blit_text(self.screen, msg, 18, (gfx.W // 2, y), COLORS['accent'], True, 'midtop')
                y += u(26)
        if self.bench is not None:
            self.bench.append(now)
        if self.cfg.show_fps:
            fps = self.clock.get_fps()
            gfx.blit_text(self.screen, '%d fps' % round(fps), 14, (gfx.W - u(10), u(6)), COLORS['dim'], anchor='topright')


def bench(seconds=6.0, rel='DDR A20/1,2,3,4!'):
    """python ravelab.py --bench : autoplay a chart, then print frame pacing."""
    app = App(windowed='--windowed' in sys.argv)
    app.cfg.values['autoplay'] = True
    while not app.library.ready:
        time.sleep(0.1)
    if not app.library.by_rel:
        print('no songs found in', library.SONGS)
        return
    e = app.library.by_rel.get(rel) or max(app.library.by_rel.values(),
                                            key=lambda x: max((s or {}).get('steps', 0) for s in x['stats']) if x['stats'] else 0)
    app.start_song(e, tuple(max(e['charts'], key=lambda c: c[1])))
    app.screen_obj.planned_start = time.perf_counter() - 30
    app.bench = []
    stop = time.perf_counter() + seconds
    orig = app.screen_obj.update

    def update():
        orig()
        if time.perf_counter() > stop:
            pygame.event.post(pygame.event.Event(pygame.QUIT))
    app.screen_obj.update = update
    app.run()
    ts = app.bench[30:]
    gaps = sorted((b - a) * 1000 for a, b in zip(ts, ts[1:]))
    n = len(gaps)
    print('frames %d  avg %.1f fps  median %.2f ms  p95 %.2f ms  p99 %.2f ms  worst %.2f ms  vsync=%s  size=%s' % (
        n, n / (ts[-1] - ts[0]), gaps[n // 2], gaps[int(n * .95)], gaps[int(n * .99)], gaps[-1], app.vsync, (gfx.W, gfx.H)))


def selftest():
    """python ravelab.py --selftest : start everything, index the songs, report, quit. No window needed."""
    os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
    os.environ.setdefault('SDL_AUDIODRIVER', 'dummy')
    print('Rave Laboratory %s, pygame-ce %s' % (VERSION, pygame.version.ver))
    print(paths.describe())
    import bgvideo
    print('ffmpeg:', bgvideo.ffmpeg_path() or 'not found (video backgrounds, Lab mode and the waveform need it)')
    app = App(windowed=True)
    while not app.library.ready:
        time.sleep(0.1)
    print('songs: %d in %d groups (%s)' % (len(app.library.by_rel), len(app.library.groups), app.library.status))
    print('players: %s' % ', '.join(p.name for p in app.profiles.all()))
    print('pads: %s' % ('; '.join(p.summary() for p in app.pads.pads.values()) or 'none connected'))
    for screen in (app.screen_obj, app.select):
        screen.update()
        screen.draw(app.screen)
    print('ok')
    pygame.quit()


if __name__ == '__main__':
    if '--outfox' in sys.argv:
        chosen = sys.argv[sys.argv.index('--outfox') + 1]
        if not paths.looks_like_outfox(chosen):
            print('That does not look like an OutFox folder (no Songs inside):', chosen)
            sys.exit(2)
        cfg = settings.Settings()
        cfg.set_extra('outfox_dir', os.path.abspath(chosen))
        print('OutFox folder saved:', os.path.abspath(chosen), '(restart to use it)')
        sys.exit(0)
    if '--paths' in sys.argv:
        print(paths.describe())
    elif '--selftest' in sys.argv:
        selftest()
    elif '--bench' in sys.argv:
        bench()
    else:
        try:
            App(windowed='--windowed' in sys.argv).run()
        except Exception:
            import traceback
            os.makedirs(settings.DATA, exist_ok=True)
            with open(os.path.join(settings.DATA, 'crash.log'), 'a', encoding='utf-8') as f:
                f.write('\n==== %s\n' % time.strftime('%Y-%m-%d %H:%M:%S'))
                traceback.print_exc(file=f)
            raise
