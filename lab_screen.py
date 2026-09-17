"""Lab mode: bring in your own songs and music videos and chart them with an AI assistant.

List view    drop a song/video file on the window (or Browse), or open an earlier project.
Editor       chat on the left, note field in the middle, beat markers (measures, beats, waveform) on its right,
             arrow tools and song settings, and a whole-song overview on the far right.

Mouse   click an empty spot = arrow, drag down = freeze, drag an arrow = move it (with everything selected),
        drag a freeze's end = length, right click = delete, Shift+drag = box select, Ctrl+click = add to selection,
        double click = change type (tap, freeze, roll, mine), wheel = scroll (Shift = measure, Ctrl = zoom),
        click/drag the beat markers or overview to jump.
Keys    Up/Down move (Shift selects), PgUp/PgDn measure, Left/Right snap, 1-4 place L D U R (hold + move = freeze),
        T type, M mirror, Shift+M flip left/right, Del delete, Ctrl+Z/Y undo/redo, Ctrl+C/X/V, Ctrl+A, Ctrl+S save,
        Space play/stop, K clap, P playtest from here (Shift+P from the start), Tab difficulty, -/= zoom,
        Enter chat, Esc back.
Files   Songs/Rave Lab/<song>/chart.ssc (plays in the song list and in OutFox) and lab.json (analysis, chat).
"""
import os
import threading
import time

import numpy as np
import pygame

import bgvideo
import gfx
import labai
import labaudio
import labchart
import simfile
import wavestrip
from gfx import COLORS, u
from labchart import DIFFS, KINDS, MEASURE, TICKS, LNote

PINK = (255, 140, 220)
MINT = (120, 255, 200)
FIELD_X, LANE = 452, 58              # design units (1280x720)
FIELD_TOP, FIELD_BOTTOM = 64, 712
RULER_X, RULER_W = FIELD_X + LANE * 4 + 8, 128
INSPECT_X = RULER_X + RULER_W + 14
MINIMAP_X, MINIMAP_W = 1206, 62
CHAT_W = 420
QUICK = [('Make a chart', 'Make a starting chart for the open difficulty that fits this song.'),
         ('Easier', 'Make this chart a bit easier.'), ('Harder', 'Make this chart a bit harder.'),
         ('More freezes', 'Add freeze arrows where the music holds long notes.')]


def _wrap(text, size, width, bold=False):
    out = []
    for para in str(text).split('\n'):
        words, cur = para.split(), ''
        for w in words:
            trial = (cur + ' ' + w).strip()
            if gfx.text(trial, size, None, bold).get_width() > width and cur:
                out.append(cur)
                cur = w
            else:
                cur = trial
        out.append(cur)
    return out


def _browse(kind):
    """The operating system's own file picker (see filedialog.py); runs on a helper thread."""
    import filedialog
    exts = labaudio.AUDIO_EXTS + labaudio.VIDEO_EXTS if kind == 'media' else labaudio.VIDEO_EXTS
    return filedialog.ask_open_file('Choose a song or music video' if kind == 'media' else 'Choose a video',
                                    ['*' + e for e in exts], 'Songs and videos' if kind == 'media' else 'Videos')


class Job:
    """Background work (import, analysis) with a status line."""

    def __init__(self, fn, *args):
        self.status, self.error, self.result, self.done = 'Starting', None, None, False
        threading.Thread(target=self._run, args=(fn, args), daemon=True).start()

    def _run(self, fn, args):
        try:
            self.result = fn(self, *args)
        except Exception as e:
            self.error = str(e) or e.__class__.__name__
        self.done = True


def _import_job(job, path):
    folder, info = labaudio.import_media(path, lambda s: setattr(job, 'status', s))
    p = labchart.Project(folder)
    for k, v in info.items():
        if hasattr(p, k):
            setattr(p, k, v)
    _analyse_into(job, p, None, None)
    p.save()
    return p


def _analyse_into(job, p, bpm, offset):
    an = labaudio.analyse(p.music_path(), lambda s: setattr(job, 'status', s), bpm, offset)
    p.analysis = an
    p.bpm, p.offset = an['bpm'], an['offset']
    if bpm is None:
        p.sample_start = an['sample_start']
    return p


def _make_clap():
    rate, _, ch = pygame.mixer.get_init()
    n = int(rate * 0.04)
    rng = np.random.default_rng(3)
    env = np.exp(-np.linspace(0, 10, n))
    x = rng.standard_normal(n) * env * 0.45
    x[:int(rate * 0.004)] += 0.6 * np.sin(np.linspace(0, 40, int(rate * 0.004)))
    x = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    arr = np.ascontiguousarray(np.repeat(x[:, None], ch, axis=1)) if ch > 1 else x
    return pygame.sndarray.make_sound(arr)


class LabScreen:
    name = 'lab'
    raw_keys = True

    def __init__(self, app):
        self.app = app
        self.mode = 'list'
        self.projects = []
        self.list_i = 0
        self.job = None
        self.job_kind = ''
        self.browse_thread = None
        self.browse_result = None
        self.buttons = []
        self.hover = (0, 0)
        self.project = None
        pygame.key.set_repeat(320, 45)
        self.refresh_list()

    # ================================================================== list view

    def refresh_list(self):
        self.projects = []
        if os.path.isdir(labaudio.LAB_DIR):
            for name in os.listdir(labaudio.LAB_DIR):
                folder = os.path.join(labaudio.LAB_DIR, name)
                lab = os.path.join(folder, 'lab.json')
                if os.path.isfile(lab):
                    self.projects.append((os.path.getmtime(lab), folder))
        self.projects = [f for _, f in sorted(self.projects, reverse=True)]
        self.summaries = {}
        for f in self.projects[:40]:
            try:
                p = labchart.Project.load(f)
                self.summaries[f] = (p.title, p.artist, ', '.join('%s %d' % (simfile.DIFF_NAMES[c.diff], c.meter) for c in p.charts),
                                     bool(p.video), p.bpm)
            except Exception:
                self.summaries[f] = (os.path.basename(f), '', '(could not read)', False, 0)
        self.list_i = min(self.list_i, max(0, len(self.projects)))

    def start_import(self, path):
        if self.job and not self.job.done:
            self.app.toast('Still working on the last file')
            return
        if not labaudio.kind_of(path):
            self.app.toast('That is not a song or video file')
            return
        self.job, self.job_kind = Job(_import_job, path), 'import'

    def browse(self, kind='media'):
        if self.browse_thread and self.browse_thread.is_alive():
            return
        self.browse_result = None

        def run():
            self.browse_result = (kind, _browse(kind))
        self.browse_thread = threading.Thread(target=run, daemon=True)
        self.browse_thread.start()
        self.app.toast('A file picker opened (it may be behind the game window: Alt+Tab)')

    def open_project(self, folder_or_project):
        p = folder_or_project if isinstance(folder_or_project, labchart.Project) else labchart.Project.load(folder_or_project)
        if not p.music or not os.path.isfile(p.music_path()):
            self.app.toast('The song file for that project is missing')
            return
        self.project = p
        self.mode = 'edit'
        self.diff = p.charts[0].diff if p.charts else 'Easy'
        self.cursor = 0
        self.view = -TICKS * 2.0
        self.zoom = 80.0                 # design px per beat
        self.snap_i = 1                  # 8ths
        self.sel = set()
        self.drag = None
        self.last_click = (0, None)
        self.undo_stack, self.redo_stack = [], []
        self.clip = []
        self.dirty = False
        self.saved_at = time.perf_counter()
        self.playing = False
        self.play_origin = 0.0
        self.play_from_tick = 0
        self.play_started_music = False
        self.clap_next = 0
        self.clap = None
        self.video = None
        self.music_loaded = False
        self.key_down = {}               # col -> tick where 1-4 was pressed
        self.chat_focus = False
        self.chat_text = ''
        self.chat_scroll = 0
        self.chat_req = None
        self.chat_retry = 0
        self.wrap_cache = {}
        self.wave = None
        self.analysis_job = None
        threading.Thread(target=self._load_wave, daemon=True).start()
        if not p.charts:
            self.send_chat('Make a starting chart for this song. Pick a friendly level for the open difficulty.', shown=True)

    def _load_wave(self):
        try:
            self.wave = wavestrip.analyse(self.project.music_path())
        except Exception:
            self.wave = None

    # ================================================================== shared input plumbing

    def on_action(self, action, down, stamp):
        """Pad buttons (and nothing else: the keyboard comes through key())."""
        if not down:
            return
        if self.mode == 'list':
            n = len(self.projects) + 1
            if action in ('up', 'left'):
                self.list_i = (self.list_i - 1) % n
            elif action in ('down', 'right'):
                self.list_i = (self.list_i + 1) % n
            elif action == 'start':
                self._open_list_item()
            elif action == 'back':
                self.leave()
        elif action == 'back':
            self.close_editor()
        elif action in ('up', 'down'):
            self.move_cursor(self.step() * (-1 if action == 'up' else 1))

    def _open_list_item(self):
        if self.list_i == 0:
            self.browse()
        elif self.list_i - 1 < len(self.projects):
            self.open_project(self.projects[self.list_i - 1])

    def wants_text(self):
        return self.mode == 'edit' and self.chat_focus

    def text_event(self, ev):
        if ev.type == pygame.TEXTINPUT:
            self.chat_text = (self.chat_text + ev.text)[:600]
            return
        k = ev.key
        if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
            if self.chat_text.strip():
                self.send_chat(self.chat_text.strip())
                self.chat_text = ''
        elif k == pygame.K_ESCAPE:
            self.set_chat_focus(False)
        elif k == pygame.K_BACKSPACE:
            if ev.mod & pygame.KMOD_CTRL:
                self.chat_text = self.chat_text.rstrip().rsplit(' ', 1)[0] if ' ' in self.chat_text.strip() else ''
            else:
                self.chat_text = self.chat_text[:-1]
        elif k == pygame.K_v and ev.mod & pygame.KMOD_CTRL:
            try:
                clip = pygame.scrap.get_text() if hasattr(pygame.scrap, 'get_text') else ''
                self.chat_text = (self.chat_text + (clip or '').replace('\r', ' ').replace('\n', ' '))[:600]
            except Exception:
                pass
        elif k in (pygame.K_UP, pygame.K_PAGEUP):
            self.chat_scroll += u(60)
        elif k in (pygame.K_DOWN, pygame.K_PAGEDOWN):
            self.chat_scroll = max(0, self.chat_scroll - u(60))

    def set_chat_focus(self, on):
        self.chat_focus = on
        if on:
            pygame.key.start_text_input()
        else:
            pygame.key.stop_text_input()

    def key(self, ev):
        if ev.type == pygame.KEYUP:
            if self.mode == 'edit':
                self._key_up(ev)
            return
        if self.mode == 'list':
            k = ev.key
            n = len(self.projects) + 1
            if k in (pygame.K_UP, pygame.K_LEFT):
                self.list_i = (self.list_i - 1) % n
            elif k in (pygame.K_DOWN, pygame.K_RIGHT):
                self.list_i = (self.list_i + 1) % n
            elif k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._open_list_item()
            elif k == pygame.K_o and ev.mod & pygame.KMOD_CTRL:
                self.browse()
            elif k in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.leave()
            return
        self._key_edit(ev)

    def mouse(self, ev):
        if ev.type == pygame.DROPFILE:
            path = ev.file
            if self.mode == 'edit' and labaudio.kind_of(path) == 'video':
                self.add_video(path)
            else:
                if self.mode == 'edit':
                    self.close_editor()
                self.start_import(path)
            return
        if ev.type == pygame.MOUSEMOTION:
            self.hover = ev.pos
            if self.mode == 'edit':
                self._drag_motion(ev.pos)
            return
        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
            for rect, fn in reversed(self.buttons):
                if rect.collidepoint(ev.pos):
                    fn()
                    return
            if self.mode == 'edit' and self.chat_focus and not self._chat_rect().collidepoint(ev.pos):
                self.set_chat_focus(False)
        if self.mode == 'edit':
            self._mouse_edit(ev)

    # ================================================================== leaving / resuming

    def leave(self):
        pygame.key.set_repeat(0)
        pygame.key.stop_text_input()
        self.app.library.rescan()
        self.app.to_profiles()

    def close(self):
        """Called by the app when this screen is replaced or the game closes."""
        self._stop(keep_cursor=True)
        if self.mode == 'edit' and self.dirty:
            self.save()

    def close_editor(self):
        self._stop(keep_cursor=True)
        if self.dirty:
            self.save()
        self.set_chat_focus(False)
        self.mode = 'list'
        self.project = None
        self.app.library.rescan()
        self.refresh_list()

    def resume(self):
        pygame.key.set_repeat(320, 45)
        self.music_loaded = False

    # ================================================================== editor model helpers

    def chart(self):
        return self.project.chart(self.diff)

    def ensure_chart(self):
        return self.project.get_or_add(self.diff)

    def step(self):
        return MEASURE // labchart.SNAPS[self.snap_i]

    def snap(self, tick):
        s = self.step()
        return int(round(tick / float(s))) * s

    def checkpoint(self):
        p = self.project
        self.undo_stack.append((p.bpm, p.offset, self.diff, [(c.diff, c.meter, c.desc, [n.astuple() for n in c.notes]) for c in p.charts]))
        del self.undo_stack[:-200]
        self.redo_stack = []
        self.dirty = True

    def _restore(self, snap):
        p = self.project
        p.bpm, p.offset, self.diff, charts = snap
        p.charts = [labchart.LChart(d, m, desc, [LNote(*t) for t in notes]) for d, m, desc, notes in charts]
        self.sel = set()
        self.dirty = True

    def _snapshot_now(self):
        p = self.project
        return (p.bpm, p.offset, self.diff, [(c.diff, c.meter, c.desc, [n.astuple() for n in c.notes]) for c in p.charts])

    def undo(self):
        if self.undo_stack:
            self.redo_stack.append(self._snapshot_now())
            self._restore(self.undo_stack.pop())
            self.app.toast('Undo')

    def redo(self):
        if self.redo_stack:
            self.undo_stack.append(self._snapshot_now())
            self._restore(self.redo_stack.pop())
            self.app.toast('Redo')

    def save(self):
        try:
            self.project.save()
            self.dirty = False
            self.saved_at = time.perf_counter()
        except OSError as e:
            self.app.toast('Could not save: %s' % e)

    def total_ticks(self):
        an = self.project.analysis or {}
        c = self.chart()
        return max(an.get('measures', 0), c.last_measure() if c else 0, 4) * MEASURE

    def move_cursor(self, d, select=False):
        before = self.cursor
        self.cursor = max(0, min(self.total_ticks(), self.cursor + d))
        if select:
            a, b = sorted((before, self.cursor))
            c = self.chart()
            if c:
                for n in c.notes:
                    if a <= n.tick <= b:
                        self.sel.add(n)
        self.keep_visible()
        if self.playing:
            self._start_play(self.cursor)

    def keep_visible(self):
        ppb = self.zoom
        rows = (FIELD_BOTTOM - FIELD_TOP) / ppb * TICKS
        if self.cursor < self.view + rows * 0.12:
            self.view = self.cursor - rows * 0.12
        elif self.cursor > self.view + rows * 0.8:
            self.view = self.cursor - rows * 0.8

    # screen <-> tick (real pixels)
    def ppb(self):
        return self.zoom * gfx.U

    def y_of(self, tick):
        return u(FIELD_TOP) + (tick - self.view) / TICKS * self.ppb()

    def tick_at(self, y):
        return self.view + (y - u(FIELD_TOP)) / self.ppb() * TICKS

    def col_at(self, x):
        c = (x - u(FIELD_X)) // u(LANE)
        return int(c) if 0 <= c < 4 else None

    def sel_measures(self):
        if not self.sel:
            return None
        ticks = [n.tick for n in self.sel]
        return (min(ticks) // MEASURE + 1, max(ticks) // MEASURE + 1)

    # ================================================================== keyboard (editor)

    def _key_edit(self, ev):
        k, mod = ev.key, ev.mod
        ctrl, shift = mod & pygame.KMOD_CTRL, mod & pygame.KMOD_SHIFT
        if ctrl:
            if k == pygame.K_z:
                self.redo() if shift else self.undo()
            elif k == pygame.K_y:
                self.redo()
            elif k == pygame.K_s:
                self.save()
                self.app.toast('Saved to Songs/Rave Lab')
            elif k == pygame.K_a and self.chart():
                self.sel = set(self.chart().notes)
            elif k in (pygame.K_c, pygame.K_x):
                self.copy_sel(cut=k == pygame.K_x)
            elif k == pygame.K_v:
                self.paste()
            return
        col = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3,
               pygame.K_KP1: 0, pygame.K_KP2: 1, pygame.K_KP3: 2, pygame.K_KP4: 3}.get(k)
        if col is not None:
            if col not in self.key_down:
                self.key_down[col] = self.cursor
            return
        if k == pygame.K_UP:
            self.move_cursor(-self.step(), bool(shift))
        elif k == pygame.K_DOWN:
            self.move_cursor(self.step(), bool(shift))
        elif k == pygame.K_PAGEUP:
            self.move_cursor(-MEASURE, bool(shift))
        elif k == pygame.K_PAGEDOWN:
            self.move_cursor(MEASURE, bool(shift))
        elif k == pygame.K_HOME:
            self.move_cursor(-self.cursor)
        elif k == pygame.K_END:
            self.move_cursor(self.total_ticks() - self.cursor)
        elif k == pygame.K_LEFT:
            self.snap_i = max(0, self.snap_i - 1)
        elif k == pygame.K_RIGHT:
            self.snap_i = min(len(labchart.SNAPS) - 1, self.snap_i + 1)
        elif k in (pygame.K_DELETE, pygame.K_BACKSPACE):
            self.delete_sel()
        elif k == pygame.K_t:
            self.cycle_type()
        elif k == pygame.K_m:
            self.mirror_sel({0: 3, 3: 0} if shift else {0: 3, 3: 0, 1: 2, 2: 1})
        elif k == pygame.K_SPACE:
            self.toggle_play()
        elif k == pygame.K_k:
            self.app.cfg.set('lab_clap', not self.app.cfg.lab_clap)
            self.app.toast('Clap %s' % ('on' if self.app.cfg.lab_clap else 'off'))
        elif k == pygame.K_p:
            self.playtest(from_start=bool(shift))
        elif k == pygame.K_TAB:
            i = DIFFS.index(self.diff) if self.diff in DIFFS else 0
            self.set_diff(DIFFS[(i + (-1 if shift else 1)) % len(DIFFS)])
        elif k in (pygame.K_MINUS, pygame.K_KP_MINUS):
            self.set_zoom(self.zoom / 1.25)
        elif k in (pygame.K_EQUALS, pygame.K_PLUS, pygame.K_KP_PLUS):
            self.set_zoom(self.zoom * 1.25)
        elif k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SLASH):
            self.set_chat_focus(True)
        elif k == pygame.K_ESCAPE:
            if self.playing:
                self._stop()
            elif self.sel:
                self.sel = set()
            else:
                self.close_editor()

    def _key_up(self, ev):
        col = {pygame.K_1: 0, pygame.K_2: 1, pygame.K_3: 2, pygame.K_4: 3,
               pygame.K_KP1: 0, pygame.K_KP2: 1, pygame.K_KP3: 2, pygame.K_KP4: 3}.get(ev.key)
        if col is None or col not in self.key_down:
            return
        start = self.key_down.pop(col)
        a, b = sorted((start, self.cursor))
        self.checkpoint()
        c = self.ensure_chart()
        if b > a:
            n = c.place(LNote(a, col, 'hold', b - a))
            self.sel = {n}
        else:
            old = c.at(a, col)
            if old is not None and old.tick == a:
                c.notes.remove(old)
                self.sel.discard(old)
            else:
                self.sel = {c.place(LNote(a, col))}

    def set_zoom(self, z):
        centre = self.tick_at(u((FIELD_TOP + FIELD_BOTTOM) / 2))
        self.zoom = max(20.0, min(400.0, z))
        self.view = centre - (FIELD_BOTTOM - FIELD_TOP) / 2.0 / self.zoom * TICKS

    def set_diff(self, d):
        self.diff = d
        self.sel = set()
        c = self.chart()
        self.app.toast('%s%s' % (simfile.DIFF_NAMES[d], ' %d' % c.meter if c else ' (empty: add arrows or ask the assistant)'))

    # ================================================================== edit operations

    def delete_sel(self):
        c = self.chart()
        if c and self.sel:
            self.checkpoint()
            c.notes = [n for n in c.notes if n not in self.sel]
            self.sel = set()

    def cycle_type(self, notes=None):
        notes = list(notes or self.sel)
        if not notes:
            return
        self.checkpoint()
        kind = KINDS[(KINDS.index(notes[0].kind) + 1) % len(KINDS)]
        c = self.chart()
        for n in notes:
            self.set_kind(c, n, kind)

    def set_kind(self, c, n, kind):
        n.kind = kind
        if kind in ('hold', 'roll'):
            if n.length <= 0:
                n.length = max(self.step(), TICKS)
            c.notes.remove(n)
            c.place(n)
        else:
            n.length = 0

    def set_sel_kind(self, kind):
        if not self.sel:
            return
        self.checkpoint()
        c = self.chart()
        for n in list(self.sel):
            self.set_kind(c, n, kind)

    def mirror_sel(self, swap):
        c = self.chart()
        if not c or not self.sel:
            return
        self.checkpoint()
        for n in self.sel:
            n.col = swap.get(n.col, n.col)
        self._resolve(self.sel)

    def nudge_length(self, d):
        holds = [n for n in self.sel if n.kind in ('hold', 'roll')]
        if not holds:
            return
        self.checkpoint()
        for n in holds:
            n.length = max(self.step(), n.length + d * self.step())
        self._resolve(set(holds))

    def _resolve(self, keep):
        """After moving notes, anything they now overlap in their columns goes."""
        c = self.chart()
        others = [n for n in c.notes if n not in keep]
        survivors = [o for o in others if not any(k.col == o.col and k.tick <= o.end and k.end >= o.tick for k in keep)]
        c.notes = survivors + list(keep)
        c.sort()

    def copy_sel(self, cut=False):
        if not self.sel:
            return
        base = min(n.tick for n in self.sel) // self.step() * self.step()
        self.clip = [(n.tick - base, n.col, n.kind, n.length) for n in self.sel]
        if cut:
            self.delete_sel()
        self.app.toast('%s %d arrows' % ('Cut' if cut else 'Copied', len(self.clip)))

    def paste(self):
        if not self.clip:
            return
        self.checkpoint()
        c = self.ensure_chart()
        new = {LNote(self.cursor + dt, col, kind, length) for dt, col, kind, length in self.clip}
        c.notes += list(new)
        self._resolve(new)
        self.sel = new

    def shift_downbeat(self, d):
        """Move where measures start by one beat, keeping every arrow at the same moment in the music."""
        self.checkpoint()
        p = self.project
        p.offset -= d * 60.0 / p.bpm
        for c in p.charts:
            for n in c.notes:
                n.tick -= d * TICKS
            c.notes = [n for n in c.notes if n.tick >= 0]
        self.reanalyse()

    def change_bpm(self, factor=None, delta=None):
        """Change tempo, keeping the first beat where it is (arrows stay on their beats)."""
        self.checkpoint()
        p = self.project
        p.bpm = round(max(20.0, min(400.0, p.bpm * factor if factor else p.bpm + delta)), 3)
        self.reanalyse()

    def change_offset(self, ms):
        self.checkpoint()
        self.project.offset = round(self.project.offset + ms / 1000.0, 4)
        self.reanalyse(delay=True)

    def reanalyse(self, delay=False):
        """The rhythm grid the generator uses depends on BPM and offset, so read it again after changes."""
        self.analysis_due = time.perf_counter() + (1.5 if delay else 0.4)

    def add_video(self, path=None):
        if path is None:
            self.browse('video')
            return
        p = self.project

        def work(job):
            p.video = labaudio.add_video(p.folder, path, lambda s: setattr(job, 'status', s))
            if os.path.isfile(os.path.join(p.folder, 'bg.jpg')):
                p.background = 'bg.jpg'
            p.save()
        self.job, self.job_kind = Job(work), 'video'

    def generate_builtin(self):
        self.checkpoint()
        c = self.ensure_chart()
        try:
            msg = labchart.generate(self.project, c)
            self.project.chat.append({'role': 'note', 'text': 'Built-in generator: ' + msg})
            self.chat_scroll = 0
        except ValueError as e:
            self.app.toast(str(e))

    def set_meter(self, d):
        c = self.ensure_chart()
        self.checkpoint()
        c.meter = max(1, min(20, c.meter + d))

    def clear_chart(self):
        c = self.chart()
        if c and c.notes:
            self.checkpoint()
            c.notes = []
            self.sel = set()
            self.app.toast('Cleared %s (Ctrl+Z brings it back)' % simfile.DIFF_NAMES[self.diff])

    def playtest(self, from_start=False):
        c = self.chart()
        if not c or not c.notes:
            self.app.toast('Add some arrows first')
            return
        self.save()
        start = 0.0 if from_start else max(0.0, self.project.time_of_tick(self.cursor // MEASURE * MEASURE))
        self._stop(keep_cursor=True)
        self.app.playtest(self, self.project.folder, self.project.rel, self.diff, start)

    # ================================================================== chat

    def send_chat(self, text, shown=True, auto=False):
        if self.chat_req is not None and not self.chat_req.done:
            self.app.toast('The assistant is still answering')
            return
        p = self.project
        entry = {'role': 'user', 'text': text, 'time': time.strftime('%Y-%m-%d %H:%M:%S')}
        if auto:
            entry['auto'] = True
        p.chat.append(entry)
        if not auto:
            self.chat_retry = 0
        ctx = labai.context_block(p, self.diff, self.cursor // MEASURE + 1, self.sel_measures())
        self.chat_req = labai.ChatRequest(self.app.cfg.lab_ai, self.app.cfg.lab_claude_model, p.chat[:-1], ctx, text,
                                          self.app.cfg.claude_code_model)
        self.chat_scroll = 0

    def _finish_chat(self):
        req, self.chat_req = self.chat_req, None
        p = self.project
        if req.error:
            p.chat.append({'role': 'error', 'text': req.error, 'by': req.label})
            return
        log, extra = [], ''
        if req.actions:
            self.checkpoint()
            log, self.diff, extra = labchart.apply_actions(p, self.diff, req.actions)
            self.sel = set()
        p.chat.append({'role': 'assistant', 'text': req.say or '(no reply text)', 'log': log, 'by': req.label,
                       'time': time.strftime('%Y-%m-%d %H:%M:%S')})
        self.chat_scroll = 0
        if req.actions:
            self.save()
        failed = [x for x in log if x.startswith(('could not', 'unknown action', 'skipped'))]
        if (failed or extra) and self.chat_retry < 1 and req.label != 'built-in generator':
            self.chat_retry += 1
            msg = []
            if failed:
                msg.append('Some of your actions failed: %s. Fix them (remember the notation) and try again.' % '; '.join(failed))
            if extra:
                msg.append('Here are the measures you asked to see:\n' + extra + '\nNow finish what I asked.')
            self.send_chat('\n'.join(msg), auto=True)

    # ================================================================== mouse (editor)

    def _chat_rect(self):
        return pygame.Rect(u(12), u(64), u(CHAT_W), gfx.H - u(76))

    def _field_rect(self):
        return pygame.Rect(u(FIELD_X), u(FIELD_TOP), u(LANE * 4), u(FIELD_BOTTOM - FIELD_TOP))

    def _ruler_rect(self):
        return pygame.Rect(u(RULER_X), u(FIELD_TOP), u(RULER_W), u(FIELD_BOTTOM - FIELD_TOP))

    def _minimap_rect(self):
        return pygame.Rect(u(MINIMAP_X), u(FIELD_TOP), u(MINIMAP_W), u(FIELD_BOTTOM - FIELD_TOP))

    def note_at(self, pos):
        c = self.chart()
        col = self.col_at(pos[0])
        if not c or col is None:
            return None, None
        half = u(LANE) * 0.45
        best = None
        for n in c.notes:
            if n.col != col:
                continue
            y = self.y_of(n.tick)
            if abs(pos[1] - y) <= half:
                return n, 'head'
            if n.kind in ('hold', 'roll'):
                ye = self.y_of(n.end)
                if abs(pos[1] - ye) <= u(12):
                    best = (n, 'tail')
                elif y < pos[1] < ye and best is None:
                    best = (n, 'body')
        return best if best else (None, None)

    def _mouse_edit(self, ev):
        pos = getattr(ev, 'pos', self.hover)
        if ev.type == pygame.MOUSEWHEEL:
            mods = pygame.key.get_mods()
            x, _ = self.hover
            if self._chat_rect().collidepoint(self.hover):
                self.chat_scroll = max(0, self.chat_scroll + ev.y * u(40))
            elif mods & pygame.KMOD_CTRL:
                self.set_zoom(self.zoom * (1.15 ** ev.y))
            elif self._field_rect().collidepoint(self.hover) or self._ruler_rect().collidepoint(self.hover) \
                    or self._minimap_rect().collidepoint(self.hover):
                amount = MEASURE if mods & pygame.KMOD_SHIFT else TICKS
                self.view -= ev.y * amount
            return
        if ev.type == pygame.MOUSEBUTTONUP and ev.button in (1, 3):
            self._drag_end()
            return
        if ev.type != pygame.MOUSEBUTTONDOWN:
            return
        if self._chat_rect().collidepoint(pos) and ev.button == 1:
            box = self._input_rect()
            if box.collidepoint(pos):
                self.set_chat_focus(True)
            return
        if self._ruler_rect().collidepoint(pos) and ev.button == 1:
            self.drag = {'mode': 'ruler'}
            self._drag_motion(pos)
            return
        if self._minimap_rect().collidepoint(pos) and ev.button == 1:
            self.drag = {'mode': 'minimap'}
            self._drag_motion(pos)
            return
        if not self._field_rect().collidepoint(pos):
            return
        mods = pygame.key.get_mods()
        col = self.col_at(pos[0])
        tick = max(0, self.snap(self.tick_at(pos[1])))
        note, part = self.note_at(pos)
        if ev.button == 3:
            if note is not None:
                self.checkpoint()
                self.chart().notes.remove(note)
                self.sel.discard(note)
            else:
                self.sel = set()
            return
        if ev.button != 1:
            return
        now = time.perf_counter()
        double = note is not None and self.last_click[1] is note and now - self.last_click[0] < 0.35
        self.last_click = (now, note)
        if double:
            self.drag = None
            self.cycle_type([note])
            return
        if mods & pygame.KMOD_SHIFT and note is None:
            self.drag = {'mode': 'box', 'a': pos, 'b': pos}
            return
        if note is not None:
            if mods & pygame.KMOD_CTRL:
                self.sel.symmetric_difference_update({note})
                return
            if note not in self.sel:
                self.sel = {note}
            if part == 'tail':
                self.drag = {'mode': 'length', 'note': note, 'orig': note.length, 'saved': False}
            else:
                self.drag = {'mode': 'move', 'grab': (tick, col), 'orig': [(n, n.tick, n.col) for n in self.sel], 'saved': False}
            self.cursor = note.tick
            return
        # empty spot: new arrow, dragging turns it into a freeze
        self.checkpoint()
        c = self.ensure_chart()
        n = c.place(LNote(tick, col))
        self.sel = {n}
        self.cursor = tick
        self.drag = {'mode': 'draw', 'note': n, 'start': tick}

    def _drag_motion(self, pos):
        d = self.drag
        if not d:
            return
        if d['mode'] == 'ruler':
            self.cursor = max(0, self.snap(self.tick_at(pos[1])))
            if self.playing:
                self._start_play(self.cursor)
        elif d['mode'] == 'minimap':
            r = self._minimap_rect()
            frac = min(1.0, max(0.0, (pos[1] - r.y) / float(r.h)))
            rows = (FIELD_BOTTOM - FIELD_TOP) / self.zoom * TICKS
            self.view = frac * self.total_ticks() - rows / 2
        elif d['mode'] == 'box':
            d['b'] = pos
        elif d['mode'] == 'draw':
            n = d['note']
            end = max(d['start'], self.snap(self.tick_at(pos[1])))
            if end - d['start'] >= self.step():
                n.kind = 'roll' if pygame.key.get_mods() & pygame.KMOD_ALT else 'hold'
                n.length = end - d['start']
            else:
                n.kind, n.length = 'tap', 0
            self._resolve({n})
        elif d['mode'] == 'length':
            n = d['note']
            end = self.snap(self.tick_at(pos[1]))
            new = max(self.step(), end - n.tick)
            if new != n.length:
                if not d['saved']:
                    self.checkpoint()
                    d['saved'] = True
                n.length = new
                self._resolve({n})
        elif d['mode'] == 'move':
            col = self.col_at(pos[0])
            tick = self.snap(self.tick_at(pos[1]))
            dt = tick - d['grab'][0]
            dc = (col - d['grab'][1]) if col is not None else 0
            if (dt or dc) and not d['saved']:
                self.checkpoint()
                d['saved'] = True
            lo = min(t for _, t, _ in d['orig'])
            dt = max(dt, -lo)
            for n, t0, c0 in d['orig']:
                n.tick = t0 + dt
                n.col = max(0, min(3, c0 + dc))

    def _drag_end(self):
        d, self.drag = self.drag, None
        if not d:
            return
        if d['mode'] == 'move' and d['saved']:
            self._resolve({n for n, _, _ in d['orig']})
        elif d['mode'] == 'box':
            c = self.chart()
            if not c:
                return
            (x0, y0), (x1, y1) = d['a'], d['b']
            t0, t1 = sorted((self.tick_at(y0), self.tick_at(y1)))
            cols = {cc for cc in range(4) if min(x0, x1) - u(LANE) < u(FIELD_X) + cc * u(LANE) < max(x0, x1)}
            picked = {n for n in c.notes if n.col in cols and t0 - 2 <= n.tick <= t1 + 2}
            if pygame.key.get_mods() & pygame.KMOD_CTRL:
                self.sel |= picked
            else:
                self.sel = picked

    # ================================================================== playback

    def toggle_play(self):
        if self.playing:
            self._stop()
        else:
            self._start_play(self.cursor)

    def _start_play(self, tick):
        p = self.project
        try:
            if not self.music_loaded:
                pygame.mixer.music.load(p.music_path())
                self.music_loaded = True
        except pygame.error as e:
            self.app.toast('Could not play the song: %s' % e)
            return
        if not self.playing:
            self.play_from_tick = tick
        t = p.time_of_tick(tick)
        self.play_origin = time.perf_counter() - t
        self.play_started_music = False
        pygame.mixer.music.stop()
        pygame.mixer.music.set_volume(self.app.cfg.game_volume / 100.0)
        if t >= 0:
            pygame.mixer.music.play(start=t)
            self.play_started_music = True
        self.playing = True
        if self.clap is None:
            try:
                self.clap = _make_clap()
            except Exception:
                self.clap = False
        c = self.chart()
        self.clap_ticks = sorted({n.tick for n in c.notes if n.kind != 'mine'}) if c else []
        self.clap_next = next((i for i, x in enumerate(self.clap_ticks) if x >= tick), len(self.clap_ticks))
        if self.video:
            self.video.stop()
            self.video = None
        if p.video and bgvideo.ffmpeg_path():
            self.video = bgvideo.VideoPlayer(os.path.join(p.folder, p.video), 0.0, (u(752), u(423)), self.play_time)

    def play_time(self):
        return time.perf_counter() - self.play_origin

    def _stop(self, keep_cursor=False):
        if not getattr(self, 'playing', False):
            return
        self.playing = False
        pygame.mixer.music.stop()
        if self.video:
            self.video.stop()
            self.video = None
        if not keep_cursor:
            self.cursor = self.snap(self.play_from_tick)
            self.keep_visible()

    # ================================================================== update

    def update(self):
        if self.browse_result:
            kind, path = self.browse_result
            self.browse_result = None
            if path:
                if kind == 'video' and self.mode == 'edit':
                    self.add_video(path)
                else:
                    self.start_import(path)
        if self.job and self.job.done:
            job, self.job = self.job, None
            if job.error:
                self.app.toast('%s failed: %s' % ('Import' if self.job_kind == 'import' else 'That', job.error))
            elif self.job_kind == 'import':
                self.refresh_list()
                self.open_project(job.result)
            elif self.job_kind == 'video':
                self.app.toast('Video added: it plays behind the arrows in the song and in this preview')
            elif self.job_kind == 'analyse':
                self.app.toast('Rhythm re-read at %.2f BPM' % self.project.bpm)
        if self.mode != 'edit':
            return
        p = self.project
        due = getattr(self, 'analysis_due', None)
        if due and time.perf_counter() >= due and not (self.job and not self.job.done):
            self.analysis_due = None
            bpm, off = p.bpm, p.offset
            self.job, self.job_kind = Job(lambda job: _analyse_into(job, p, bpm, off)), 'analyse'
        if self.chat_req is not None and self.chat_req.done:
            self._finish_chat()
        if self.playing:
            t = self.play_time()
            if not self.play_started_music and t >= 0:
                pygame.mixer.music.play(start=t)
                self.play_started_music = True
            tick = p.tick_of_time(t)
            if self.play_started_music and not pygame.mixer.music.get_busy() and t > 1:
                self._stop(keep_cursor=True)
            self.cursor = int(tick)
            rows = (FIELD_BOTTOM - FIELD_TOP) / self.zoom * TICKS
            self.view = tick - rows * 0.3
            if self.app.cfg.lab_clap and self.clap:
                fired = False
                while self.clap_next < len(self.clap_ticks) and self.clap_ticks[self.clap_next] <= tick:
                    if tick - self.clap_ticks[self.clap_next] < TICKS // 4 and not fired:
                        self.clap.play()
                        fired = True
                    self.clap_next += 1
        if self.dirty and time.perf_counter() - self.saved_at > 20 and not self.drag:
            self.save()

    # ================================================================== drawing

    def button(self, surf, rect, label, fn, active=False, size=15, color=None, enabled=True):
        hover = rect.collidepoint(self.hover) and enabled
        base = color or COLORS['accent']
        bg = base if active else COLORS['panel2'] if hover else COLORS['panel']
        pygame.draw.rect(surf, bg, rect, border_radius=u(6))
        pygame.draw.rect(surf, base if (hover or active) else COLORS['line'], rect, max(1, u(2)), border_radius=u(6))
        fg = (12, 14, 26) if active else COLORS['text'] if enabled else COLORS['dim']
        gfx.blit_text(surf, label, size, rect.center, fg, True, 'center', max_w=rect.w - u(8))
        if enabled:
            self.buttons.append((rect, fn))

    def draw(self, surf):
        self.buttons = []
        surf.fill(COLORS['bg'])
        if self.mode == 'list':
            self.draw_list(surf)
        else:
            self.draw_editor(surf)
        if self.job and not self.job.done:
            box = pygame.Rect(gfx.W // 2 - u(260), gfx.H // 2 - u(50), u(520), u(100))
            surf.blit(self.app.shade(150), (0, 0))
            pygame.draw.rect(surf, (12, 16, 34), box, border_radius=u(10))
            pygame.draw.rect(surf, MINT, box, max(1, u(3)), border_radius=u(10))
            dots = '.' * (1 + int(time.perf_counter() * 2) % 3)
            gfx.blit_text(surf, self.job.status + dots, 22, (box.centerx, box.y + u(30)), COLORS['text'], True, 'center', max_w=box.w - u(30))
            gfx.blit_text(surf, 'This takes a few seconds per song', 14, (box.centerx, box.y + u(68)), COLORS['dim'], False, 'center')

    # ---------------------------------------------------------- list

    def draw_list(self, surf):
        gfx.blit_text(surf, 'RAVE LABORATORY', 20, (gfx.W // 2, u(22)), PINK, True, 'midtop')
        gfx.blit_text(surf, 'LAB MODE', 44, (gfx.W // 2, u(52)), COLORS['text'], True, 'midtop')
        gfx.blit_text(surf, 'Chart your own songs and music videos. The assistant makes a first chart; you and it shape it from there.',
                      16, (gfx.W // 2, u(112)), COLORS['dim'], False, 'midtop')
        drop = pygame.Rect(u(140), u(150), gfx.W - u(280), u(150))
        sel = self.list_i == 0
        pygame.draw.rect(surf, COLORS['panel2'] if sel else COLORS['panel'], drop, border_radius=u(14))
        dash = MINT if sel else COLORS['line']
        for x in range(drop.x + u(16), drop.right - u(16), u(22)):
            pygame.draw.line(surf, dash, (x, drop.y + u(6)), (x + u(11), drop.y + u(6)), max(1, u(3)))
            pygame.draw.line(surf, dash, (x, drop.bottom - u(7)), (x + u(11), drop.bottom - u(7)), max(1, u(3)))
        gfx.blit_text(surf, 'Drop a song or music video on this window', 26, (drop.centerx, drop.y + u(26)), COLORS['text'], True, 'midtop')
        gfx.blit_text(surf, 'mp3, ogg, wav, flac, m4a  ·  mp4, mkv, webm, avi, mov', 15, (drop.centerx, drop.y + u(64)),
                      COLORS['dim'], False, 'midtop')
        self.button(surf, pygame.Rect(drop.centerx - u(110), drop.y + u(94), u(220), u(40)), 'Browse for a file...', self.browse,
                    active=sel, size=17, color=MINT)
        y = drop.bottom + u(26)
        gfx.blit_text(surf, 'YOUR LAB SONGS', 18, (u(140), y), PINK, True)
        gfx.blit_text(surf, 'saved in Songs/Rave Lab, so they are in the song list too', 14, (gfx.W - u(140), y + u(4)),
                      COLORS['dim'], anchor='topright')
        y += u(34)
        if not self.projects:
            gfx.blit_text(surf, 'Nothing here yet.', 18, (u(140), y), COLORS['dim'])
        first = max(0, min(self.list_i - 1 - 4, len(self.projects) - 7))
        for i, folder in enumerate(self.projects[first:first + 7], first):
            r = pygame.Rect(u(140), y, gfx.W - u(280), u(46))
            title, artist, charts, video, bpm = self.summaries.get(folder, (os.path.basename(folder), '', '', False, 0))
            is_sel = self.list_i == i + 1
            pygame.draw.rect(surf, COLORS['panel2'] if is_sel or r.collidepoint(self.hover) else COLORS['panel'], r, border_radius=u(8))
            if is_sel:
                pygame.draw.rect(surf, MINT, r, max(1, u(2)), border_radius=u(8))
            gfx.blit_text(surf, title + ('  ·  ' + artist if artist else ''), 19, (r.x + u(16), r.y + u(12)), COLORS['text'], True, max_w=u(560))
            info = '%s%s   %.0f BPM' % (charts or 'no charts yet', '   video' if video else '', bpm)
            gfx.blit_text(surf, info, 15, (r.right - u(16), r.y + u(15)), COLORS['dim'], anchor='topright', max_w=u(380))
            self.buttons.append((r, lambda f=folder: self.open_project(f)))
            y += u(52)
        gfx.blit_text(surf, 'Mouse or arrows + Enter to open   Esc back   Pad: ↑ ↓ choose, start open, back leaves', 15,
                      (gfx.W // 2, gfx.H - u(34)), COLORS['dim'], False, 'midtop')

    # ---------------------------------------------------------- editor

    def draw_editor(self, surf):
        p = self.project
        c = self.chart()
        if p.background:
            bg = self.app.images.get(os.path.join(p.folder, p.background), (gfx.W, gfx.H), 'cover')
            if bg is not None:
                surf.blit(bg, bg.get_rect(center=(gfx.W // 2, gfx.H // 2)))
                surf.blit(self.app.shade(225), (0, 0))
        if self.video is not None and self.video.frame is not None:
            frame = self.video.frame
            fr = frame.get_rect(center=(u((FIELD_X + MINIMAP_X) // 2), gfx.H // 2))
            surf.blit(frame, fr)
            surf.blit(self.app.shade(140, fr.size), fr)
        self.draw_topbar(surf, p, c)
        self.draw_chat(surf, p)
        self.draw_field(surf, p, c)
        self.draw_ruler(surf, p)
        self.draw_inspector(surf, p, c)
        self.draw_minimap(surf, p, c)

    def draw_topbar(self, surf, p, c):
        pygame.draw.rect(surf, (16, 19, 38), (0, 0, gfx.W, u(56)))
        self.button(surf, pygame.Rect(u(12), u(10), u(70), u(36)), '< Songs', self.close_editor, size=14)
        gfx.blit_text(surf, p.title, 20, (u(94), u(8)), COLORS['text'], True, max_w=u(330))
        sub = '%s%.2f BPM  ·  %s' % (p.artist + '  ·  ' if p.artist else '', p.bpm,
                                     'unsaved' if self.dirty else 'saved')
        gfx.blit_text(surf, sub, 13, (u(94), u(34)), COLORS['dim'], max_w=u(330))
        x = u(FIELD_X - 10)
        for d in DIFFS:
            ch = p.chart(d)
            label = '%s %s' % ({'Beginner': 'BEG', 'Easy': 'BASIC', 'Medium': 'DIFF', 'Hard': 'EXPERT', 'Challenge': 'CHAL'}[d],
                               ch.meter if ch else '+')
            r = pygame.Rect(x, u(10), u(78), u(36))
            self.button(surf, r, label, lambda d=d: self.set_diff(d), active=d == self.diff, size=14, color=COLORS[d])
            x += u(84)
        x += u(12)
        self.button(surf, pygame.Rect(x, u(10), u(88), u(36)), 'Stop' if self.playing else 'Play', self.toggle_play,
                    active=self.playing, size=15, color=MINT)
        x += u(94)
        self.button(surf, pygame.Rect(x, u(10), u(96), u(36)), 'Playtest', self.playtest, size=15, color=PINK)
        x += u(102)
        self.button(surf, pygame.Rect(x, u(10), u(62), u(36)), 'Undo', self.undo, size=14, enabled=bool(self.undo_stack))
        x += u(68)
        self.button(surf, pygame.Rect(x, u(10), u(62), u(36)), 'Redo', self.redo, size=14, enabled=bool(self.redo_stack))
        x += u(68)
        self.button(surf, pygame.Rect(x, u(10), u(62), u(36)), 'Save', lambda: (self.save(), self.app.toast('Saved')), size=14)

    def _input_rect(self):
        r = self._chat_rect()
        return pygame.Rect(r.x + u(10), r.bottom - u(54), r.w - u(20), u(44))

    def draw_chat(self, surf, p):
        r = self._chat_rect()
        bg = pygame.Surface(r.size, pygame.SRCALPHA)
        bg.fill((14, 17, 36, 235))
        surf.blit(bg, r)
        pygame.draw.rect(surf, PINK if self.chat_focus else COLORS['line'], r, max(1, u(2)), border_radius=u(10))
        gfx.blit_text(surf, 'LAB ASSISTANT', 17, (r.x + u(14), r.y + u(10)), PINK, True)
        setting = self.app.cfg.lab_ai
        opts = labai.PROVIDERS
        br = pygame.Rect(r.right - u(150), r.y + u(8), u(140), u(26))
        self.button(surf, br, 'AI: %s' % setting, lambda: self.app.cfg.set('lab_ai', opts[(opts.index(setting) + 1) % len(opts)]
                                                                            if setting in opts else 'auto'), size=13, color=PINK)
        # quick requests
        qx, qy = r.x + u(10), r.y + u(42)
        for label, prompt in QUICK:
            w = gfx.text(label, 13, None, True).get_width() + u(18)
            self.button(surf, pygame.Rect(qx, qy, w, u(26)), label, lambda pr=prompt: self.send_chat(pr), size=13, color=MINT)
            qx += w + u(6)
        # messages, newest at the bottom
        area = pygame.Rect(r.x + u(10), qy + u(34), r.w - u(20), self._input_rect().y - qy - u(44))
        clip = surf.get_clip()
        surf.set_clip(area)
        y = area.bottom + self.chat_scroll
        items = list(p.chat)
        if self.chat_req is not None:
            dots = '.' * (1 + int(time.perf_counter() * 2) % 3)
            items.append({'role': 'pending', 'text': 'Thinking%s  (%s, %ds)' % (dots, self.chat_req.label or 'starting',
                                                                               time.perf_counter() - self.chat_req.started)})
        width = area.w - u(24)
        for m in reversed(items):
            role = m.get('role')
            color = {'user': COLORS['text'], 'assistant': COLORS['text'], 'error': COLORS['miss'], 'note': MINT,
                     'pending': COLORS['dim']}.get(role, COLORS['dim'])
            size = 13 if m.get('auto') or role in ('note', 'pending') else 15
            text = ('(sent automatically) ' if m.get('auto') else '') + m.get('text', '')
            if m.get('auto') and len(text) > 160:
                text = text[:160] + '...'
            key = (text, size, width, role == 'user')
            lines = self.wrap_cache.get(key)
            if lines is None:
                lines = _wrap(text, size, width, role == 'user')
                self.wrap_cache[key] = lines
            logs = []
            for entry in m.get('log') or []:
                lk = ('log', entry, width)
                if lk not in self.wrap_cache:
                    ok = not entry.startswith(('could', 'unknown', 'skipped'))
                    self.wrap_cache[lk] = _wrap(('+ ' if ok else '! ') + entry, 12, width)
                logs += self.wrap_cache[lk]
            lh = u(size + 5)
            h = len(lines) * lh + len(logs) * u(16) + u(16) + (u(16) if role == 'assistant' else 0)
            y -= h + u(8)
            if y > area.bottom or y + h < area.y:
                continue
            bubble = pygame.Rect(area.x + (u(24) if role == 'user' else 0), y, area.w - u(24), h)
            fill = (58, 30, 62) if role == 'user' else (26, 32, 60) if role == 'assistant' else (20, 24, 44)
            pygame.draw.rect(surf, fill, bubble, border_radius=u(8))
            ty = bubble.y + u(8)
            if role == 'assistant':
                gfx.blit_text(surf, m.get('by') or 'assistant', 11, (bubble.x + u(10), ty), PINK, True)
                ty += u(16)
            for line in lines:
                gfx.blit_text(surf, line, size, (bubble.x + u(10), ty), color, role == 'user')
                ty += lh
            for line in logs:
                gfx.blit_text(surf, line, 12, (bubble.x + u(10), ty), COLORS['miss'] if line.startswith('! ') else MINT)
                ty += u(16)
        if not items:
            for i, line in enumerate(_wrap('Ask for anything: "make a Basic level 4", "add jumps on the chorus", '
                                           '"measure 20 feels awkward", "make the drop harder". '
                                           'The assistant sees the song\'s loudness map, the chart, and where your cursor is.', 14, width)):
                gfx.blit_text(surf, line, 14, (area.x + u(6), area.y + u(10) + i * u(20)), COLORS['dim'])
        surf.set_clip(clip)
        box = self._input_rect()
        pygame.draw.rect(surf, COLORS['panel2'], box, border_radius=u(8))
        pygame.draw.rect(surf, PINK if self.chat_focus else COLORS['line'], box, max(1, u(2)), border_radius=u(8))
        if self.chat_text or self.chat_focus:
            caret = '|' if self.chat_focus and int(time.perf_counter() * 2) % 2 else ''
            shown = self.chat_text + caret
            s = gfx.text(shown, 15)
            if s.get_width() > box.w - u(20):
                clip = surf.get_clip()
                surf.set_clip(box.inflate(-u(12), 0))
                surf.blit(s, (box.right - u(10) - s.get_width(), box.y + u(12)))
                surf.set_clip(clip)
            else:
                surf.blit(s, (box.x + u(10), box.y + u(12)))
        else:
            gfx.blit_text(surf, 'Click here or press Enter to talk to the assistant', 14, (box.x + u(10), box.y + u(13)), COLORS['dim'])

    def draw_field(self, surf, p, c):
        field = self._field_rect()
        surf.blit(self.app.shade(150, (field.w + u(8), field.h)), (field.x - u(4), field.y))
        clip = surf.get_clip()
        surf.set_clip(field.inflate(u(8), 0))
        top_t, bot_t = self.tick_at(field.y) - TICKS, self.tick_at(field.bottom) + TICKS
        # grid: measures, beats, snap lines
        step = self.step()
        start = max(0, int(top_t // step) * step)
        fine = self.ppb() * step / TICKS >= u(10)
        for t in range(start, int(bot_t), step if fine else TICKS):
            y = int(self.y_of(t))
            if t % MEASURE == 0:
                pygame.draw.line(surf, (190, 200, 235), (field.x, y), (field.right, y), max(1, u(2)))
            elif t % TICKS == 0:
                pygame.draw.line(surf, (80, 90, 130), (field.x, y), (field.right, y), 1)
            else:
                pygame.draw.line(surf, (42, 48, 78), (field.x, y), (field.right, y), 1)
        for k in range(1, 4):
            x = field.x + k * u(LANE)
            pygame.draw.line(surf, (40, 46, 74), (x, field.y), (x, field.bottom), 1)
        size = u(LANE - 6)
        pad = (u(LANE) - size) // 2
        if c:
            for n in c.notes:
                if n.end < top_t or n.tick > bot_t:
                    continue
                x = field.x + n.col * u(LANE) + pad
                y = self.y_of(n.tick)
                if n.kind in ('hold', 'roll'):
                    y2 = self.y_of(n.end)
                    body = self.app.hold_body(size, 'active', n.kind)
                    body_clip = pygame.Rect(x, int(y), size, int(y2 - y) + size // 2).clip(surf.get_clip())
                    old = surf.get_clip()
                    surf.set_clip(body_clip)
                    yy = int(y)
                    while yy < y2 + size // 2:
                        surf.blit(body, (x, yy))
                        yy += size
                    surf.set_clip(old)
                    pygame.draw.rect(surf, (230, 255, 235) if n.kind == 'hold' else (255, 200, 120),
                                     (x + size // 5, int(y2) - u(3), size - 2 * (size // 5), u(6)), border_radius=u(3))
                if n.kind == 'mine':
                    surf.blit(gfx.mine(size), (x, int(y) - size // 2))
                else:
                    q = 4 if n.tick % TICKS == 0 else 8 if n.tick % (TICKS // 2) == 0 else 16 if n.tick % (TICKS // 4) == 0 else 12
                    colr = (255, 140, 40) if n.kind == 'roll' else gfx.quant_color(q, 'rhythm')
                    surf.blit(gfx.arrow(size, n.col, colr), (x, int(y) - size // 2))
                if n in self.sel:
                    r = pygame.Rect(x - u(3), int(y) - size // 2 - u(3), size + u(6), size + u(6))
                    if n.kind in ('hold', 'roll'):
                        r.height = int(self.y_of(n.end) - y) + size + u(6)
                    pygame.draw.rect(surf, (90, 240, 255), r, max(1, u(2)), border_radius=u(6))
        # hover ghost
        if not self.drag and field.collidepoint(self.hover) and not self.playing:
            col = self.col_at(self.hover[0])
            note, part = self.note_at(self.hover)
            if col is not None and note is None:
                t = max(0, self.snap(self.tick_at(self.hover[1])))
                ghost = gfx.faded(gfx.arrow(size, col, (200, 200, 220)), 0.35)
                surf.blit(ghost, (field.x + col * u(LANE) + pad, int(self.y_of(t)) - size // 2))
            elif part == 'tail':
                pygame.draw.line(surf, (90, 240, 255), (field.x + col * u(LANE) + pad, int(self.y_of(note.end))),
                                 (field.x + col * u(LANE) + pad + size, int(self.y_of(note.end))), max(2, u(3)))
        # keyboard freeze in progress
        for col, start in self.key_down.items():
            a, b = sorted((start, self.cursor))
            pygame.draw.rect(surf, (90, 240, 255), (field.x + col * u(LANE) + pad, int(self.y_of(a)) - size // 2, size,
                                                     int(self.y_of(b) - self.y_of(a)) + size), max(1, u(2)), border_radius=u(6))
        # cursor
        cy = int(self.y_of(self.cursor))
        pygame.draw.line(surf, MINT if self.playing else COLORS['accent'], (field.x - u(4), cy), (field.right + u(4), cy), max(2, u(3)))
        if self.drag and self.drag['mode'] == 'box':
            (x0, y0), (x1, y1) = self.drag['a'], self.drag['b']
            box = pygame.Rect(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            pygame.draw.rect(surf, (90, 240, 255), box, 1)
        surf.set_clip(clip)

    def draw_ruler(self, surf, p):
        r = self._ruler_rect()
        surf.blit(self.app.shade(185, r.size), r)
        top_t, bot_t = self.tick_at(r.y) - TICKS, self.tick_at(r.bottom) + TICKS
        clip = surf.get_clip()
        surf.set_clip(r)
        # waveform: loudness at each row's song time, coloured by pitch
        if self.wave is not None:
            env, pcls, pstr = self.wave['env'], self.wave['pitch_class'], self.wave['pitch_strength']
            step = max(2, u(3))
            half = u(RULER_W - 58) // 2
            cx = r.x + u(52) + half
            for y in range(r.y, r.bottom, step):
                t = p.time_of_tick(self.tick_at(y))
                i = int(t / wavestrip.ENV_STEP)
                if 0 <= i < len(env):
                    a = min(1.2, float(env[i]))
                    if a > 0.02:
                        k = int(t / wavestrip.PITCH_STEP)
                        colr = wavestrip.PITCH_COLORS[int(pcls[k])] if 0 <= k < len(pcls) and pstr[k] > 0.12 else (130, 140, 170)
                        ln = int(a * half)
                        pygame.draw.line(surf, tuple(v // 2 + 30 for v in colr), (cx - ln, y), (cx + ln, y), step - 1)
        # beat markers
        for b in range(max(0, int(top_t // TICKS)), int(bot_t // TICKS) + 1):
            t = b * TICKS
            y = int(self.y_of(t))
            if b % 4 == 0:
                pygame.draw.line(surf, (220, 225, 250), (r.x, y), (r.right, y), max(1, u(2)))
                label = gfx.text(str(b // 4 + 1), 18, (235, 238, 255), True)
                tag = pygame.Rect(r.x + u(2), y + u(2), label.get_width() + u(10), label.get_height())
                pygame.draw.rect(surf, (40, 46, 90), tag, border_radius=u(4))
                surf.blit(label, (tag.x + u(5), tag.y))
            else:
                pygame.draw.line(surf, (110, 120, 160), (r.x, y), (r.x + u(22), y), max(1, u(2)))
                if self.ppb() >= u(40):
                    gfx.blit_text(surf, str(b % 4 + 1), 11, (r.x + u(26), y), (130, 140, 175), False, 'midleft')
        # song start / end
        for t_s, label in ((0.0, 'song starts'), ((p.analysis or {}).get('length', 0), 'song ends')):
            if t_s <= 0 and label == 'song ends':
                continue
            y = int(self.y_of(p.tick_of_time(t_s)))
            if r.y <= y <= r.bottom:
                pygame.draw.line(surf, PINK, (r.x, y), (r.right, y), max(1, u(2)))
                gfx.blit_text(surf, label, 11, (r.right - u(4), y - u(2)), PINK, True, 'bottomright')
        cy = int(self.y_of(self.cursor))
        pygame.draw.polygon(surf, MINT if self.playing else COLORS['accent'], [(r.x, cy - u(7)), (r.x + u(10), cy), (r.x, cy + u(7))])
        surf.set_clip(clip)
        gfx.blit_text(surf, 'BEATS', 11, (r.centerx, r.bottom + u(1)), COLORS['dim'], True, 'midtop')

    def draw_inspector(self, surf, p, c):
        x = u(INSPECT_X)
        w = u(MINIMAP_X - INSPECT_X - 12)
        panel = pygame.Rect(x - u(6), u(64), w + u(12), gfx.H - u(76))
        surf.blit(self.app.shade(190, panel.size), panel)
        y = u(72)

        def head(text):
            nonlocal y
            gfx.blit_text(surf, text, 13, (x, y), PINK, True)
            y += u(20)

        def row_buttons(items, h=26):
            nonlocal y
            n = len(items)
            bw = (w - u(4) * (n - 1)) // n
            for i, (label, fn, active) in enumerate(items):
                self.button(surf, pygame.Rect(x + i * (bw + u(4)), y, bw, u(h)), label, fn, active=active, size=12)
            y += u(h + 6)

        head('SONG')
        gfx.blit_text(surf, '%.2f BPM   offset %+.3f s' % (p.bpm, p.offset), 13, (x, y), COLORS['text'])
        y += u(20)
        row_buttons([('-0.1', lambda: self.change_bpm(delta=-0.1), False), ('+0.1', lambda: self.change_bpm(delta=0.1), False),
                     ('÷2', lambda: self.change_bpm(factor=0.5), False), ('×2', lambda: self.change_bpm(factor=2.0), False)])
        row_buttons([('-5ms', lambda: self.change_offset(-5), False), ('+5ms', lambda: self.change_offset(5), False),
                     ('bar <', lambda: self.shift_downbeat(-1), False), ('bar >', lambda: self.shift_downbeat(1), False)])
        gfx.blit_text(surf, 'bar < >  moves where measures start by a beat', 11, (x, y - u(3)), COLORS['dim'])
        y += u(14)
        row_buttons([('Add video' if not p.video else 'Change video', lambda: self.add_video(), False)])

        head('CHART  %s' % simfile.DIFF_NAMES[self.diff])
        meter = c.meter if c else labchart.DEFAULT_METER[self.diff]
        row_buttons([('-', lambda: self.set_meter(-1), False), ('level %d' % meter, lambda: None, False), ('+', lambda: self.set_meter(1), False)])
        st = c.stats(p.bpm) if c else {'steps': 0}
        if st['steps']:
            lines = ['%d steps  %d jumps  %d freezes' % (st['steps'], st['jumps'], st['freezes']),
                     '%.1f steps/s  on-beat %d%%  jacks %d%%' % (st['steps_per_s'], st['on_beat_pct'], st['jack_pct'])]
        else:
            lines = ['no arrows yet']
        for line in lines:
            gfx.blit_text(surf, line, 12, (x, y), COLORS['text'], max_w=w)
            y += u(17)
        y += u(4)
        row_buttons([('Generate', self.generate_builtin, False), ('Clear', self.clear_chart, False)])

        head('ARROWS  %s' % ('(%d selected)' % len(self.sel) if self.sel else '(none selected)'))
        kinds = {n.kind for n in self.sel}
        row_buttons([('Tap', lambda: self.set_sel_kind('tap'), kinds == {'tap'}), ('Freeze', lambda: self.set_sel_kind('hold'), kinds == {'hold'})])
        row_buttons([('Roll', lambda: self.set_sel_kind('roll'), kinds == {'roll'}), ('Mine', lambda: self.set_sel_kind('mine'), kinds == {'mine'})])
        row_buttons([('Mirror', lambda: self.mirror_sel({0: 3, 3: 0, 1: 2, 2: 1}), False), ('Flip ↔', lambda: self.mirror_sel({0: 3, 3: 0}), False),
                     ('Delete', self.delete_sel, False)])
        row_buttons([('Shorter', lambda: self.nudge_length(-1), False), ('Longer', lambda: self.nudge_length(1), False)])

        head('SNAP & VIEW')
        snap = labchart.SNAPS[self.snap_i]
        row_buttons([('<', lambda: setattr(self, 'snap_i', max(0, self.snap_i - 1)), False),
                     ('%s notes' % {4: '4th', 8: '8th', 12: '12th', 16: '16th', 24: '24th', 32: '32nd', 48: '48th'}[snap], lambda: None, False),
                     ('>', lambda: setattr(self, 'snap_i', min(len(labchart.SNAPS) - 1, self.snap_i + 1)), False)])
        row_buttons([('Zoom -', lambda: self.set_zoom(self.zoom / 1.25), False), ('Zoom +', lambda: self.set_zoom(self.zoom * 1.25), False),
                     ('Clap', lambda: self.app.cfg.set('lab_clap', not self.app.cfg.lab_clap), self.app.cfg.lab_clap)])
        m = self.cursor // MEASURE + 1
        beat = (self.cursor % MEASURE) / float(TICKS) + 1
        gfx.blit_text(surf, 'measure %d  beat %s  ·  %.2f s' % (m, labchart._num(beat), p.time_of_tick(self.cursor)), 12,
                      (x, y), COLORS['text'], max_w=w)
        y += u(22)
        help_lines = ['click: arrow · drag down: freeze', 'drag arrow: move · right click: delete', 'double click: type · Shift+drag: select',
                      '1-4 place · hold + ↑↓ freeze', 'Space play · P playtest here', 'Ctrl+Z undo · Tab difficulty']
        for line in help_lines:
            if y > panel.bottom - u(16):
                break
            gfx.blit_text(surf, line, 11, (x, y), COLORS['dim'], max_w=w)
            y += u(15)

    def draw_minimap(self, surf, p, c):
        r = self._minimap_rect()
        surf.blit(self.app.shade(190, r.size), r)
        total = float(self.total_ticks())
        loud = (p.analysis or {}).get('loudness') or []
        measures = int(total // MEASURE)
        mh = r.h / max(1, measures)
        top = max(loud) if loud else 1
        counts = [0] * (measures + 1)
        if c:
            for n in c.notes:
                if n.kind != 'mine':
                    counts[min(measures, n.tick // MEASURE)] += 1
        peak = max(counts) or 1
        for m in range(measures):
            y = r.y + int(m * mh)
            h = max(1, int(mh))
            if m < len(loud):
                lw = int((r.w // 2 - u(4)) * loud[m] / (top or 1))
                pygame.draw.rect(surf, (60, 70, 110), (r.x + u(2), y, lw, h))
            if counts[m]:
                cw = int((r.w // 2 - u(4)) * counts[m] / peak)
                pygame.draw.rect(surf, COLORS[self.diff] if self.diff in COLORS else MINT, (r.centerx + u(2), y, cw, h))
        rows = (FIELD_BOTTOM - FIELD_TOP) / self.zoom * TICKS
        vy = r.y + int(max(0, self.view) / total * r.h)
        vh = max(u(4), int(rows / total * r.h))
        pygame.draw.rect(surf, (230, 235, 255), (r.x, vy, r.w, min(vh, r.bottom - vy)), max(1, u(2)))
        cy = r.y + int(self.cursor / total * r.h)
        pygame.draw.line(surf, MINT if self.playing else COLORS['accent'], (r.x, cy), (r.right, cy), max(1, u(2)))
        gfx.blit_text(surf, 'SONG', 11, (r.centerx, r.bottom + u(1)), COLORS['dim'], True, 'midtop')
