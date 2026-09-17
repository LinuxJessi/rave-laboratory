"""Song select: the music wheel, song search, favorites / most played, and the song info panel
(groove radar, Sensory rating, BPM, length, difficulty ladder)."""
import math
import time

import pygame

import chartstats
import gfx
import simfile
from gameplay import speed_multiplier
from gfx import COLORS, u

SORTS = ['group', 'level', 'title']
SPECIAL = ('search', 'favorites', 'most', 'recent')
HOLD_FAVORITE_S = 0.6
CHORD_S = 0.2
ARROWS = ('left', 'down', 'up', 'right')
PARTNER = {'left': 'right', 'right': 'left', 'up': 'down', 'down': 'up'}
KEY_ROWS = [list('ABCDEFGHIJ'), list('KLMNOPQRST'), list('UVWXYZ0123'), list("456789-'&!"),
            ['SPACE', 'DEL', 'CLEAR', 'SEARCH']]
RADAR_AXES = [('STREAM', -90), ('VOLTAGE', -162), ('AIR', 126), ('FREEZE', 54), ('CHAOS', -18)]


def sensory_color(score):
    for limit, colr in ((20, (138, 212, 255)), (35, (124, 252, 124)), (50, (246, 224, 94)), (70, (246, 161, 60))):
        if score < limit:
            return colr
    return (242, 85, 95)


def fmt_len(secs):
    secs = int(round(secs or 0))
    return '%d:%02d' % (secs // 60, secs % 60)


def draw_star(surf, center, r, color):
    cx, cy = center
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.45
        a = math.radians(-90 + i * 36)
        pts.append((cx + math.cos(a) * rad, cy + math.sin(a) * rad))
    pygame.draw.polygon(surf, color, pts)


class SearchBox:
    """On-screen keyboard that works from the pad, plus normal typing."""

    def __init__(self, screen):
        self.screen = screen
        self.open = False
        self.query = ''
        self.row = self.col = 0
        self.results = []

    def start(self, query=''):
        self.open = True
        self.query = query
        self.row = self.col = 0
        self.refresh()
        pygame.key.start_text_input()

    def close(self):
        self.open = False
        pygame.key.stop_text_input()

    def refresh(self):
        self.results = self.screen.app.library.search(self.query) if self.query.strip() else []

    def press(self, key):
        if key == 'SPACE':
            self.query += ' '
        elif key == 'DEL':
            self.query = self.query[:-1]
        elif key == 'CLEAR':
            self.query = ''
        elif key == 'SEARCH':
            self.submit()
            return
        else:
            self.query += key.lower()
        self.refresh()

    def submit(self):
        if not self.query.strip():
            self.close()
            return
        if not self.results:
            self.screen.app.toast('No songs match "%s"' % self.query.strip())
            return
        self.close()
        self.screen.show_search(self.query.strip())

    def move(self, dr, dc):
        self.row = (self.row + dr) % len(KEY_ROWS)
        self.col = min(self.col, len(KEY_ROWS[self.row]) - 1)
        if dc:
            self.col = (self.col + dc) % len(KEY_ROWS[self.row])

    def action(self, action):
        if action == 'left':
            self.move(0, -1)
        elif action == 'right':
            self.move(0, 1)
        elif action == 'up':
            self.move(-1, 0)
        elif action == 'down':
            self.move(1, 0)
        elif action == 'start':
            self.press(KEY_ROWS[self.row][self.col])
        elif action == 'back':
            self.close()

    def event(self, ev):
        if ev.type == pygame.TEXTINPUT:
            self.query += ev.text
            self.refresh()
        elif ev.type == pygame.KEYDOWN:
            if ev.key == pygame.K_BACKSPACE:
                self.press('DEL')
            elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self.submit()
            elif ev.key == pygame.K_ESCAPE:
                self.close()
            elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
                self.action({pygame.K_LEFT: 'left', pygame.K_RIGHT: 'right', pygame.K_UP: 'up', pygame.K_DOWN: 'down'}[ev.key])

    def draw(self, surf):
        box = pygame.Rect(u(190), u(90), gfx.W - u(380), u(540))
        surf.blit(self.screen.app.shade(150), (0, 0))
        pygame.draw.rect(surf, (12, 16, 34), box, border_radius=u(10))
        pygame.draw.rect(surf, COLORS['cyan'], box, max(1, u(3)), border_radius=u(10))
        x = box.x + u(28)
        gfx.blit_text(surf, 'SEARCH SONGS', 22, (x, box.y + u(18)), COLORS['cyan'], True)
        gfx.blit_text(surf, 'title, artist or folder', 15, (box.right - u(28), box.y + u(24)), COLORS['dim'], anchor='topright')
        field = pygame.Rect(x, box.y + u(56), box.w - u(56), u(48))
        pygame.draw.rect(surf, COLORS['panel2'], field, border_radius=u(6))
        caret = '|' if int(time.perf_counter() * 2) % 2 else ' '
        gfx.blit_text(surf, self.query + caret, 26, (field.x + u(14), field.y + u(8)), COLORS['text'], True, max_w=field.w - u(28))
        ky = field.bottom + u(18)
        for r, keys in enumerate(KEY_ROWS):
            kw = (field.w - u(8) * (len(keys) - 1)) // len(keys)
            for c, key in enumerate(keys):
                kr = pygame.Rect(field.x + c * (kw + u(8)), ky, kw, u(40))
                sel = r == self.row and c == self.col
                pygame.draw.rect(surf, COLORS['cyan'] if sel else COLORS['panel'], kr, border_radius=u(5))
                gfx.blit_text(surf, key, 18, kr.center, (10, 12, 24) if sel else COLORS['text'], True, 'center')
            ky += u(48)
        n = len(self.results)
        label = ('%d songs' % n) if self.query.strip() else 'Start typing, or step on letters'
        gfx.blit_text(surf, label, 18, (x, ky + u(4)), COLORS['accent'] if n else COLORS['dim'], True)
        names = ', '.join(e['title'] for e in self.results[:6])
        gfx.blit_text(surf, names, 15, (x, ky + u(30)), COLORS['dim'], max_w=field.w)
        gfx.blit_text(surf, 'Pad: arrows move, ←+→ types the key, ↑+↓ closes    Keys: type, Enter search, Esc close', 14,
                      (box.centerx, box.bottom - u(26)), COLORS['dim'], anchor='center')


class SelectScreen:
    name = 'select'

    def __init__(self, app):
        self.app = app
        last = app.scores.data['last']
        self.sort = last.get('sort', 'group')
        self.pref_diff = last.get('diff', 'Easy')
        self.query = ''
        self.open_folder = None
        self.folder_list = []
        self.items = []
        self.cursor = 0
        self.chart_i = 0
        self.hold_dir = 0
        self.hold_next = 0.0
        self.preview_due = None
        self.preview_started = None
        self.preview_rel = None
        self.confirm_until = 0.0
        self.pad_down = {}
        self.chord = None
        self.quit_until = 0.0
        self.start_down = None
        self.last_space = 0.0
        self.search = SearchBox(self)
        self.play_counts = {}
        self.built = False
        self.lib_generation = 0

    # ---------------------------------------------------------- wheel model

    def _counts(self):
        lib = self.app.library
        # the profile's own plays, including those imported from its OutFox profile
        return {rel: n for rel, n in self.app.scores.plays().items() if rel in lib.by_rel}

    def folders(self):
        lib = self.app.library
        scores = self.app.scores
        out = []
        if self.query:
            out.append(('Search: %s' % self.query, lib.search(self.query), None, 'search'))
        out.append(('Favorites', [lib.by_rel[r] for r in scores.data['favorites'] if r in lib.by_rel], None, 'favorites'))
        self.play_counts = self._counts()
        most = sorted((r for r, n in self.play_counts.items() if n > 0 and r in lib.by_rel), key=lambda r: -self.play_counts[r])
        if most:
            out.append(('Most played', [lib.by_rel[r] for r in most[:60]], None, 'most'))
        recent = [lib.by_rel[r] for r in scores.data['recent'] if r in lib.by_rel]
        if recent:
            out.append(('Recently played', recent, None, 'recent'))
        if self.sort == 'group':
            out += [(g, entries, None, 'group') for g, entries in lib.groups]
        elif self.sort == 'level':
            by = {}
            for _, entries in lib.groups:
                for e in entries:
                    for m in {c[1] for c in e['charts'] if c[0] != 'Edit'}:
                        by.setdefault(min(m, 20), []).append(e)
            for m in sorted(by):
                out.append(('Level %d%s' % (m, '+' if m == 20 else ''), sorted(by[m], key=lambda e: e['title'].lower()), m, 'group'))
        else:
            by = {}
            for _, entries in lib.groups:
                for e in entries:
                    ch = (e['title'][:1] or '#').upper()
                    by.setdefault(ch if ch.isalpha() else '#', []).append(e)
            for k in sorted(by):
                out.append((k, sorted(by[k], key=lambda e: e['title'].lower()), None, 'group'))
        return out

    def build(self, keep_rel=None):
        self.folder_list = self.folders()
        items = [('player',), ('search',)]
        for fi, (name, entries, meter, kind) in enumerate(self.folder_list):
            items.append(('folder', fi))
            if fi == self.open_folder:
                items += [('song', e, meter) for e in entries]
        self.items = items
        if keep_rel:
            for i, it in enumerate(items):
                if it[0] == 'song' and it[1]['rel'] == keep_rel:
                    self.cursor = i
                    break
        self.cursor = max(0, min(self.cursor, len(items) - 1))
        self.built = True
        self.on_cursor()

    def home_folder(self, rel, prefer_name=None):
        folders = self.folders()
        if prefer_name:
            for fi, (name, entries, _, kind) in enumerate(folders):
                if name == prefer_name and any(e['rel'] == rel for e in entries):
                    return fi
        for fi, (name, entries, _, kind) in enumerate(folders):
            if kind == 'group' and any(e['rel'] == rel for e in entries):
                return fi
        return None

    def restore(self):
        last = self.app.scores.data['last']
        rel = last.get('rel')
        if rel:
            self.open_folder = self.home_folder(rel, last.get('folder'))
        self.build(rel)

    def restore_to(self, rel):
        if rel:
            self.open_folder = self.home_folder(rel)
        self.build(rel)

    def show_search(self, query):
        self.query = query
        self.open_folder = 0
        self.build()
        self.cursor = 3 if len(self.items) > 3 else 2
        self.on_cursor()

    def current(self):
        return self.items[self.cursor] if self.items else None

    def entry(self):
        it = self.current()
        return it[1] if it and it[0] == 'song' else None

    def on_cursor(self):
        e = self.entry()
        if not e:
            self.preview_due = None
            return
        it = self.current()
        want_meter = it[2] if len(it) > 2 else None
        best, best_cost = 0, 1e9
        order = simfile.DIFF_ORDER
        for i, (d, m, desc) in enumerate(e['charts']):
            cost = abs(order.index(d) - order.index(self.pref_diff)) * 10 + (5 if desc and d == 'Edit' else 0)
            if want_meter is not None:
                cost += abs(m - want_meter) * 100
            if cost < best_cost:
                best, best_cost = i, cost
        self.chart_i = best
        self.app.sync.hold_until = time.perf_counter() + 1.5
        self.app.sync.request(e)
        if e['rel'] != self.preview_rel:
            self.preview_due = time.perf_counter() + self.app.cfg.preview_delay_ms / 1000.0

    # ---------------------------------------------------------- input

    def wants_text(self):
        return self.search.open

    def text_event(self, ev):
        self.search.event(ev)

    # 4-panel pads: Left+Right together = Start (hold = favorite), Up+Down together = Back.
    # The first arrow of a pair has already moved something, so a chord undoes that move.

    def _snapshot(self):
        return (self.cursor, self.chart_i, self.pref_diff, self.search.row, self.search.col)

    def _undo(self, snap):
        cursor, chart_i, pref_diff, srow, scol = snap
        if self.search.open:
            self.search.row, self.search.col = srow, scol
            return
        if cursor != self.cursor:
            self.cursor = cursor
            self.on_cursor()
        self.chart_i, self.pref_diff = chart_i, pref_diff

    def on_action(self, action, down, stamp):
        now = time.perf_counter()
        if action in ARROWS:
            partner = PARTNER[action]
            if down:
                self.pad_down[action] = (now, self._snapshot())
                other = self.pad_down.get(partner)
                if other and now - other[0] <= CHORD_S:
                    self._undo(other[1])
                    self.hold_dir = 0
                    self.chord = 'start' if action in ('left', 'right') else 'back'
                    self._chord_action(self.chord, True)
                    return
            else:
                self.pad_down.pop(action, None)
                if self.chord and (action in ('left', 'right')) == (self.chord == 'start'):
                    chord, self.chord = self.chord, None
                    self._chord_action(chord, False)
                    return
        self._single(action, down, now)

    def _chord_action(self, action, down):
        if self.search.open:
            if down:
                self.search.action(action)
            return
        self._single(action, down, time.perf_counter())

    def _single(self, action, down, now):
        if self.search.open:
            if down:
                self.search.action(action)
            return
        if action in ('left', 'right'):
            if down:
                self.move(-1 if action == 'left' else 1)
                self.hold_dir = -1 if action == 'left' else 1
                self.hold_next = now + self.app.cfg.wheel_delay_ms / 1000.0
            elif self.hold_dir == (-1 if action == 'left' else 1):
                self.hold_dir = 0
            return
        if action == 'start':
            it = self.current()
            if down:
                if it and it[0] == 'song':
                    self.start_down = now      # tap = play, hold = favorite (handled in update)
                else:
                    self.start()
            elif self.start_down is not None:
                self.start_down = None
                self.start()
            return
        if not down:
            return
        if action in ('up', 'down'):
            e = self.entry()
            if e:
                self.chart_i = max(0, min(len(e['charts']) - 1, self.chart_i + (1 if action == 'down' else -1)))
                self.pref_diff = e['charts'][self.chart_i][0]
        elif action == 'back':
            self.back()

    def key(self, ev):
        k = ev.key
        cfg = self.app.cfg
        if k == pygame.K_TAB:
            self.sort = SORTS[(SORTS.index(self.sort) + 1) % len(SORTS)]
            rel = self.entry()['rel'] if self.entry() else None
            self.open_folder = None
            self.restore_to(rel)
            self.app.toast('Sort: ' + self.sort)
        elif k in (pygame.K_MINUS, pygame.K_EQUALS, pygame.K_KP_MINUS, pygame.K_KP_PLUS):
            d = 1 if k in (pygame.K_EQUALS, pygame.K_KP_PLUS) else -1
            if cfg.scroll_mode == 'multiplier':
                cfg.set('multiplier', max(0.25, min(8.0, cfg.multiplier + 0.25 * d)))
            else:
                cfg.set('target_speed', max(100, min(1000, cfg.target_speed + 25 * d)))
        elif k in (pygame.K_LEFTBRACKET, pygame.K_RIGHTBRACKET):
            d = 5 if k == pygame.K_RIGHTBRACKET else -5
            cfg.set('audio_offset_ms', max(-300, min(300, cfg.audio_offset_ms + d)))
            self.app.toast('Audio offset %+d ms' % cfg.audio_offset_ms)
        elif k in (pygame.K_PAGEUP, pygame.K_PAGEDOWN):
            self.jump_folder(-1 if k == pygame.K_PAGEUP else 1)
        elif k == pygame.K_f and self.entry():
            self.toggle_favorite()
        elif k == pygame.K_SLASH or (k == pygame.K_f and ev.mod & pygame.KMOD_CTRL):
            self.search.start()
        elif k == pygame.K_SPACE:
            now = time.perf_counter()
            if now - self.last_space < 0.45:
                self.search.start()
            self.last_space = now

    def toggle_favorite(self):
        e = self.entry()
        if not e:
            return
        on = self.app.scores.toggle_favorite(e['rel'])
        self.app.toast(('Added to' if on else 'Removed from') + ' Favorites: ' + e['title'])
        self.build(e['rel'])

    def jump_folder(self, d):
        heads = [i for i, it in enumerate(self.items) if it[0] != 'song']
        if d < 0:
            prev = [i for i in heads if i < self.cursor]
            self.cursor = prev[-1] if prev else heads[-1]
        else:
            nxt = [i for i in heads if i > self.cursor]
            self.cursor = nxt[0] if nxt else heads[0]
        self.on_cursor()

    def move(self, d):
        if not self.items:
            return
        self.cursor = (self.cursor + d) % len(self.items)
        self.confirm_until = 0
        self.start_down = None
        self.on_cursor()

    def back(self):
        if self.open_folder is None:
            # top of the song list: back goes to Who's playing? (quit is a card there)
            self.app.to_profiles()
            return
        fi = self.open_folder
        self.open_folder = None
        self.build()
        self.cursor = next(i for i, it in enumerate(self.items) if it[0] == 'folder' and it[1] == fi)
        self.on_cursor()

    def start(self):
        it = self.current()
        if not it:
            return
        if it[0] == 'search':
            self.search.start()
            return
        if it[0] == 'player':
            self.app.to_profiles()
            return
        if it[0] == 'folder':
            fi = it[1]
            self.open_folder = None if self.open_folder == fi else fi
            self.build()
            self.cursor = next(i for i, x in enumerate(self.items) if x[0] == 'folder' and x[1] == fi)
            if self.open_folder is not None and self.cursor + 1 < len(self.items) and self.items[self.cursor + 1][0] == 'song':
                self.cursor += 1
            elif self.open_folder is not None and self.folder_list[fi][3] == 'favorites':
                self.app.toast('No favorites yet: hold Left+Right on a song (or press F)')
            self.on_cursor()
            return
        now = time.perf_counter()
        if self.app.cfg.confirm_twice and now > self.confirm_until:
            self.confirm_until = now + 2.0
            return
        e = it[1]
        d, m, desc = e['charts'][self.chart_i]
        self.app.scores.remember(rel=e['rel'], diff=self.pref_diff, meter=m, sort=self.sort,
                                 folder=self.folder_list[self.open_folder][0] if self.open_folder is not None else '')
        self.app.start_song(e, (d, m, desc))

    # ---------------------------------------------------------- update

    def update(self):
        if not self.built:
            if not self.app.library.ready:
                return
            self.restore()
            self.lib_generation = self.app.library.generation
        elif self.lib_generation != self.app.library.generation:
            self.lib_generation = self.app.library.generation
            e = self.entry()
            self.build(e['rel'] if e else None)
        now = time.perf_counter()
        if self.start_down is not None and now - self.start_down >= HOLD_FAVORITE_S:
            self.start_down = None
            self.toggle_favorite()
        if self.hold_dir and now >= self.hold_next:
            self.move(self.hold_dir)
            self.hold_next = now + self.app.cfg.wheel_repeat_ms / 1000.0
        e = self.entry()
        if self.preview_due and now >= self.preview_due and e and not self.hold_dir:
            self.preview_due = None
            self.preview_rel = e['rel']
            try:
                pygame.mixer.music.load(e['music'])
                pygame.mixer.music.set_volume(self.app.cfg.preview_volume / 100.0)
                pygame.mixer.music.play(start=max(0.0, e['sample_start']), fade_ms=500)
                self.preview_started = now
            except Exception:
                self.preview_started = None
        if self.preview_started and e and now - self.preview_started > e['sample_length'] + 1.2:
            pygame.mixer.music.fadeout(800)
            self.preview_started = None
            self.preview_rel = None
            self.preview_due = now + 1.0
        if not e and self.preview_rel:
            pygame.mixer.music.fadeout(500)
            self.preview_rel = None
            self.preview_started = None

    # ---------------------------------------------------------- drawing

    def draw(self, surf):
        app = self.app
        surf.fill(COLORS['bg'])
        if not app.library.ready:
            i, n = app.library.progress
            gfx.blit_text(surf, 'Loading songs  %d / %d' % (i, n), 28, (gfx.W // 2, gfx.H // 2 - u(20)), COLORS['text'], True, 'center')
            gfx.blit_text(surf, 'Indexing charts (Sensory, groove radar). This is cached after the first run.', 16,
                          (gfx.W // 2, gfx.H // 2 + u(20)), COLORS['dim'], False, 'center')
            return
        e = self.entry()
        if e and e.get('background'):
            bg = app.images.get(e['background'], (gfx.W, gfx.H), 'cover')
            if bg is not None:
                surf.blit(bg, bg.get_rect(center=(gfx.W // 2, gfx.H // 2)))
                surf.blit(app.shade(205), (0, 0))
        self.draw_info(surf, e)
        self.draw_wheel(surf)
        hint = 'Pad: ← → choose   ↑ ↓ difficulty   %s start (hold = favorite)   %s back / switch player' % (app.start_hint(), app.back_hint())
        gfx.blit_text(surf, hint, 15, (u(24), gfx.H - u(30)), COLORS['dim'])
        # who is playing, always visible
        chip = gfx.text('PLAYER  %s' % app.profile.name, 16, (255, 190, 235), True)
        r = chip.get_rect(topright=(gfx.W - u(80), u(4)))     # left of the fps counter
        pygame.draw.rect(surf, (40, 22, 40), r.inflate(u(16), u(6)), border_radius=u(6))
        surf.blit(chip, r)
        keys = 'Space×2 or / search   F favorite   Tab sort (%s)   -/= speed   F1 design   F2 note' % self.sort
        gfx.blit_text(surf, keys, 15, (gfx.W - u(24), gfx.H - u(30)), COLORS['dim'], anchor='topright')
        if self.search.open:
            self.search.draw(surf)

    def draw_info(self, surf, e):
        app = self.app
        panel = pygame.Rect(u(20), u(20), u(572), gfx.H - u(64))
        pygame.draw.rect(surf, COLORS['panel'], panel, border_radius=u(10))
        x = panel.x + u(18)
        if not e:
            it = self.current()
            if it and it[0] == 'player':
                gfx.blit_text(surf, 'Player: %s' % app.profile.name, 30, (x, panel.y + u(24)), COLORS['text'], True)
                gfx.blit_text(surf, 'Left+Right (or Enter) to switch player.', 20, (x, panel.y + u(70)), COLORS['accent'])
                gfx.blit_text(surf, 'Scores, favorites, speed and training settings are saved per player.', 18, (x, panel.y + u(104)), COLORS['dim'])
            elif it and it[0] == 'search':
                gfx.blit_text(surf, 'Search songs', 30, (x, panel.y + u(24)), COLORS['text'], True)
                gfx.blit_text(surf, 'Left+Right (or Enter) to open the keyboard.', 20, (x, panel.y + u(70)), COLORS['accent'])
                gfx.blit_text(surf, 'Matches title, artist and folder name.', 18, (x, panel.y + u(104)), COLORS['dim'])
            elif it:
                name, entries, _, kind = self.folder_list[it[1]]
                gfx.blit_text(surf, name, 30, (x, panel.y + u(24)), COLORS['text'], True, max_w=panel.w - u(36))
                gfx.blit_text(surf, '%d songs' % len(entries), 20, (x, panel.y + u(70)), COLORS['dim'])
                gfx.blit_text(surf, 'Left+Right (or Enter) to open', 20, (x, panel.y + u(104)), COLORS['accent'])
                if kind == 'favorites':
                    gfx.blit_text(surf, 'Add songs: hold Left+Right on a song, or press F.', 16, (x, panel.y + u(140)), COLORS['dim'])
                if kind == 'most':
                    gfx.blit_text(surf, 'Counts plays here plus those imported from OutFox.', 16, (x, panel.y + u(140)), COLORS['dim'])
            return

        # --- header: jacket + title block
        art = e.get('jacket') or e.get('banner') or e.get('background')
        box = (u(150), u(150))
        frame = pygame.Rect(x, panel.y + u(16), box[0], box[1])
        pygame.draw.rect(surf, (0, 0, 0), frame)
        img = app.images.get(art, box, 'fit')
        if img is not None:
            surf.blit(img, img.get_rect(center=frame.center))
        tx = frame.right + u(16)
        tw = panel.right - tx - u(16)
        y = frame.y + u(2)
        fav = app.scores.is_favorite(e['rel'])
        if fav:
            draw_star(surf, (tx + u(10), y + u(16)), u(10), COLORS['accent'])
        gfx.blit_text(surf, e['title'], 26, (tx + (u(26) if fav else 0), y), COLORS['text'], True, max_w=tw - (u(26) if fav else 0))
        y += u(36)
        if e.get('subtitle'):
            gfx.blit_text(surf, e['subtitle'], 15, (tx, y), COLORS['dim'], max_w=tw)
            y += u(20)
        gfx.blit_text(surf, e['artist'], 18, (tx, y), COLORS['dim'], max_w=tw)
        y += u(26)
        gfx.blit_text(surf, e['group'], 14, (tx, y), COLORS['dim'], max_w=tw)
        plays = self.play_counts.get(e['rel'], 0)
        if plays:
            gfx.blit_text(surf, ('%d play' if plays == 1 else '%d plays') % plays, 14, (panel.right - u(16), frame.bottom - u(18)), COLORS['dim'], anchor='topright')

        stats = e.get('stats') or []
        st = stats[self.chart_i] if self.chart_i < len(stats) else None

        # --- difficulty ladder
        y = frame.bottom + u(12)
        cols = (x + u(6), x + u(210), x + u(290), panel.right - u(16))
        gfx.blit_text(surf, 'DIFFICULTY', 12, (cols[0], y), COLORS['dim'], True)
        gfx.blit_text(surf, 'FOOT', 12, (cols[1], y), COLORS['dim'], True, 'midtop')
        gfx.blit_text(surf, 'SENSORY', 12, (cols[2], y), COLORS['dim'], True, 'midtop')
        gfx.blit_text(surf, 'BEST', 12, (cols[3], y), COLORS['dim'], True, 'topright')
        y += u(18)
        charts = e['charts']
        first = max(0, min(self.chart_i - 2, len(charts) - 5))
        for i in range(first, min(len(charts), first + 5)):
            d, m, desc = charts[i]
            sel = i == self.chart_i
            row = pygame.Rect(x, y, panel.w - u(36), u(28))
            if sel:
                pygame.draw.rect(surf, COLORS['panel2'], row, border_radius=u(4))
                pygame.draw.rect(surf, COLORS[d], row, max(1, u(2)), border_radius=u(4))
            label = simfile.DIFF_NAMES.get(d, d) + ('  ' + desc if d == 'Edit' and desc else '')
            gfx.blit_text(surf, label, 17, (cols[0], row.centery), COLORS[d], sel, 'midleft', max_w=u(190))
            gfx.blit_text(surf, str(m), 19, (cols[1], row.centery), COLORS['text'], True, 'center')
            cst = stats[i] if i < len(stats) else None
            if cst:
                gfx.blit_text(surf, str(cst['sensory']), 19, (cols[2], row.centery), sensory_color(cst['sensory']), True, 'center')
            best = app.scores.best(e['rel'], '%s|%s' % (d, desc))
            if best:
                gfx.blit_text(surf, '%s  %s' % (best.get('grade', ''), '{:,}'.format(best.get('score', 0))), 15,
                              (cols[3], row.centery), COLORS['accent'] if best.get('lamp_rank', 0) >= 3 else COLORS['dim'], False, 'midright')
            y += u(30)
        rungs = []
        for i, (d, m, desc) in enumerate(charts):
            if d == 'Edit' or i >= len(stats) or not stats[i]:
                continue
            v = str(stats[i]['sensory'])
            rungs.append('[%s]' % v if i == self.chart_i else v)
        if rungs:
            gfx.blit_text(surf, 'LADDER  ' + '  >  '.join(rungs), 16, (x + u(6), y + u(2)), COLORS['text'], True, max_w=panel.w - u(48))
        y += u(28)
        pygame.draw.line(surf, COLORS['line'], (x, y), (panel.right - u(18), y))
        y += u(8)

        # --- radar (left) and numbers (right)
        radar_c = (x + u(130), y + u(148))
        self.draw_radar(surf, radar_c, u(82), st, COLORS[charts[self.chart_i][0]])
        sx = x + u(292)
        sy = y + u(6)
        if st:
            gfx.blit_text(surf, 'SENSORY', 13, (sx, sy), COLORS['dim'], True)
            gfx.blit_text(surf, str(st['sensory']), 40, (sx, sy + u(12)), sensory_color(st['sensory']), True)
            gfx.blit_text(surf, 'NPS %.1f avg / %.1f peak' % (st['avg_nps'], st['peak_nps']), 15, (sx + u(80), sy + u(20)), COLORS['text'])
            mix = st['mix'] + ('   ' + ' '.join(st['gimmicks']) if st['gimmicks'] else '')
            gfx.blit_text(surf, mix, 14, (sx + u(80), sy + u(40)), COLORS['dim'], max_w=panel.right - sx - u(100))
            sy += u(70)
            est = st['bpm']
            gfx.blit_text(surf, 'BPM', 13, (sx, sy), COLORS['dim'], True)
            gfx.blit_text(surf, '%03d' % est['average'], 30, (sx, sy + u(12)), COLORS['text'], True)
            rng = '%03d' % est['average'] if est['constant'] else '%03d - %03d' % (round(est['min']), round(est['max']))
            gfx.blit_text(surf, 'AVG   range ' + rng, 14, (sx + u(66), sy + u(16)), COLORS['text'])
            tier = chartstats.speed_tier(est['dominant']) + ' / ' + chartstats.variability(est)
            gfx.blit_text(surf, tier, 14, (sx + u(66), sy + u(34)), sensory_color({'SLOW': 0, 'MODERATE': 25, 'FAST': 40, 'VERY FAST': 60}.get(chartstats.speed_tier(est['dominant']), 90)), True)
            sy += u(62)
            gfx.blit_text(surf, 'LENGTH  %s' % fmt_len(e.get('length')), 16, (sx, sy), COLORS['text'], True)
            sy += u(24)
            gfx.blit_text(surf, 'STEPS %d   JUMPS %d   FREEZES %d%s' % (st['steps'], st['jumps'], st['holds'],
                                                                     ('   SHOCKS %d' % st['mines']) if st['mines'] else ''),
                          14, (sx, sy), COLORS['dim'], max_w=panel.right - sx - u(18))
            sy += u(24)
        cfg = app.cfg
        rec = app.sync.get(e)
        if rec is None:
            sync = 'SYNC  checking...'
        elif rec.get('confident') and abs(rec.get('lag_ms', 0)) >= 15:
            sync = 'SYNC  chart moved %+d ms to match the music' % rec['lag_ms'] if cfg.auto_sync else 'SYNC  off by %+d ms (auto-fix is off)' % rec['lag_ms']
        elif rec.get('confident'):
            sync = 'SYNC  in time with the music'
        else:
            sync = 'SYNC  could not measure'
        gfx.blit_text(surf, sync, 14, (sx, sy), COLORS['dim'], max_w=panel.right - sx - u(18))
        sy += u(22)
        main_bpm = st['bpm']['dominant'] if st else e.get('bpm_max', 120)
        mult = speed_multiplier(cfg, main_bpm)
        speed = 'CMOD %d' % cfg.target_speed if cfg.scroll_mode == 'constant' else 'speed x%g  (reads %d)' % (mult, round(mult * main_bpm))
        gfx.blit_text(surf, speed, 14, (sx, sy), COLORS['cyan'])
        if self.confirm_until > time.perf_counter():
            gfx.blit_text(surf, 'Press Start again!', 24, (panel.centerx, panel.bottom - u(24)), COLORS['accent'], True, 'center')

    def draw_radar(self, surf, center, radius, st, color):
        cx, cy = center

        def point(i, frac):
            a = math.radians(RADAR_AXES[i][1])
            return (cx + math.cos(a) * radius * frac, cy + math.sin(a) * radius * frac)
        for frac in (0.25, 0.5, 0.75, 1.0):
            pygame.draw.polygon(surf, COLORS['line'] if frac == 1.0 else (45, 52, 90), [point(i, frac) for i in range(5)], 1)
        for i in range(5):
            pygame.draw.line(surf, (45, 52, 90), (cx, cy), point(i, 1.0))
        vals = st['radar'] if st else [0] * 5
        if st:
            shape = [point(i, max(0.04, min(1.0, v / 100.0))) for i, v in enumerate(vals)]
            layer = pygame.Surface((radius * 2 + 4, radius * 2 + 4), pygame.SRCALPHA)
            off = (cx - radius - 2, cy - radius - 2)
            pygame.draw.polygon(layer, color + (110,), [(px - off[0], py - off[1]) for px, py in shape])
            surf.blit(layer, off)
            pygame.draw.polygon(surf, color, shape, max(1, u(2)))
        for i, (name, ang) in enumerate(RADAR_AXES):
            lx, ly = point(i, 1.0)
            a = math.radians(ang)
            lx += math.cos(a) * u(16)
            ly += math.sin(a) * u(14)
            if i == 0:
                r = gfx.blit_text(surf, name, 11, (lx - u(4), ly), COLORS['dim'], True, 'bottomright')
                gfx.blit_text(surf, str(vals[i]), 15, (lx + u(2), r.bottom + u(2)), COLORS['text'], True, 'bottomleft')
                continue
            anchor = 'midright' if math.cos(a) < -0.3 else 'midleft' if math.cos(a) > 0.3 else 'midtop'
            r = gfx.blit_text(surf, name, 11, (lx, ly), COLORS['dim'], True, anchor)
            gfx.blit_text(surf, str(vals[i]), 15, (r.centerx, r.bottom), COLORS['text'], True, 'midtop')
        if st:
            tag = 'official DDR values' if st.get('radar_official') else 'computed'
            gfx.blit_text(surf, tag, 11, (cx, cy + radius + u(30)), COLORS['dim'], False, 'midtop')

    def draw_wheel(self, surf):
        if not self.items:
            return
        x = u(610)
        w = gfx.W - x - u(20)
        row_h = u(54)
        cy = gfx.H // 2 - u(20)
        span = 6
        favs = set(self.app.scores.data['favorites'])
        open_kind = self.folder_list[self.open_folder][3] if self.open_folder is not None else None
        for off in range(-span, span + 1):
            i = self.cursor + off
            if i < 0 or i >= len(self.items):
                continue
            it = self.items[i]
            y = cy + off * row_h - row_h // 2
            sel = off == 0
            r = pygame.Rect(x + (0 if sel else u(20)), y, w - (0 if sel else u(20)), row_h - u(4))
            fade = max(60, 255 - abs(off) * 28)
            if it[0] == 'player':
                pygame.draw.rect(surf, (60, 30, 60) if sel else (40, 22, 40), r, border_radius=u(6))
                if sel:
                    pygame.draw.rect(surf, (255, 140, 220), r, max(1, u(3)), border_radius=u(6))
                pygame.draw.circle(surf, (255, 140, 220), (r.x + u(26), r.centery - u(6)), u(6))
                pygame.draw.ellipse(surf, (255, 140, 220), (r.x + u(16), r.centery + u(2), u(20), u(12)))
                label = 'Player: %s' % self.app.profile.name
                gfx.blit_text(surf, label, 22, (r.x + u(52), r.centery), (255, 190, 235), True, 'midleft', max_w=r.w - u(200))
                gfx.blit_text(surf, 'switch player', 15, (r.right - u(16), r.centery), COLORS['dim'], anchor='midright')
            elif it[0] == 'search':
                pygame.draw.rect(surf, (20, 60, 80) if sel else (16, 36, 50), r, border_radius=u(6))
                if sel:
                    pygame.draw.rect(surf, COLORS['cyan'], r, max(1, u(3)), border_radius=u(6))
                pygame.draw.circle(surf, COLORS['cyan'], (r.x + u(26), r.centery - u(3)), u(8), max(1, u(3)))
                pygame.draw.line(surf, COLORS['cyan'], (r.x + u(32), r.centery + u(3)), (r.x + u(38), r.centery + u(9)), max(1, u(3)))
                label = 'Search songs' + ('   (last: %s)' % self.query if self.query else '')
                gfx.blit_text(surf, label, 22, (r.x + u(52), r.centery), COLORS['cyan'], True, 'midleft', max_w=r.w - u(70))
            elif it[0] == 'folder':
                name, entries, _, kind = self.folder_list[it[1]]
                is_open = it[1] == self.open_folder
                special = kind in SPECIAL
                base = (40, 30, 70) if special else (60, 50, 20)
                pygame.draw.rect(surf, base if sel else tuple(v * 6 // 10 for v in base), r, border_radius=u(6))
                if sel:
                    pygame.draw.rect(surf, (200, 150, 255) if special else COLORS['accent'], r, max(1, u(3)), border_radius=u(6))
                tcol = ((220, 190, 255) if special else (255, 220, 120)) if sel else ((fade * 200 // 255, fade * 170 // 255, fade) if special else (fade, fade * 200 // 255, 90))
                tx, ty, t = r.x + u(18), r.centery, u(7)
                if kind == 'favorites':
                    draw_star(surf, (tx + t, ty), u(10), tcol)
                else:
                    tri = [(tx, ty - t), (tx + 2 * t, ty - t), (tx + t, ty + t)] if is_open else [(tx, ty - t), (tx + 2 * t, ty), (tx, ty + t)]
                    pygame.draw.polygon(surf, tcol, tri)
                gfx.blit_text(surf, name, 22, (r.x + u(44), r.centery), tcol, True, 'midleft', max_w=r.w - u(140))
                gfx.blit_text(surf, str(len(entries)), 18, (r.right - u(16), r.centery), COLORS['dim'], anchor='midright')
            else:
                e = it[1]
                pygame.draw.rect(surf, COLORS['panel2'] if sel else COLORS['panel'], r, border_radius=u(6))
                if sel:
                    pygame.draw.rect(surf, COLORS['cyan'], r, max(1, u(3)), border_radius=u(6))
                col = COLORS['text'] if sel else (fade, fade, min(255, fade + 20))
                lx = r.x + u(16)
                if e['rel'] in favs:
                    draw_star(surf, (lx + u(8), r.y + u(16)), u(8), COLORS['accent'])
                    lx += u(22)
                gfx.blit_text(surf, e['title'], 22, (lx, r.y + u(2)), col, sel, max_w=r.right - lx - u(190))
                sub = e['artist']
                if open_kind == 'most':
                    sub = '%d plays   %s' % (self.play_counts.get(e['rel'], 0), sub)
                elif open_kind in ('search', 'favorites', 'recent'):
                    sub = '%s   (%s)' % (sub, e['group'])
                gfx.blit_text(surf, sub, 13, (r.x + u(16), r.y + u(30)), COLORS['dim'], max_w=r.w - u(200))
                cx = r.right - u(16)
                meters = {}
                for d, m, desc in e['charts']:
                    if d != 'Edit':
                        meters.setdefault(d, m)
                for d in reversed(simfile.DIFF_ORDER[:5]):
                    if d in meters:
                        gfx.blit_text(surf, str(meters[d]), 20, (cx, r.centery), COLORS[d], d == self.pref_diff, 'midright')
                    cx -= u(34)
