"""Design Mode (F1): live-edit every setting, and the note box (F2) for leaving feedback."""
import json
import os
import time

import pygame

import gfx
import settings
from gfx import COLORS, u

NOTES = os.path.join(settings.DATA, 'design-notes.jsonl')


class DesignOverlay:
    def __init__(self, app):
        self.app = app
        self.open = False
        self.section = 0
        self.row = 0

    def fields(self):
        name = settings.SECTIONS[self.section]
        return [f for f in settings.FIELDS if f[2] == name]

    def toggle(self):
        self.open = not self.open

    def key(self, ev):
        """Handle a KEYDOWN while open. Returns True if consumed."""
        k = ev.key
        shift = bool(ev.mod & pygame.KMOD_SHIFT)
        fields = self.fields()
        if k in (pygame.K_F1, pygame.K_ESCAPE):
            self.open = False
        elif k == pygame.K_UP:
            self.row = (self.row - 1) % len(fields)
        elif k == pygame.K_DOWN:
            self.row = (self.row + 1) % len(fields)
        elif k in (pygame.K_TAB, pygame.K_PAGEDOWN):
            step = -1 if shift and k == pygame.K_TAB else 1
            self.section = (self.section + step) % len(settings.SECTIONS)
            self.row = 0
        elif k == pygame.K_PAGEUP:
            self.section = (self.section - 1) % len(settings.SECTIONS)
            self.row = 0
        elif k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_RETURN, pygame.K_SPACE):
            d = -1 if k == pygame.K_LEFT else 1
            if fields[self.row][4] == 'button':
                if k in (pygame.K_RETURN, pygame.K_SPACE):
                    self.open = False
                    self.app.design_button(fields[self.row][0])
                return True
            self.app.cfg.adjust(fields[self.row], d, big=shift)
            self.app.settings_changed(fields[self.row][0])
        elif k in (pygame.K_BACKSPACE, pygame.K_DELETE):
            self.app.cfg.reset(fields[self.row])
            self.app.settings_changed(fields[self.row][0])
        else:
            return False
        return True

    def pad(self, action):
        """Pad navigation while open (menus only)."""
        fake = {'up': pygame.K_UP, 'down': pygame.K_DOWN, 'left': pygame.K_LEFT, 'right': pygame.K_RIGHT,
                'start': pygame.K_TAB, 'back': pygame.K_ESCAPE}.get(action)
        if fake:
            self.key(pygame.event.Event(pygame.KEYDOWN, key=fake, mod=0))

    def draw(self, surf):
        if not self.open:
            return
        cfg = self.app.cfg
        w = u(560)
        panel = pygame.Rect(gfx.W - w - u(20), u(20), w, gfx.H - u(40))
        bg = pygame.Surface(panel.size, pygame.SRCALPHA)
        bg.fill((8, 10, 22, 235))
        surf.blit(bg, panel)
        pygame.draw.rect(surf, COLORS['accent'], panel, max(1, u(2)), border_radius=u(6))
        x, y = panel.x + u(18), panel.y + u(12)
        gfx.blit_text(surf, 'DESIGN MODE', 24, (x, y), COLORS['accent'], True)
        gfx.blit_text(surf, 'pink "player" settings save to %s; the rest to this machine' % (cfg.profile.name if cfg.profile else 'the player'), 14, (panel.right - u(18), y + u(8)), COLORS['dim'], anchor='topright')
        y += u(40)
        tx = x
        for i, name in enumerate(settings.SECTIONS):
            r = gfx.blit_text(surf, name, 16, (tx, y), COLORS['text'] if i == self.section else COLORS['dim'], i == self.section)
            if i == self.section:
                pygame.draw.line(surf, COLORS['accent'], (r.left, r.bottom + u(2)), (r.right, r.bottom + u(2)), max(1, u(2)))
            tx = r.right + u(14)
        y += u(36)
        fields = self.fields()
        self.row = min(self.row, len(fields) - 1)
        for i, f in enumerate(fields):
            key, default, _, label, step, lo, hi, help_ = f
            val = cfg.values[key]
            sel = i == self.row
            if sel:
                pygame.draw.rect(surf, COLORS['panel2'], (panel.x + u(8), y - u(3), panel.w - u(16), u(30)), border_radius=u(4))
            if step == 'button':
                shown = self.app.design_button_label(key)
            elif step is None:
                shown = 'ON' if val else 'OFF'
            elif isinstance(val, float):
                shown = ('%.2f' % val).rstrip('0').rstrip('.')
            else:
                shown = str(val)
            changed = val != default
            r = gfx.blit_text(surf, label, 17, (x, y), COLORS['text'] if sel else COLORS['dim'], sel)
            if cfg.is_personal(key):
                gfx.blit_text(surf, 'player', 11, (r.right + u(8), y + u(5)), (255, 140, 220), True)
            if step == 'button':
                gfx.blit_text(surf, ('[ %s ]' if sel else '%s') % shown, 16, (panel.right - u(18), y), COLORS['cyan'], sel, 'topright', max_w=u(300))
            elif step is None:
                box = pygame.Rect(panel.right - u(40), y + u(1), u(22), u(22))
                pygame.draw.rect(surf, COLORS['accent'] if sel else COLORS['line'], box, max(1, u(2)), border_radius=u(4))
                if val:
                    pygame.draw.lines(surf, COLORS['great'], False, [(box.x + u(5), box.centery), (box.x + u(9), box.bottom - u(6)),
                                                                     (box.right - u(4), box.y + u(5))], max(2, u(3)))
            else:
                arrows = '<  %s  >' % shown if sel else shown
                gfx.blit_text(surf, arrows, 17, (panel.right - u(18), y), COLORS['accent'] if changed else COLORS['text'], True, 'topright')
            y += u(32)
        help_ = fields[self.row][7]
        y = panel.bottom - u(118)
        pygame.draw.line(surf, COLORS['line'], (x, y), (panel.right - u(18), y))
        y += u(8)
        for line in _wrap(help_ or ' ', 60)[:2]:
            gfx.blit_text(surf, line, 15, (x, y), COLORS['text'])
            y += u(20)
        y = panel.bottom - u(56)
        gfx.blit_text(surf, 'Up/Down pick   Left/Right change (Shift x10)   Tab section', 14, (x, y), COLORS['dim'])
        gfx.blit_text(surf, 'Backspace reset   F1/Esc close   F2 leave a feedback note', 14, (x, y + u(20)), COLORS['dim'])


def _wrap(s, n):
    words, lines, cur = s.split(), [], ''
    for w in words:
        if len(cur) + len(w) + 1 > n:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + ' ' + w).strip()
    if cur:
        lines.append(cur)
    return lines


class NoteBox:
    """F2: type a comment. Saved with context to data/design-notes.jsonl."""

    def __init__(self, app):
        self.app = app
        self.open = False
        self.text = ''
        self.context = {}

    def start(self, context):
        self.open = True
        self.text = ''
        self.context = context
        pygame.key.start_text_input()

    def key(self, ev):
        if ev.type == pygame.TEXTINPUT:
            self.text += ev.text
            return True
        if ev.type != pygame.KEYDOWN:
            return False
        if ev.key == pygame.K_ESCAPE:
            self.close()
        elif ev.key == pygame.K_RETURN:
            if self.text.strip():
                os.makedirs(settings.DATA, exist_ok=True)
                entry = dict(self.context, time=time.strftime('%Y-%m-%d %H:%M:%S'), note=self.text.strip())
                with open(NOTES, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + '\n')
                self.app.toast('Note saved to data/design-notes.jsonl')
            self.close()
        elif ev.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
        return True

    def close(self):
        self.open = False
        pygame.key.stop_text_input()

    def draw(self, surf):
        if not self.open:
            return
        r = pygame.Rect(u(100), gfx.H // 2 - u(70), gfx.W - u(200), u(140))
        bg = pygame.Surface(r.size, pygame.SRCALPHA)
        bg.fill((8, 10, 22, 240))
        surf.blit(bg, r)
        pygame.draw.rect(surf, COLORS['cyan'], r, max(1, u(2)), border_radius=u(6))
        where = ', '.join(str(v) for k, v in self.context.items() if k in ('screen', 'song', 'chart', 'song_time') and v != '')
        gfx.blit_text(surf, 'Feedback note  (%s)' % where, 16, (r.x + u(16), r.y + u(12)), COLORS['cyan'], True, max_w=r.w - u(32))
        shown = self.text[-90:] + ('|' if int(time.perf_counter() * 2) % 2 else ' ')
        gfx.blit_text(surf, shown, 22, (r.x + u(16), r.y + u(50)), COLORS['text'], max_w=r.w - u(32))
        gfx.blit_text(surf, 'Enter save   Esc cancel', 14, (r.x + u(16), r.bottom - u(28)), COLORS['dim'])
