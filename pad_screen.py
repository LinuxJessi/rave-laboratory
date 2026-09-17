"""Set up pad: step on each panel in turn and the game learns what the pad sends.

Opens by itself the first time an unknown pad is plugged in, and from Who's playing? > Set up pad or
F1 > Controls. Works with any pad that shows up as a joystick (buttons, d-pad hat, or axes).
Keys: Esc cancels, Backspace goes back one panel, Enter/Space skips an optional button.
"""
import time

import pygame

import gfx
import pads
from gfx import COLORS, u

STEPS = [('up', 'Step on UP', True), ('down', 'Step on DOWN', True), ('left', 'Step on LEFT', True),
         ('right', 'Step on RIGHT', True),
         ('start', 'Press START (centre panel or Start button)', False),
         ('back', 'Press BACK (a corner panel or Select/Back button)', False)]
COL_OF = {'left': 0, 'down': 1, 'up': 2, 'right': 3}


class PadSetupScreen:
    name = 'pad_setup'
    raw_keys = True                     # every key comes to key(), so Esc/Backspace/Enter work here

    def __init__(self, app, back_to, pad=None):
        self.app = app
        self.back_to = back_to              # screen object to return to
        self.pad = pad                      # None = whichever pad is stepped on first
        self.step = 0
        self.got = {}                       # action -> [codes]
        self.waiting_release = None         # (pad, code) pressed for the current step, waiting for release
        self.captured_at = 0.0
        self.opened = time.perf_counter()
        self.done = False
        self.message = ''

    def current(self):
        return STEPS[self.step] if self.step < len(STEPS) else None

    # ---------------------------------------------------------- input

    def raw_pad(self, pad, code, down):
        if self.done or time.perf_counter() - self.opened < 0.4:
            return
        if self.pad is not None and pad is not self.pad:
            return
        if self.waiting_release is not None:
            if not down and (pad, code) == self.waiting_release:
                self.waiting_release = None
                self._advance()
            return
        if not down:
            return
        used = {c for codes in self.got.values() for c in codes}
        if code in used:
            self.message = '%s is already %s' % (pads.describe_code(code), next(a for a, cs in self.got.items() if code in cs).upper())
            return
        if self.pad is None:
            self.pad = pad
        action = STEPS[self.step][0]
        self.got[action] = [code]
        self.captured_at = time.perf_counter()
        self.waiting_release = (pad, code)
        self.message = '%s = %s' % (action.upper(), pads.describe_code(code))

    def _advance(self):
        self.step += 1
        if self.step >= len(STEPS):
            self.finish()

    def on_action(self, action, down, stamp):
        pass                                # mapped actions are ignored here; the raw codes matter

    def key(self, ev):
        if ev.type != pygame.KEYDOWN:
            return
        if ev.key == pygame.K_ESCAPE:
            self.cancel()
        elif ev.key == pygame.K_BACKSPACE and self.step > 0:
            self.step -= 1
            self.got.pop(STEPS[self.step][0], None)
            self.waiting_release = None
            self.message = ''
        elif ev.key in (pygame.K_RETURN, pygame.K_SPACE, pygame.K_KP_ENTER):
            cur = self.current()
            if cur and not cur[2]:
                self.got.pop(cur[0], None)
                self._advance()
            elif cur is None:
                self.finish()

    def update(self):
        # a pad that never sends a release (some adapters) shouldn't stall the wizard
        if self.waiting_release is not None and time.perf_counter() - self.captured_at > 1.5:
            self.waiting_release = None
            self._advance()

    def finish(self):
        self.done = True
        if self.pad is not None and all(self.got.get(a) for a in pads.ARROWS):
            self.app.pads.save_bindings(self.pad, self.got)
            self.app.toast('Pad saved: %s' % self.pad.name)
        self.app.screen_obj = self.back_to

    def cancel(self):
        self.done = True
        if self.pad is not None and self.pad in self.app.pads.new_unmapped:
            self.app.pads.new_unmapped.remove(self.pad)      # don't nag again this session
        self.app.screen_obj = self.back_to

    # ---------------------------------------------------------- drawing

    def draw(self, surf):
        surf.fill(COLORS['bg'])
        gfx.blit_text(surf, 'RAVE LABORATORY', 20, (gfx.W // 2, u(26)), (255, 140, 220), True, 'midtop')
        gfx.blit_text(surf, 'SET UP PAD', 44, (gfx.W // 2, u(60)), COLORS['text'], True, 'midtop')
        names = [p.name for p in self.app.pads.pads.values()]
        who = self.pad.name if self.pad else (', '.join(names) if names else 'no pad connected: plug one in')
        gfx.blit_text(surf, who, 18, (gfx.W // 2, u(120)), COLORS['dim'], False, 'midtop', max_w=gfx.W - u(80))
        cur = self.current()
        size = u(96)
        cx = gfx.W // 2
        cy = u(300)
        for action, col in COL_OF.items():
            x = cx + (col - 1.5) * (size + u(10))
            done_ = action in self.got
            lit = cur and cur[0] == action
            style = 'receptor_lit' if lit else 'receptor'
            surf.blit(gfx.arrow(size, col, (0, 0, 0), style), (int(x), cy - size // 2))
            if done_:
                surf.blit(gfx.arrow(size, col, COLORS['great']), (int(x), cy - size // 2))
        if cur:
            gfx.blit_text(surf, cur[1], 34, (cx, u(400)), COLORS['accent'], True, 'midtop')
            if not cur[2]:
                gfx.blit_text(surf, 'Optional: Enter or Space skips it (Left+Right / Up+Down together work instead)', 17,
                              (cx, u(450)), COLORS['dim'], False, 'midtop')
        else:
            gfx.blit_text(surf, 'All set. Enter saves.', 34, (cx, u(400)), COLORS['great'], True, 'midtop')
        if self.message:
            gfx.blit_text(surf, self.message, 18, (cx, u(490)), COLORS['cyan'], False, 'midtop')
        y = u(540)
        for action, label, _ in STEPS:
            codes = self.got.get(action)
            txt = '%-6s  %s' % (action.upper(), ', '.join(pads.describe_code(c) for c in codes) if codes else '-')
            gfx.blit_text(surf, txt, 15, (cx - u(200), y), COLORS['text'] if codes else COLORS['dim'])
            y += u(20)
        gfx.blit_text(surf, 'Esc cancel   Backspace redo the last panel', 15, (cx, gfx.H - u(40)), COLORS['dim'], False, 'midtop')
