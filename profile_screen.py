"""Who's playing? Pick a profile (or make one) with the pad or keyboard.

Pad: Left/Right choose, Left+Right together = select, Up+Down together = back to songs.
On the first run with the song list loaded, every OutFox local profile is imported.
"""
import os
import time

import pygame

import gfx
import profiles
from gfx import COLORS, u
from select_screen import CHORD_S, KEY_ROWS, PARTNER

CARD_COLORS = [(255, 120, 200), (90, 200, 255), (255, 200, 60), (120, 230, 130), (190, 130, 255),
               (255, 150, 90), (80, 220, 200), (240, 90, 110), (160, 190, 255), (220, 220, 120)]


def draw_flask(surf, center, size, colr):
    cx, cy = center
    w = max(1, u(4))
    neck = size * 0.22
    pts = [(cx - neck, cy - size * 0.9), (cx - neck, cy - size * 0.25), (cx - size * 0.8, cy + size * 0.75),
           (cx + size * 0.8, cy + size * 0.75), (cx + neck, cy - size * 0.25), (cx + neck, cy - size * 0.9)]
    liquid = [(cx - size * 0.48, cy + size * 0.25), (cx - size * 0.8, cy + size * 0.75), (cx + size * 0.8, cy + size * 0.75),
              (cx + size * 0.48, cy + size * 0.25)]
    pygame.draw.polygon(surf, (255, 120, 210), liquid)
    pygame.draw.lines(surf, colr, False, pts, w)
    pygame.draw.line(surf, colr, (cx - neck * 1.6, cy - size * 0.9), (cx + neck * 1.6, cy - size * 0.9), w)
    for dx, dy, r in ((-0.2, 0.45, 0.09), (0.18, 0.55, 0.06), (0.02, 0.05, 0.07)):
        pygame.draw.circle(surf, colr, (int(cx + dx * size), int(cy + dy * size)), max(2, int(r * size)), max(1, w // 2))


class ProfileScreen:
    name = 'profiles'

    def __init__(self, app):
        self.app = app
        self.cards = []
        self.cursor = 0
        self.pad_down = {}
        self.naming = None           # {'text', 'row', 'col'} while typing a new name
        self.status = ''
        self.checked_outfox = False
        self.refresh()
        ids = [c.id if isinstance(c, profiles.Profile) else None for c in self.cards]
        if app.profile and app.profile.id in ids:
            self.cursor = ids.index(app.profile.id)

    def refresh(self):
        self.cards = self.app.profiles.all() + [None, 'lab', 'pads', 'quit']   # None = new player, then Lab mode, pad setup, exit
        self.summaries = {p.id: p.summary() for p in self.cards if isinstance(p, profiles.Profile)}

    # ---------------------------------------------------------- input

    def on_action(self, action, down, stamp):
        now = time.perf_counter()
        if action in PARTNER:
            if down:
                snap = (self.cursor, dict(self.naming) if self.naming else None)
                self.pad_down[action] = (now, snap)
                other = self.pad_down.get(PARTNER[action])
                if other and now - other[0] <= CHORD_S:
                    self.cursor, naming = other[1]
                    if self.naming is not None and naming is not None:
                        self.naming = naming
                    self._do('start' if action in ('left', 'right') else 'back')
                    return
            else:
                self.pad_down.pop(action, None)
                return
        if down:
            self._do(action)

    def _do(self, action):
        if self.naming is not None:
            n = self.naming
            if action in ('left', 'right'):
                n['col'] = (n['col'] + (1 if action == 'right' else -1)) % len(KEY_ROWS[n['row']])
            elif action in ('up', 'down'):
                n['row'] = (n['row'] + (1 if action == 'down' else -1)) % len(KEY_ROWS)
                n['col'] = min(n['col'], len(KEY_ROWS[n['row']]) - 1)
            elif action == 'start':
                key = KEY_ROWS[n['row']][n['col']]
                if key == 'SPACE':
                    n['text'] += ' '
                elif key == 'DEL':
                    n['text'] = n['text'][:-1]
                elif key == 'CLEAR':
                    n['text'] = ''
                elif key == 'SEARCH':
                    self._finish_name()
                else:
                    n['text'] += key if not n['text'] or n['text'].endswith(' ') else key.lower()
            elif action == 'back':
                self._stop_naming()
            return
        if action in ('left', 'right'):
            self.cursor = (self.cursor + (1 if action == 'right' else -1)) % len(self.cards)
        elif action == 'start':
            card = self.cards[self.cursor]
            if card == 'quit':
                pygame.event.post(pygame.event.Event(pygame.QUIT))
            elif card == 'lab':
                self.app.to_lab()
            elif card == 'pads':
                self.app.open_pad_setup()
            elif card is None:
                self.naming = {'text': '', 'row': 0, 'col': 0}
                pygame.key.start_text_input()
            else:
                self.app.set_profile(card)
        elif action == 'back' and self.app.library.ready:
            self.app.set_profile(self.app.profile)

    def key(self, ev):
        if ev.key == pygame.K_i and self.app.library.ready:
            self.do_import()
        elif ev.key == pygame.K_p:
            self.app.open_pad_setup()

    def wants_text(self):
        return self.naming is not None

    def text_event(self, ev):
        n = self.naming
        if ev.type == pygame.TEXTINPUT:
            n['text'] = (n['text'] + ev.text)[:24]
        elif ev.key == pygame.K_BACKSPACE:
            n['text'] = n['text'][:-1]
        elif ev.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            self._finish_name()
        elif ev.key == pygame.K_ESCAPE:
            self._stop_naming()
        elif ev.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_UP, pygame.K_DOWN):
            self._do({pygame.K_LEFT: 'left', pygame.K_RIGHT: 'right', pygame.K_UP: 'up', pygame.K_DOWN: 'down'}[ev.key])

    def _stop_naming(self):
        self.naming = None
        pygame.key.stop_text_input()

    def _finish_name(self):
        name = self.naming['text'].strip()
        if not name:
            return
        if self.app.profiles.find_by_name(name):
            self.app.toast('There is already a player called %s' % name)
            return
        cfg = self.app.cfg
        p = self.app.profiles.create(name, {k: cfg.machine[k] for k in profiles.PERSONAL if k in cfg.machine})
        self._stop_naming()
        self.refresh()
        self.cursor = next(i for i, c in enumerate(self.cards) if isinstance(c, profiles.Profile) and c.id == p.id)
        self.app.toast('Made player %s' % name)

    def do_import(self):
        report = self.app.profiles.import_outfox(self.app.library, self.app.cfg.machine)
        self.refresh()
        if report:
            self.status = 'Imported from OutFox: ' + ', '.join('%s (%d charts)' % r for r in report)
        else:
            self.status = 'No OutFox profiles found'
        # scores for the active player may have changed on disk
        if self.app.profile:
            self.app.scores.__init__(self.app.profile.scores_path, self.app.profile.runs_dir)

    # ---------------------------------------------------------- update/draw

    def update(self):
        if self.app.library.ready and not self.checked_outfox:
            self.checked_outfox = True
            if not self.app.profiles.index.get('outfox_imported') or self.app.profiles.outfox_changed():
                self.do_import()

    def draw(self, surf):
        surf.fill(COLORS['bg'])
        gfx.blit_text(surf, 'RAVE LABORATORY', 20, (gfx.W // 2, u(26)), (255, 140, 220), True, 'midtop')
        gfx.blit_text(surf, "WHO'S PLAYING?", 44, (gfx.W // 2, u(60)), COLORS['text'], True, 'midtop')
        if not self.app.library.ready:
            i, n = self.app.library.progress
            gfx.blit_text(surf, 'Loading songs %d / %d  (OutFox profiles import once this finishes)' % (i, n), 16,
                          (gfx.W // 2, u(118)), COLORS['dim'], False, 'midtop')
        elif self.status:
            gfx.blit_text(surf, self.status, 15, (gfx.W // 2, u(118)), COLORS['great'], False, 'midtop', max_w=gfx.W - u(80))
        card_w, card_h, gap = u(230), u(300), u(26)
        n = len(self.cards)
        cx = gfx.W // 2 - (self.cursor * (card_w + gap)) - card_w // 2
        top = u(190)
        for i, p in enumerate(self.cards):
            x = cx + i * (card_w + gap)
            if x + card_w < -card_w or x > gfx.W + card_w:
                continue
            sel = i == self.cursor
            r = pygame.Rect(x, top - (u(16) if sel else 0), card_w, card_h + (u(32) if sel else 0))
            colr = CARD_COLORS[i % len(CARD_COLORS)] if isinstance(p, profiles.Profile) else COLORS['dim']
            pygame.draw.rect(surf, COLORS['panel2'] if sel else COLORS['panel'], r, border_radius=u(14))
            pygame.draw.rect(surf, colr if sel else COLORS['line'], r, max(1, u(4 if sel else 2)), border_radius=u(14))
            if p == 'lab':
                draw_flask(surf, (r.centerx, r.y + u(95)), u(50), (120, 255, 200) if sel else COLORS['dim'])
                gfx.blit_text(surf, 'Lab mode', 24, (r.centerx, r.y + u(162)), COLORS['text'], True, 'midtop')
                for k, line in enumerate(('Chart your own songs', 'and music videos', 'with AI help')):
                    gfx.blit_text(surf, line, 15, (r.centerx, r.y + u(204) + k * u(22)), COLORS['dim'], False, 'midtop')
                continue
            if p == 'pads':
                pcol = (120, 200, 255) if sel else COLORS['dim']
                cell = u(26)
                for row in range(3):
                    for col in range(3):
                        cr = pygame.Rect(r.centerx - cell * 1.5 + col * cell + u(2), r.y + u(52) + row * cell + u(2), cell - u(4), cell - u(4))
                        arrow = (row, col) in ((0, 1), (1, 0), (1, 2), (2, 1))
                        pygame.draw.rect(surf, pcol if arrow else (40, 44, 60), cr, 0 if arrow else max(1, u(2)), border_radius=u(4))
                gfx.blit_text(surf, 'Set up pad', 24, (r.centerx, r.y + u(162)), COLORS['text'], True, 'midtop')
                names = list(self.app.pads.pads.values())
                lines = [pp.name[:22] + (' (ready)' if pp.ready else ' (not set up)') for pp in names[:2]] or ['no pad connected', 'keyboard arrows work']
                for k, line in enumerate(lines + ['step on each panel']):
                    gfx.blit_text(surf, line, 15, (r.centerx, r.y + u(204) + k * u(22)), COLORS['dim'], False, 'midtop', max_w=card_w - u(16))
                continue
            if p == 'quit':
                pygame.draw.circle(surf, COLORS['miss'], (r.centerx, r.y + u(95)), u(46), max(1, u(4)))
                pygame.draw.line(surf, COLORS['miss'], (r.centerx, r.y + u(62)), (r.centerx, r.y + u(98)), max(1, u(6)))
                gfx.blit_text(surf, 'Quit game', 24, (r.centerx, r.y + u(170)), COLORS['text'], True, 'midtop')
                continue
            if p is None:
                pygame.draw.circle(surf, colr, (r.centerx, r.y + u(95)), u(46), max(1, u(4)))
                pygame.draw.line(surf, colr, (r.centerx - u(22), r.y + u(95)), (r.centerx + u(22), r.y + u(95)), max(1, u(5)))
                pygame.draw.line(surf, colr, (r.centerx, r.y + u(73)), (r.centerx, r.y + u(117)), max(1, u(5)))
                gfx.blit_text(surf, 'New player', 24, (r.centerx, r.y + u(170)), COLORS['text'], True, 'midtop')
                continue
            pygame.draw.circle(surf, colr, (r.centerx, r.y + u(95)), u(52))
            initial = (p.name[:1] or '?').upper()
            gfx.blit_text(surf, initial, 54, (r.centerx, r.y + u(95)), (15, 15, 30), True, 'center')
            gfx.blit_text(surf, p.name, 26, (r.centerx, r.y + u(162)), COLORS['text'], True, 'midtop', max_w=card_w - u(20))
            s = self.summaries.get(p.id, {})
            lines = ['%d plays' % s.get('plays', 0), '%d songs, %d AA or better' % (s.get('songs', 0), s.get('aa', 0))]
            if s.get('last'):
                lines.append('last played %s' % s['last'])
            if p.data.get('outfox'):
                lines.append('from OutFox')
            for k, line in enumerate(lines):
                gfx.blit_text(surf, line, 15, (r.centerx, r.y + u(204) + k * u(22)), COLORS['dim'], False, 'midtop', max_w=card_w - u(16))
        gfx.blit_text(surf, 'Pad: ← → choose   %s play as this player   %s back to songs' % (self.app.start_hint(), self.app.back_hint()), 17,
                      (gfx.W // 2, gfx.H - u(80)), COLORS['dim'], False, 'midtop')
        keys = 'Keys: arrows, Enter, Esc    P = set up pad'
        if os.path.isdir(profiles.OUTFOX_PROFILES):
            keys += '    I = import again from OutFox (adds new plays and scores)'
        gfx.blit_text(surf, keys, 15, (gfx.W // 2, gfx.H - u(50)), COLORS['dim'], False, 'midtop')
        if self.naming is not None:
            self.draw_naming(surf)

    def draw_naming(self, surf):
        n = self.naming
        box = pygame.Rect(u(190), u(120), gfx.W - u(380), u(470))
        surf.blit(self.app.shade(170), (0, 0))
        pygame.draw.rect(surf, (12, 16, 34), box, border_radius=u(10))
        pygame.draw.rect(surf, (255, 140, 220), box, max(1, u(3)), border_radius=u(10))
        x = box.x + u(28)
        gfx.blit_text(surf, 'NEW PLAYER NAME', 22, (x, box.y + u(18)), (255, 140, 220), True)
        field = pygame.Rect(x, box.y + u(56), box.w - u(56), u(48))
        pygame.draw.rect(surf, COLORS['panel2'], field, border_radius=u(6))
        caret = '|' if int(time.perf_counter() * 2) % 2 else ' '
        gfx.blit_text(surf, n['text'] + caret, 26, (field.x + u(14), field.y + u(8)), COLORS['text'], True)
        ky = field.bottom + u(18)
        for r_i, keys in enumerate(KEY_ROWS):
            kw = (field.w - u(8) * (len(keys) - 1)) // len(keys)
            for c_i, key in enumerate(keys):
                kr = pygame.Rect(field.x + c_i * (kw + u(8)), ky, kw, u(40))
                sel = r_i == n['row'] and c_i == n['col']
                label = 'DONE' if key == 'SEARCH' else key
                pygame.draw.rect(surf, (255, 140, 220) if sel else COLORS['panel'], kr, border_radius=u(5))
                gfx.blit_text(surf, label, 18, kr.center, (10, 12, 24) if sel else COLORS['text'], True, 'center')
            ky += u(48)
        gfx.blit_text(surf, 'Pad: arrows move, ←+→ types, ↑+↓ cancels    Keys: type, Enter done, Esc cancel', 14,
                      (box.centerx, box.bottom - u(24)), COLORS['dim'], anchor='center')
