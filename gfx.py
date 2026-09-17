"""Drawing helpers: fonts, cached text, pre-rendered arrow sprites, background image loader.

All layout numbers in the game are written for a 1280x720 screen and multiplied by U.
"""
import math
import queue
import sys
import threading

import pygame

W, H, U = 1280, 720, 1.0

COLORS = {
    'bg': (10, 12, 24), 'panel': (22, 26, 48), 'panel2': (34, 40, 72), 'line': (70, 80, 130),
    'text': (235, 238, 255), 'dim': (150, 158, 190), 'accent': (255, 196, 40), 'cyan': (70, 220, 255),
    'marvelous': (250, 250, 255), 'perfect': (255, 220, 60), 'great': (90, 230, 110), 'good': (80, 170, 255),
    'miss': (255, 70, 90), 'ok': (255, 230, 120), 'ng': (255, 70, 90),
    'Beginner': (90, 220, 255), 'Easy': (255, 200, 40), 'Medium': (255, 80, 110), 'Hard': (90, 230, 110),
    'Challenge': (200, 110, 255), 'Edit': (180, 180, 190),
}
QUANT_COLORS = {4: (235, 50, 70), 8: (50, 110, 245), 16: (250, 200, 30)}
OTHER_QUANT = (40, 200, 120)
FLAT_COLOR = (235, 50, 70)
ROTATION = [0, 90, -90, 180]   # base sprite points left: L, D, U, R


def setup(width, height):
    global W, H, U
    W, H, U = width, height, height / 720.0


def u(v):
    return int(round(v * U))


# ---------------------------------------------------------------- text

_fonts = {}
_text_cache = {}
if sys.platform == 'win32':
    _FACES = 'segoeui,arial,dejavusans'
    _CJK_FACES = 'yugothicui,meiryo,malgungothic,msgothic,segoeui'
elif sys.platform == 'darwin':
    _FACES = 'helveticaneue,helvetica,arial,dejavusans'
    _CJK_FACES = 'hiraginosans,pingfangsc,applesdgothicneo,helveticaneue'
else:
    _FACES = 'dejavusans,notosans,liberationsans,ubuntu,cantarell,arial'
    _CJK_FACES = 'notosanscjkjp,notosanscjk,notosanscjksc,droidsansfallback,wenquanyizenhei,dejavusans'


def font(size, bold=False, cjk=False):
    key = (size, bold, cjk)
    if key not in _fonts:
        _fonts[key] = pygame.font.SysFont(_CJK_FACES if cjk else _FACES, max(6, u(size)), bold=bold)
    return _fonts[key]


def text(s, size, color=None, bold=False):
    s = str(s)
    color = color or COLORS['text']
    key = (s, size, color, bold)
    surf = _text_cache.get(key)
    if surf is None:
        if len(_text_cache) > 3000:
            _text_cache.clear()
        cjk = any(ord(ch) > 0x2E7F for ch in s)
        surf = font(size, bold, cjk).render(s, True, color)
        _text_cache[key] = surf
    return surf


def blit_text(dst, s, size, pos, color=None, bold=False, anchor='topleft', max_w=None):
    surf = text(s, size, color, bold)
    if max_w and surf.get_width() > max_w:
        surf = pygame.transform.smoothscale(surf, (int(max_w), surf.get_height()))
    r = surf.get_rect(**{anchor: pos})
    dst.blit(surf, r)
    return r


def outlined(s, size, color, outline=(0, 0, 0), bold=True, px=2):
    key = ('outlined', s, size, color, outline, px)
    surf = _text_cache.get(key)
    if surf is None:
        inner = font(size, bold).render(s, True, color)
        edge = font(size, bold).render(s, True, outline)
        p = u(px)
        surf = pygame.Surface((inner.get_width() + 2 * p, inner.get_height() + 2 * p), pygame.SRCALPHA)
        for dx in (-p, 0, p):
            for dy in (-p, 0, p):
                if dx or dy:
                    surf.blit(edge, (p + dx, p + dy))
        surf.blit(inner, (p, p))
        _text_cache[key] = surf
    return surf


# ---------------------------------------------------------------- arrows

_arrow_cache = {}
_ARROW_POLY = [(0.04, 0.50), (0.48, 0.06), (0.68, 0.06), (0.40, 0.34), (0.96, 0.34),
               (0.96, 0.66), (0.40, 0.66), (0.68, 0.94), (0.48, 0.94)]


def _poly(size, inset=0.0, pad=0.0):
    c = 0.5
    pts = []
    for x, y in _ARROW_POLY:
        x = c + (x - c) * (1 - inset)
        y = c + (y - c) * (1 - inset)
        pts.append((pad + x * size, pad + y * size))
    return pts


def _lighter(c, f):
    return tuple(min(255, int(v + (255 - v) * f)) for v in c)


def _darker(c, f):
    return tuple(int(v * (1 - f)) for v in c)


def arrow(size, col, color, style='note'):
    """style: note, receptor, receptor_lit, glow."""
    key = (size, col, color, style)
    surf = _arrow_cache.get(key)
    if surf is not None:
        return surf
    ss = 3
    big = size * ss
    base = pygame.Surface((big, big), pygame.SRCALPHA)
    if style == 'note':
        pygame.draw.polygon(base, (15, 15, 20), _poly(big, 0.0))
        pygame.draw.polygon(base, _darker(color, 0.25), _poly(big, 0.12))
        pygame.draw.polygon(base, color, _poly(big, 0.22))
        pygame.draw.polygon(base, _lighter(color, 0.55), _poly(big, 0.52))
    elif style in ('receptor', 'receptor_lit'):
        lit = style == 'receptor_lit'
        pygame.draw.polygon(base, (230, 235, 255) if lit else (150, 160, 190), _poly(big, 0.0))
        pygame.draw.polygon(base, (120, 140, 200) if lit else (25, 28, 45), _poly(big, 0.14))
        pygame.draw.polygon(base, (200, 215, 255) if lit else (55, 62, 95), _poly(big, 0.34))
    elif style == 'glow':
        for i in range(10, 0, -1):
            a = int(18 + 14 * (10 - i))
            pygame.draw.polygon(base, (255, 255, 255, min(255, a)), _poly(big, -0.05 * i + 0.3))
    surf = pygame.transform.smoothscale(base, (size, size))
    surf = pygame.transform.rotate(surf, ROTATION[col])
    _arrow_cache[key] = surf
    return surf


_alpha_cache = {}


def faded(surf, level, levels=8):
    """A cached copy of surf at alpha level/levels (0 = invisible)."""
    level = max(0, min(levels, int(round(level * levels))))
    key = (id(surf), level)
    out = _alpha_cache.get(key)
    if out is None:
        if len(_alpha_cache) > 400:
            _alpha_cache.clear()
        out = surf.copy()
        out.set_alpha(int(255 * level / levels))
        _alpha_cache[key] = (out, surf)
        return out
    return out[0]


def lighter(color, f=0.45):
    return _lighter(color, f)


def quant_color(q, mode):
    if mode == 'flat':
        return FLAT_COLOR
    return QUANT_COLORS.get(q, OTHER_QUANT)


def mine(size):
    key = ('mine', size)
    if key not in _arrow_cache:
        s = pygame.Surface((size, size), pygame.SRCALPHA)
        c = size // 2
        pygame.draw.circle(s, (20, 20, 25), (c, c), int(size * 0.36))
        pygame.draw.circle(s, (240, 60, 70), (c, c), int(size * 0.30))
        pygame.draw.circle(s, (255, 255, 255), (c, c), int(size * 0.14))
        for i in range(8):
            a = i * math.pi / 4
            pygame.draw.line(s, (255, 230, 120), (c + math.cos(a) * size * 0.2, c + math.sin(a) * size * 0.2),
                             (c + math.cos(a) * size * 0.46, c + math.sin(a) * size * 0.46), max(2, size // 20))
        _arrow_cache[key] = s
    return _arrow_cache[key]


def clear_sprite_cache():
    _arrow_cache.clear()


# ---------------------------------------------------------------- images (loaded off the main thread)

class Images:
    def __init__(self):
        self.ready = {}
        self.pending = set()
        self.q = queue.Queue()
        self.done = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        while True:
            path, size, mode = self.q.get()
            try:
                img = pygame.image.load(path)
                if img.get_bitsize() not in (24, 32):
                    rgba = pygame.Surface(img.get_size(), pygame.SRCALPHA)
                    rgba.blit(img, (0, 0))
                    img = rgba
                if size:
                    iw, ih = img.get_size()
                    if mode == 'cover':
                        f = max(size[0] / iw, size[1] / ih)
                    else:
                        f = min(size[0] / iw, size[1] / ih)
                    img = pygame.transform.smoothscale(img, (max(1, int(iw * f)), max(1, int(ih * f))))
                self.done.put(((path, size, mode), img))
            except Exception:
                self.done.put(((path, size, mode), False))

    def get(self, path, size=None, mode='fit'):
        """Return a Surface, or None while loading / when missing."""
        if not path:
            return None
        key = (path, size, mode)
        while not self.done.empty():
            k, img = self.done.get()
            self.pending.discard(k)
            if img is not False:
                img = img.convert_alpha() if img.get_alpha() is not None or img.get_bitsize() == 32 else img.convert()
            self.ready[k] = img
            if len(self.ready) > 120:
                for old in list(self.ready)[:40]:
                    del self.ready[old]
        if key in self.ready:
            return self.ready[key] or None
        if key not in self.pending:
            self.pending.add(key)
            self.q.put(key)
        return None
