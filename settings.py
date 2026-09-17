"""Tunable settings. Every field here shows up in Design Mode (F1) and is saved to data/settings.json.

The file is re-read whenever it changes on disk, so it can be edited by hand (or by Claude) while the game runs.
"""
import json
import os

import paths

DATA = paths.DATA
PATH = paths.SETTINGS_PATH

# (key, default, section, label, step, min, max, help)   step None = on/off, list = choices
FIELDS = [
    ('audio_offset_ms', 80, 'Timing', 'Judge offset (ms)', 5, -300, 300,
     'Positive = steps judged later. Use the value the results screen suggests. Does not move the arrows.'),
    ('visual_offset_ms', 20, 'Timing', 'Arrow timing (ms)', 5, -200, 200,
     'Arrows reach the receptors this many ms after the beat. Lower = earlier arrows. Does not change judging.'),
    ('auto_sync', True, 'Timing', 'Auto-fix song sync', None, None, None,
     'Measures each song against its audio and shifts off-sync charts at play time. Simfiles are not edited.'),
    ('lead_in_s', 2.0, 'Timing', 'Lead-in before song (s)', 0.5, 0.0, 8.0, 'Silence before the music starts.'),

    ('scroll_mode', 'target', 'Speed', 'Speed mode', ['target', 'multiplier', 'constant'],
     None, None, 'target: same scroll speed on every song (multiplier worked out from its main BPM). multiplier: fixed xN, speed varies by BPM.'),
    ('target_speed', 225, 'Speed', 'Read speed (all songs)', 25, 100, 1000,
     'One number for every song: main BPM x multiplier. 1x on your library ranges 100-204.'),
    ('multiplier', 1.0, 'Speed', 'Fixed multiplier', 0.25, 0.25, 8.0, 'Used by multiplier mode. OutFox with no speed mod = 1.0.'),
    ('mult_step', 0.05, 'Speed', 'Multiplier rounding', [0.05, 0.25, 0.5], None, None,
     '0.05 keeps every song within 2% of the read speed. Arcade DDR uses 0.25 (within about 7%).'),

    ('win_marvelous_ms', 16.7, 'Judging', 'Marvelous window (+/- ms)', 0.5, 5, 60, 'Arcade DDR: about 1 frame (16.7).'),
    ('win_perfect_ms', 33.3, 'Judging', 'Perfect window (+/- ms)', 0.5, 10, 90, 'Arcade DDR: about 2 frames (33.3).'),
    ('win_great_ms', 91.7, 'Judging', 'Great window (+/- ms)', 0.5, 20, 150, 'Arcade DDR: about 5.5 frames (91.7).'),
    ('win_good_ms', 141.7, 'Judging', 'Good window (+/- ms)', 0.5, 30, 250, 'Arcade DDR: about 8.5 frames (141.7).'),
    ('hold_grace_ms', 350, 'Judging', 'Freeze release grace (ms)', 10, 0, 600,
     'How long a foot may come off a freeze arrow before it is N.G. Each re-step resets it.'),
    ('autoplay', False, 'Judging', 'Autoplay (demo, not scored)', None, None, None, 'Watch a chart play itself.'),
    ('input_debounce_ms', 30, 'Judging', 'Pad flicker filter (ms)', 5, 0, 100,
     'A panel that lets go and presses again within this time counts as still held.'),
    ('good_breaks_combo', True, 'Judging', 'Good breaks combo', None, None, None, 'Arcade: yes.'),
    ('jump_judge', 'worst', 'Judging', 'Jump judged by', ['worst', 'average', 'last'], None, None, ''),

    ('life_mode', 'fail at end', 'Life', 'Life gauge', ['fail at end', 'normal', 'no fail', 'life4', 'off'], None, None,
     'fail at end: only fails if the gauge is empty when the song ends (OutFox FailAtEnd). normal: fails the moment it empties. life4: 4 misses and out.'),
    ('life_miss', 8.0, 'Life', 'Life lost per miss (%)', 0.5, 0, 50, ''),
    ('life_gain', 1.0, 'Life', 'Life gained per Perfect+ (%)', 0.1, 0, 10, ''),

    ('arrow_size', 96, 'Look', 'Arrow size (px)', 4, 48, 160, ''),
    ('lane_gap', 6, 'Look', 'Gap between lanes (px)', 2, 0, 60, ''),
    ('receptor_y', 150, 'Look', 'Receptor height from top (px)', 10, 40, 700, ''),
    ('reverse', False, 'Look', 'Reverse scroll (arrows fall)', None, None, None, ''),
    ('field_x', 'center', 'Look', 'Playfield position', ['center', 'left', 'right'], None, None, ''),
    ('video_backgrounds', True, 'Look', 'Video backgrounds', None, None, None,
     'Play the song videos listed in its #BGCHANGES (uses ffmpeg). Off = still background image.'),
    ('bg_brightness', 35, 'Look', 'Background brightness (%)', 5, 0, 100, ''),
    ('note_colors', 'rhythm', 'Look', 'Arrow colours', ['rhythm', 'flat'], None, None, 'rhythm: red 4ths, blue 8ths, yellow 16ths, green others.'),
    ('show_early_late', True, 'Look', 'Show FAST/SLOW', None, None, None, ''),
    ('judge_y', 360, 'Look', 'Judgment text height (px)', 10, 100, 700, ''),
    ('show_fps', True, 'Look', 'Show FPS', None, None, None, ''),

    ('measure_lines', True, 'Training', 'Measure lines', None, None, None,
     'Lines scroll with the arrows: bright at each measure (with its number), faint on each beat.'),
    ('eighth_lines', False, 'Training', '8th-note lines', None, None, None,
     'Extra dotted lines halfway between beats, to tell 8ths (blue) from 4ths (red).'),
    ('timing_meter', True, 'Training', 'Step timing meter', None, None, None,
     'Bar at the bottom of the screen: a tick for each recent step, left = early, right = late.'),
    ('beat_flash', True, 'Training', 'Receptors flash on the beat', None, None, None,
     'Like the DDR step zone: the receptors blink on every beat, brighter at each measure.'),
    ('arrow_flash', True, 'Training', 'Arrows flash on the beat', None, None, None,
     'Arrows brighten for a moment on every beat, like arcade DDR note skins.'),
    ('approach_glow', True, 'Training', 'Glow when an arrow is about to hit', None, None, None,
     'A receptor starts glowing one beat before its next arrow arrives and peaks when it should be stepped.'),
    ('waveform', True, 'Training', 'Waveform strip (BPM, pitch, key)', None, None, None,
     'Song waveform scrolling up the left side with the arrows. Width = loudness, colour = pitch; shows BPM, pitch and key.'),
    ('coach', 'off', 'Coach', 'AI step coach', ['off', 'claude-code', 'claude', 'ollama'], None, None,
     'Optional. claude-code: your Claude plan through Claude Code. claude: API key. ollama: local model. Sends only run numbers.'),
    ('coach_claude_model', 'claude-opus-5', 'Coach', 'Claude model', ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'], None, None,
     'Opus 5 gives the most careful advice; Sonnet 5 and Haiku 4.5 are cheaper and faster.'),
    ('coach_auto', False, 'Coach', 'Ask the coach after every song', None, None, None,
     'Off: step Up (or press C) on the results screen to ask.'),
    ('lab_ai', 'auto', 'Lab', 'Lab mode assistant', ['auto', 'claude-code', 'claude', 'ollama', 'built-in'], None, None,
     'auto: Claude Code (your Claude plan) if installed, else the Claude API if a key is set, else Ollama, else built-in.'),
    ('claude_code_model', 'claude-sonnet-5', 'Lab', 'Claude Code model', ['claude-sonnet-5', 'claude-opus-5', 'claude-haiku-4-5'], None, None,
     'Lab mode and the coach through Claude Code. Counts toward your Claude plan usage; no API credits.'),
    ('lab_claude_model', 'claude-opus-5', 'Lab', 'Lab Claude API model', ['claude-opus-5', 'claude-sonnet-5', 'claude-haiku-4-5'], None, None,
     'Opus 5 edits charts most carefully; Sonnet 5 and Haiku 4.5 answer faster and cost less.'),
    ('lab_clap', True, 'Lab', 'Clap on arrows while previewing', None, None, None, 'Assist tick in the Lab editor (K toggles).'),
    ('render_height', 1080, 'Display', 'Render resolution (restart)', [720, 900, 1080, 1440], None, None,
     'Height of the drawing surface; lower = more FPS. Scaled to your screen.'),
    ('fullscreen', True, 'Display', 'Fullscreen (restart)', None, None, None, 'Scaled to fill the screen.'),
    ('vsync', True, 'Display', 'VSync (restart)', None, None, None, 'Off = uncapped frames with more precise input polling, may tear.'),
    ('fps_cap', 0, 'Display', 'FPS cap when VSync off (0 = none)', 30, 0, 1000, ''),

    ('wheel_repeat_ms', 110, 'Menu', 'Wheel auto-scroll speed (ms)', 10, 30, 400, 'Hold Left/Right to keep scrolling.'),
    ('wheel_delay_ms', 300, 'Menu', 'Wheel hold delay (ms)', 10, 100, 1000, ''),
    ('preview_delay_ms', 350, 'Menu', 'Music preview delay (ms)', 50, 0, 2000, ''),
    ('preview_volume', 70, 'Menu', 'Preview volume (%)', 5, 0, 100, ''),
    ('game_volume', 100, 'Menu', 'Song volume (%)', 5, 0, 100, ''),
    ('confirm_twice', False, 'Menu', 'Press Start twice to play', None, None, None, 'Arcade asks you to confirm.'),

    ('pad_setup', None, 'Controls', 'Dance pad', 'button', None, None,
     'Enter: step on each panel so the game learns your pad. Pads set up in OutFox, StepManiaX stages and most USB mats work without this.'),
    ('outfox_import', None, 'Songs', 'OutFox profiles and scores', 'button', None, None,
     'Enter: import every OutFox local profile (plays, best scores, favorites). Also happens by itself after OutFox has been played.'),
    ('rescan', None, 'Songs', 'Song folders', 'button', None, None,
     'Enter: look again for songs (Songs plus AdditionalSongFolders from OutFox). Lab mode saves are picked up by themselves.'),
]

# machine settings that are not simple fields: kept in settings.json, edited by the game or by hand
EXTRA_DEFAULTS = {'outfox_dir': '', 'pad_bindings': {}}

# settings that belong to a player rather than the machine (saved in the active profile).
# Timing offsets are deliberately NOT here: they correct the machine's audio/video/pad delay, so they
# are the same for everyone. One player's habits shouldn't move the clock for the whole program.
PERSONAL = ('scroll_mode', 'target_speed', 'multiplier', 'mult_step',
            'life_mode', 'measure_lines', 'eighth_lines', 'timing_meter', 'beat_flash', 'arrow_flash', 'approach_glow', 'waveform', 'coach_auto',
            'show_early_late', 'note_colors',
            'reverse', 'arrow_size', 'receptor_y', 'bg_brightness', 'lane_gap', 'field_x', 'judge_y')

SECTIONS = []
for _f in FIELDS:
    if _f[2] not in SECTIONS:
        SECTIONS.append(_f[2])
_STEP = {_f[0]: _f[4] for _f in FIELDS}


class Settings:
    def __init__(self):
        self.values = {f[0]: f[1] for f in FIELDS}
        self.machine = dict(self.values)     # what data/settings.json holds
        self.extras = dict(EXTRA_DEFAULTS)    # also in settings.json, not shown as fields
        self.profile = None                   # personal keys come from the active profile
        self.mtime = 0
        self.load()

    def extra(self, key, default=None):
        return self.extras.get(key, default)

    def set_extra(self, key, value):
        self.extras[key] = value
        self.save()

    def use_profile(self, profile):
        self.profile = profile
        self._merge()

    def _merge(self):
        self.values.update(self.machine)
        if self.profile is not None:
            for k, v in self.profile.data.get('settings', {}).items():
                if k in PERSONAL and k in self.values:
                    self.values[k] = v

    def is_personal(self, key):
        return self.profile is not None and key in PERSONAL

    def __getattr__(self, name):
        try:
            return self.__dict__['values'][name]
        except KeyError:
            raise AttributeError(name)

    def load(self):
        try:
            with open(PATH, encoding='utf-8') as f:
                data = json.load(f)
            for k, v in data.items():
                if k in self.machine:
                    self.machine[k] = v
                elif k in EXTRA_DEFAULTS:
                    self.extras[k] = v
            if 'pad_bindings' not in data and 'pad_left' in data:
                import pads                                   # settings from before the pad setup screen
                legacy = pads.legacy_from_settings(data)
                if legacy:
                    self.extras['pad_bindings'] = {'*': legacy}
            self._merge()
            self.mtime = os.path.getmtime(PATH)
        except (FileNotFoundError, ValueError):
            pass

    def poll(self):
        """Reload if the file changed on disk. Returns True when it did."""
        try:
            m = os.path.getmtime(PATH)
        except OSError:
            return False
        if m != self.mtime:
            self.load()
            return True
        return False

    def save(self):
        os.makedirs(DATA, exist_ok=True)
        tmp = PATH + '.tmp'
        out = {k: v for k, v in self.machine.items() if _STEP.get(k) != 'button'}
        out.update(self.extras)
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(out, f, indent=2)
        os.replace(tmp, PATH)
        self.mtime = os.path.getmtime(PATH)

    def set(self, key, value):
        self.values[key] = value
        if self.is_personal(key):
            self.profile.data.setdefault('settings', {})[key] = value
            self.profile.save()
        else:
            self.machine[key] = value
            self.save()

    def adjust(self, field, direction, big=False):
        key, default, _, _, step, lo, hi, _ = field
        cur = self.values[key]
        if step == 'button':
            return
        if step is None:
            self.set(key, not cur)
        elif isinstance(step, list):
            i = step.index(cur) if cur in step else 0
            self.set(key, step[(i + direction) % len(step)])
        else:
            val = cur + direction * step * (10 if big else 1)
            val = max(lo, min(hi, val))
            if isinstance(default, int) and isinstance(step, int):
                val = int(val)
            else:
                val = round(val, 3)
            self.set(key, val)

    def reset(self, field):
        self.set(field[0], field[1])
