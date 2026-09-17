# Dance pads and controllers

Rave Laboratory talks to any pad the operating system shows as a joystick / game controller, whatever it sends:
**buttons**, a **d-pad (hat)**, or **axes**. Keyboard pads (mats that type arrow keys) work as a keyboard.

## How a pad gets its mapping

When a pad is connected (before or after the game starts), the game tries, in order:

1. **Bindings saved in the game** for this exact pad (by its GUID and name), from Set up pad.
2. **OutFox's `Save/Keymaps.ini`**, if OutFox has seen this pad (it is listed in `LastSeenInputDevices` in
   `Preferences.ini`). A pad that works in OutFox works here with no setup.
3. **Known pads by name**: StepManiaX stages (3x3 grid, centre = Start, bottom-left = Back), L-TEK pads, USB
   "Dance Pad"/"DDR"/RedOctane/Cobalt Flux style mats and PlayStation adapters (arrows on the d-pad, Start/Select),
   Xbox mats and controllers (d-pad, Start/Back), Sony controllers.
4. **A guess from the hardware**: a hat becomes the arrows (plus the first two axes, if any); with no hat, two axes;
   a four-button device is read as Up, Left, Right, Down.
5. Otherwise **Set up pad** opens by itself.

F1 > Controls shows every connected pad and where its mapping came from, and pops up a message naming each
button / d-pad direction / axis as you press it, which helps when something is odd.

## Set up pad

Who's playing? > **Set up pad** (or press P there, or F1 > Controls > Enter). Step on UP, DOWN, LEFT, RIGHT when
asked; then, optionally, press START and BACK (Enter or Space skips them). The pad you stepped on first is the one
being set up, so it also works with several pads plugged in. Backspace redoes the previous panel, Esc cancels.
The result is saved to `data/settings.json` under `pad_bindings` and used from then on.

## Playing without Start or Back buttons

Every 4-panel pad can drive all the menus with the arrows alone:

- **Left + Right together** = Start (hold it on a song = favorite)
- **Up + Down together** = Back
- **Stand on Up + Down for 2 seconds during a song** = quit the song

The first arrow of a pair moves the cursor for a moment; the chord undoes that move, so nothing is lost.

## Pad flicker filter

Sensor pads (StepManiaX and similar) can release and re-press for 10 to 120 ms while you stand on a freeze arrow.
F1 > Judging > **Pad flicker filter** (30 ms by default) treats a release-and-press within that time as still held.
Raise it if freezes drop while your foot never left; set it to 0 for a pad that never flickers.

## Binding codes

`pad_bindings` in `data/settings.json` looks like this:

```json
"pad_bindings": {
  "03004517...|StepManiaX": {"left": ["b3"], "down": ["b7"], "up": ["b1"], "right": ["b5"], "start": ["b4"], "back": ["b6"]}
}
```

- `bN` = button N (numbered from 0, so OutFox's "Button 4" is `b3`)
- `h0u` `h0d` `h0l` `h0r` = hat (d-pad) 0 up / down / left / right
- `aN-` / `aN+` = axis N pushed past half way in the negative / positive direction

An entry keyed `"*"` applies to any pad that has no entry of its own. Several codes per action are fine.

## Keyboard

Arrow keys, numpad 4 / 2 / 8 / 6, Enter, Esc / Backspace always work, so a keyboard-type mat needs nothing.
In Lab mode's editor the keyboard is the editor's (1-4 place arrows, and so on); pads still control the menus and
playtests there.

## Two players?

Rave Laboratory is a single-player game: every connected pad drives player 1. Two pads can both be plugged in
(for example a StepManiaX stage and a soft mat) and each keeps its own mapping.
