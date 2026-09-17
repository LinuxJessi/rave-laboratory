"""Dance pads and controllers: turn whatever a pad sends (buttons, a d-pad hat, or axes) into
left / down / up / right / start / back.

A pad is found in this order:
  1. bindings saved for this pad in data/settings.json ("pad_bindings", keyed by the pad's GUID or name),
     usually made with the in-game setup (Who's playing? > Set up pad, or F1 > Controls)
  2. OutFox's own Save/Keymaps.ini (the first joystick gets OutFox's Joy1 mapping, so a pad that works in
     OutFox works here with no setup)
  3. a table of pads we know by name (StepManiaX, ...)
  4. a guess from what the pad has: a d-pad hat or two axes become the four arrows

Binding codes: "b3" = button 3, "h0u" = hat 0 up (u/d/l/r), "a1-" / "a1+" = axis 1 pushed past half.
Any pad can also play with only its four arrows: Left+Right together = Start, Up+Down together = Back.
"""
import re

import pygame

import paths

ACTIONS = ('left', 'down', 'up', 'right', 'start', 'back')
ARROWS = ACTIONS[:4]
AXIS_ON, AXIS_OFF = 0.5, 0.3           # hysteresis for analogue axes
_HAT = {'u': (1, 1), 'd': (1, -1), 'l': (0, -1), 'r': (0, 1)}

# name fragment (lower case) -> bindings. Button numbers are 0-based, as pygame reports them.
KNOWN = [
    # StepManiaX stage in gamepad mode: 3x3 grid, button = row * 3 + column (0 = top-left, 4 = centre)
    ('stepmaniax', {'up': ['b1'], 'left': ['b3'], 'start': ['b4'], 'right': ['b5'], 'back': ['b6'], 'down': ['b7']}),
    ('smx', {'up': ['b1'], 'left': ['b3'], 'start': ['b4'], 'right': ['b5'], 'back': ['b6'], 'down': ['b7']}),
    # Konami / RedOctane / Cobalt Flux style PlayStation mats through a USB adapter: arrows on the d-pad, Start/Select buttons
    ('dance pad', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('dancepad', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('dance mat', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('ddr', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('cobalt', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('redoctane', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    # L-TEK pads in their default (joystick) mode
    ('ltek', {'up': ['b2'], 'down': ['b1'], 'left': ['b3'], 'right': ['b0'], 'start': ['b9'], 'back': ['b8']}),
    ('l-tek', {'up': ['b2'], 'down': ['b1'], 'left': ['b3'], 'right': ['b0'], 'start': ['b9'], 'back': ['b8']}),
    # Xbox 360 / Xbox One dance mats show up as a normal controller: arrows on the d-pad
    ('xbox', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b7'], 'back': ['b6']}),
    ('x-box', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b7'], 'back': ['b6']}),
    ('xinput', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b7'], 'back': ['b6']}),
    # Sony pads (PS3/PS4/PS5 mats and converters): d-pad arrows, Options/Share
    ('wireless controller', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('playstation', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('ps3', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('ps4', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('dualshock', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
    ('dualsense', {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r'], 'start': ['b9'], 'back': ['b8']}),
]


def device_key(joy):
    """A stable id for saving bindings: the SDL GUID when it isn't all zeros, else the name."""
    try:
        guid = joy.get_guid()
    except Exception:
        guid = ''
    if guid and guid.strip('0'):
        return '%s|%s' % (guid, joy.get_name())
    return joy.get_name()


def known_bindings(name):
    """Every table entry whose name fragment appears in the pad's name, most specific first."""
    low = (name or '').lower()
    hits = [(frag, {a: list(v) for a, v in binds.items()}) for frag, binds in KNOWN if frag in low]
    hits.sort(key=lambda h: -len(h[0]))
    return hits


def guessed_bindings(joy):
    """From what the pad physically has. Returns None when there is nothing sensible to guess."""
    try:
        hats, axes, buttons = joy.get_numhats(), joy.get_numaxes(), joy.get_numbuttons()
    except Exception:
        return None
    if hats >= 1:
        b = {'up': ['h0u'], 'down': ['h0d'], 'left': ['h0l'], 'right': ['h0r']}
        if axes >= 2:      # many adapters send both; accept either
            b['up'].append('a1-'); b['down'].append('a1+'); b['left'].append('a0-'); b['right'].append('a0+')
        return b
    if axes >= 2:
        return {'up': ['a1-'], 'down': ['a1+'], 'left': ['a0-'], 'right': ['a0+']}
    if buttons == 4:       # four-panel pads that number their panels in reading order
        return {'up': ['b0'], 'left': ['b1'], 'right': ['b2'], 'down': ['b3']}
    return None


def outfox_bindings(player=1):
    """Joy<N> bindings from OutFox's Save/Keymaps.ini for player 1, as our codes. None if not set up."""
    try:
        text = open(paths.KEYMAPS, encoding='utf-8', errors='replace').read()
    except OSError:
        return None
    out = {}
    names = {'Left': 'left', 'Down': 'down', 'Up': 'up', 'Right': 'right', 'Start': 'start', 'Back': 'back'}
    for m in re.finditer(r'^%d_(\w+)=(.*)$' % player, text, re.M):
        action = names.get(m.group(1))
        if not action:
            continue
        for part in m.group(2).split(':'):
            part = part.strip()
            j = re.match(r'Joy(\d+)_(.*)', part)
            if not j:
                continue
            code = _code_from_outfox(j.group(2).strip())
            if code:
                out.setdefault(action, []).append(code)
    return out if any(a in out for a in ARROWS) else None


def outfox_knows(name):
    """OutFox's Keymaps.ini was made with this pad (it is in Preferences.ini LastSeenInputDevices)."""
    try:
        text = open(paths.PREFERENCES, encoding='utf-8', errors='replace').read()
    except OSError:
        return False
    m = re.search(r'^LastSeenInputDevices=(.*)$', text, re.M)
    if not m:
        return False
    low = (name or '').lower()
    return any(d.strip() and (d.strip().lower() in low or low in d.strip().lower()) for d in m.group(1).split('|'))


def _code_from_outfox(name):
    m = re.match(r'Button (\d+)$', name)
    if m:
        return 'b%d' % (int(m.group(1)) - 1)
    m = re.match(r'Hat (Up|Down|Left|Right)$', name)
    if m:
        return 'h0' + m.group(1)[0].lower()
    axes = {'Left': 'a0-', 'Right': 'a0+', 'Up': 'a1-', 'Down': 'a1+', 'Z-Up': 'a2-', 'Z-Down': 'a2+',
            'Z-Rot-Up': 'a3-', 'Z-Rot-Down': 'a3+', 'Hat Left': 'h0l', 'Hat Right': 'h0r', 'Hat Up': 'h0u', 'Hat Down': 'h0d'}
    return axes.get(name)


def describe_code(code):
    if code.startswith('b'):
        return 'button %s' % code[1:]
    if code.startswith('h'):
        return 'd-pad %s' % {'u': 'up', 'd': 'down', 'l': 'left', 'r': 'right'}[code[-1]]
    if code.startswith('a'):
        return 'axis %s %s' % (code[1:-1], '-' if code.endswith('-') else '+')
    return code


class Pad:
    def __init__(self, joy, bindings, source):
        self.joy = joy
        self.name = joy.get_name()
        self.key = device_key(joy)
        self.bindings = bindings or {}
        self.source = source                    # 'saved', 'outfox', 'known', 'guess', 'none'
        self.hat = {}                           # hat index -> (x, y)
        self.axis = {}                          # (axis, sign) -> pressed
        self.lookup = {}
        for action, codes in self.bindings.items():
            for c in codes:
                self.lookup.setdefault(c, set()).add(action)

    @property
    def ready(self):
        return all(self.bindings.get(a) for a in ARROWS)

    @property
    def has_start(self):
        return bool(self.bindings.get('start'))

    def summary(self):
        if not self.ready:
            return '%s: not set up' % self.name
        src = {'saved': 'your setup', 'outfox': "OutFox's keymap", 'known': 'known pad', 'guess': 'auto-detected'}.get(self.source, self.source)
        return '%s (%s)' % (self.name, src)


class PadManager:
    """Owns every connected joystick and turns its events into game actions."""

    def __init__(self, cfg):
        self.cfg = cfg
        self.pads = {}                          # instance id -> Pad
        self.new_unmapped = []                  # pads that need the setup screen

    # ---------------------------------------------------------- devices

    def add(self, joy):
        bindings, source = self.resolve(joy)
        pad = Pad(joy, bindings, source)
        self.pads[joy.get_instance_id()] = pad
        if not pad.ready:
            self.new_unmapped.append(pad)
        return pad

    def remove(self, instance_id):
        pad = self.pads.pop(instance_id, None)
        if pad in self.new_unmapped:
            self.new_unmapped.remove(pad)
        return pad

    def resolve(self, joy):
        saved = self.cfg.extra('pad_bindings', {})
        key = device_key(joy)
        if key in saved and any(saved[key].get(a) for a in ARROWS):
            return saved[key], 'saved'
        legacy = saved.get('*')
        if legacy and any(legacy.get(a) for a in ARROWS) and joy.get_numbuttons() > max(_button_numbers(legacy), default=-1):
            return legacy, 'saved'
        if outfox_knows(joy.get_name()):
            of = outfox_bindings()
            if of and self._fits(joy, of):
                return of, 'outfox'
        for _, known in known_bindings(joy.get_name()):
            if self._fits(joy, known):
                return known, 'known'
        guess = guessed_bindings(joy)
        if guess:
            return guess, 'guess'
        return {}, 'none'

    @staticmethod
    def _fits(joy, bindings):
        """The bindings only mention buttons/hats/axes the pad actually has."""
        try:
            nb, nh, na = joy.get_numbuttons(), joy.get_numhats(), joy.get_numaxes()
        except Exception:
            return True
        for codes in bindings.values():
            for c in codes:
                if c.startswith('b') and int(c[1:]) >= nb:
                    return False
                if c.startswith('h') and int(c[1:-1]) >= nh:
                    return False
                if c.startswith('a') and int(c[1:-1]) >= na:
                    return False
        return True

    def save_bindings(self, pad, bindings):
        saved = dict(self.cfg.extra('pad_bindings', {}))
        saved[pad.key] = {a: list(v) for a, v in bindings.items() if v}
        self.cfg.set_extra('pad_bindings', saved)
        pad.bindings = saved[pad.key]
        pad.source = 'saved'
        pad.lookup = {}
        for action, codes in pad.bindings.items():
            for c in codes:
                pad.lookup.setdefault(c, set()).add(action)
        if pad in self.new_unmapped:
            self.new_unmapped.remove(pad)

    def forget(self, pad):
        saved = dict(self.cfg.extra('pad_bindings', {}))
        saved.pop(pad.key, None)
        self.cfg.set_extra('pad_bindings', saved)
        bindings, source = self.resolve(pad.joy)
        self.pads[pad.joy.get_instance_id()] = Pad(pad.joy, bindings, source)

    def any_start(self):
        return any(p.has_start for p in self.pads.values())

    # ---------------------------------------------------------- events

    def raw_events(self, ev):
        """[(pad, code, down)] for a joystick event, before any binding is applied."""
        pad = self.pads.get(getattr(ev, 'instance_id', None))
        if pad is None:
            return []
        if ev.type == pygame.JOYBUTTONDOWN:
            return [(pad, 'b%d' % ev.button, True)]
        if ev.type == pygame.JOYBUTTONUP:
            return [(pad, 'b%d' % ev.button, False)]
        out = []
        if ev.type == pygame.JOYHATMOTION:
            old = pad.hat.get(ev.hat, (0, 0))
            new = tuple(ev.value)
            pad.hat[ev.hat] = new
            for d, (idx, want) in _HAT.items():
                was, now = old[idx] == want, new[idx] == want
                if was != now:
                    out.append((pad, 'h%d%s' % (ev.hat, d), now))
        elif ev.type == pygame.JOYAXISMOTION:
            for sign, v in (('-', -ev.value), ('+', ev.value)):
                k = (ev.axis, sign)
                was = pad.axis.get(k, False)
                now = v > AXIS_ON if not was else v > AXIS_OFF
                if now != was:
                    pad.axis[k] = now
                    out.append((pad, 'a%d%s' % (ev.axis, sign), now))
        return out

    def actions(self, ev):
        """[(action, down)] for a joystick event, using the pad's bindings."""
        out = []
        for pad, code, down in self.raw_events(ev):
            for action in pad.lookup.get(code, ()):
                out.append((action, down))
        return out


def _button_numbers(bindings):
    return [int(c[1:]) for codes in bindings.values() for c in codes if c.startswith('b')]


def legacy_from_settings(values):
    """The old pad_left..pad_back numbers from settings.json, as bindings for any pad ('*')."""
    keys = ('pad_left', 'pad_down', 'pad_up', 'pad_right', 'pad_start', 'pad_back')
    if not all(k in values for k in keys[:4]):
        return None
    out = {}
    for k in keys:
        v = values.get(k)
        if isinstance(v, int) and v >= 0:
            out[k[4:]] = ['b%d' % v]
    return out
