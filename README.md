# Rave Laboratory

A DDR-style dance game that plays the songs in your **Project OutFox** (or StepMania) `Songs` folder, with arcade
scoring, a quick pad-only menu, per-player profiles, and **Lab mode**: drop in any song or music video and chart it
with an AI assistant. Windows, macOS and Linux.

- Arcade DDR judging (Marvelous / Perfect / Great / Good / Miss with arcade timing windows) and the DDR A20 / World
  money score, grades AAA to D, full-combo lamps.
- One read speed for every song, freeze arrows, rolls, shock arrows, BPM changes, stops and warps.
- Reads `.ssc`, `.sm` and `.dwi`, video backgrounds, groove radar and Sensory ratings, favorites, most played, search.
- Imports your OutFox profiles (scores, play counts, favorites) and uses your OutFox pad mapping.
- Works with StepManiaX stages, USB dance mats, PlayStation / Xbox mats through adapters, and the keyboard.
- Lab mode: BPM and beat detection, a chart generator that follows the music, and a chat assistant (Claude Code,
  Claude API or a local Ollama model) that writes and edits charts with you.

## Running it

**Ready-made package (nothing to install).** The game ships with its own Python, so download the package for your
system, unzip it, and double-click:

| System | Package | Double-click |
|---|---|---|
| Windows | `Rave-Laboratory-<version>-windows-x64.zip` | `Rave Laboratory.exe` |
| macOS (Apple Silicon or Intel) | `...-macos-apple-silicon.tar.gz` / `...-macos-intel.tar.gz` | `Rave Laboratory.app` (first time: right-click > Open) |
| Linux | `...-linux-x64.tar.gz` | `Rave Laboratory.sh` (choose "Run" if your file manager asks) |

The game is still ordinary Python files: open `ravelab.py` and friends in any editor and your changes run next
launch. The bundled interpreter lives in `runtime/` (`runtime\python.exe` on Windows, `runtime/bin/python3` elsewhere).

**With your own Python** (3.10 or newer), from the source zip or a checkout:

```bash
python -m pip install -r requirements.txt
python ravelab.py
```

or double-click `Rave Laboratory.pyw` (Windows, no console window), `Rave Laboratory.command` (macOS) or
`Rave Laboratory.sh` (Linux); the last two make a private `.venv` and install the packages on the first run.
`Play Rave Laboratory (console).bat` on Windows keeps a console open so you can see errors.

### Where do the songs come from?

Put the `Rave Laboratory` folder **inside your Project OutFox folder** (next to `Songs`) and it finds everything by
itself. Anywhere else, it looks in the usual install places (Steam libraries, Program Files, `/Applications`,
`~/.project-outfox`, ...). To point it somewhere by hand:

```bash
python ravelab.py --outfox "D:/Games/Project OutFox"
```

(or put `"outfox_dir": "D:/Games/Project OutFox"` in `data/settings.json`). `python ravelab.py --paths` shows what it
found. With no OutFox at all, the game still runs: Lab mode saves songs into a `Songs` folder next to the game.
OutFox's `AdditionalSongFolders` are read too.

The first start indexes every chart (about a minute per 2,000 songs); after that the index is cached.

### Other command-line switches

| Switch | What it does |
|---|---|
| `--windowed` | Start in a window instead of fullscreen (also F1 > Display > Fullscreen) |
| `--selftest` | Start with no window, index the songs, print what was found, and quit. Good for bug reports. |
| `--bench` | Autoplay a chart for six seconds and print frame pacing |
| `--paths` | Print the folders in use |

## Playing

The first screen is **Who's playing?**: pick a player card (or make one), then the song list.

| | Pad | Keyboard |
|---|---|---|
| Move through songs / folders | Left / Right (hold to scroll) | Left / Right, PgUp / PgDn jump a folder |
| Change difficulty | Up / Down | Up / Down |
| Open a folder, start a song | Start, or Left+Right together | Enter |
| Favorite | Hold Start (or Left+Right) on a song | F |
| Back / close folder / switch player | Back, or Up+Down together | Esc |
| Quit a song | Stand on Up+Down for 2 s, or hold Back | Hold Esc 1 s |
| Search | "Search songs" at the top of the list (on-screen keyboard from the pad) | Space twice, or `/` |
| Sort by group / level / title | | Tab |
| Read speed, judge offset | | `-` `=`, `[` `]` |
| Settings (Design Mode), feedback note | | F1, F2 |

Every 4-panel pad works without a Start button: **Left+Right together = Start, Up+Down together = Back**.

The song panel shows the difficulty ladder with foot ratings and Sensory scores, your best score and lamp,
the groove radar (official DDR values when the song is known, otherwise computed), BPM, length, and whether the
chart was auto-synced to the music.

### Results screen

Shows judgments, max combo, FAST/SLOW counts and a timing histogram. If your steps were consistently early or late
it suggests a judge offset; press **O** to apply it for everyone on this machine (see Timing below). Up (or C) asks
the coach, if one is turned on.

## Timing: the two offsets

Latency is different on every machine (display, audio, pad). Two machine-wide settings correct it, both in
F1 > Timing:

- **Judge offset** (`audio_offset_ms`): when your steps are judged. Play a couple of songs you know, then use the
  number the results screen suggests. Positive = your steps are judged later.
- **Arrow timing** (`visual_offset_ms`): when the arrows reach the receptors. Change it only if the arrows look
  early or late against the music while the judging already feels right.

They are per machine, not per player, on purpose: they correct hardware, not people. Songs whose charts are out of
sync with their audio are measured and corrected automatically at play time (`Auto-fix song sync`); the simfiles are
never edited.

## Settings (Design Mode, F1)

F1 opens a panel on any screen, including mid-song. Up/Down picks a setting, Left/Right changes it (Shift x10),
Backspace resets, Tab switches sections. Settings marked **player** (speed, life gauge, training aids, look) are saved
with the current player; everything else is per machine in `data/settings.json`, which is re-read while the game runs,
so you can also edit it in a text editor.

Sections: Timing, Speed (one read speed for all songs, or a fixed multiplier, or constant), Judging (windows,
freeze grace, pad flicker filter), Life, Look, Training (measure lines, 8th lines, step timing meter, beat flashes,
approach glow, waveform strip), Coach, Lab, Display (resolution, fullscreen, VSync), Menu, Controls (pad setup),
Songs (OutFox import, rescan).

## Dance pads

Plug in the pad before or after starting; it is recognised in this order: bindings you saved in the game,
OutFox's own `Keymaps.ini`, a table of known pads (StepManiaX, L-TEK, Konami/RedOctane/Cobalt Flux mats through
adapters, PlayStation and Xbox controllers and mats), then a guess from what the pad has (a d-pad or two axes become
the arrows). If none of that works, **Set up pad** opens by itself: step on Up, Down, Left, Right, then optionally
Start and Back, and the pad is saved. You can open it any time from Who's playing? > Set up pad (or the P key), or
F1 > Controls. Keyboard arrows (and numpad 4/2/8/6) always work too. Details in [docs/PADS.md](docs/PADS.md).

## Players and OutFox

Each player has their own scores, favorites, recently played, speed and training settings, in
`data/profiles/<player>/`. On the first start (and whenever OutFox has been played since), every OutFox local
profile is imported: best scores are converted to the DDR money score, play counts and favorites come along.
OutFox's files are only read. Import again any time with **I** on Who's playing? or F1 > Songs.

## Lab mode

Pick **Lab mode** on Who's playing?. Drop a song or a music video on the window (or Browse). The game copies it into
`Songs/Rave Lab/<song>/`, finds the BPM and beat grid, and the assistant makes a first chart. Then chat
("easier", "jumps on the chorus", "measure 20 feels awkward") or edit with the mouse and keyboard; Playtest plays it
on the pad from the cursor. Saved charts appear in the song list and in OutFox (the game clears OutFox's cache entry
so the new chart shows up next time OutFox starts).

The assistant (F1 > Lab) is, in `auto` order: **Claude Code** if it is installed and signed in (uses your Claude plan,
no API credits), the **Claude API** if `ANTHROPIC_API_KEY` is set, a local **Ollama** model if one is running, else the
built-in generator. Only the song's shape (loudness per measure, the chart as text) is sent, never audio.

| | Mouse | Keyboard |
|---|---|---|
| Add an arrow / freeze | Click an empty spot / drag down (Alt+drag = roll) | 1-4 = Left Down Up Right; hold and move Up/Down for a freeze |
| Move, delete, change type | Drag, right-click, double-click | Arrows, Delete, T |
| Select, copy, paste, mirror | Click, Ctrl+click, Shift+drag | Shift+Up/Down, Ctrl+A/C/X/V, M, Shift+M |
| Listen, playtest | Play, Clap, Playtest buttons | Space, K, P (Shift+P from the start) |
| Undo / save | Undo, Redo, Save | Ctrl+Z, Ctrl+Y, Ctrl+S (it also saves by itself) |

Lab mode needs ffmpeg (included in the ready-made packages; from source, `imageio-ffmpeg` in requirements.txt provides
it, or install ffmpeg yourself).

## AI step coach

Off by default. F1 > Coach picks Claude Code, the Claude API or Ollama. On the results screen, Up or C asks for three
short tips based on the run's numbers (judgments, timing per rhythm and per panel, where the misses were). Answers are
kept in `data/profiles/<player>/coach.jsonl`.

## Building it yourself

`python build_release.py` makes every package from any operating system (it downloads a Python and the wheels
for each target). `build_frozen.py` is the alternative single-executable build with PyInstaller, kept for
comparison; [docs/BUILDING.md](docs/BUILDING.md) explains both and why the bundled runtime is the release.

## Files

```
Rave Laboratory/
  ravelab.py               the game (python ravelab.py)
  Rave Laboratory.exe / .app / .sh   double-click launchers in the packages (.pyw/.command/.sh from source)
  runtime/                 the bundled Python (packages only)
  data/                    made on first run: settings.json, profiles/, library-cache.json, song-sync.json, wave-cache/
  data/design-notes.jsonl  notes typed with F2, with the song and time they were written at
  data/crash.log           if the game ever crashes, the reason is here
  docs/                    PADS.md, BUILDING.md
```

Deleting `data/library-cache.json` forces a full re-index. Deleting `data/` resets the game (players included).

## Troubleshooting

- **"Loading songs 0 / 0" or "No songs found"**: the game did not find OutFox. Run `python ravelab.py --paths`, then
  `--outfox <folder>`.
- **No music / crackling**: another program has exclusive audio; or lower F1 > Display > Render resolution.
- **Steps all judged late or early**: play one song, accept the offset the results screen suggests (O).
- **Pad does nothing**: open Who's playing? > Set up pad and step on each panel. F1 > Controls shows what the pad
  sends when you press it.
- **Video backgrounds / waveform / Lab imports missing**: ffmpeg was not found. `--selftest` prints where it looked.
- **Windows SmartScreen / macOS "unidentified developer"**: the packages are not signed by us. More info > Run anyway
  (Windows) or right-click > Open (macOS); if macOS still refuses, run `xattr -dr com.apple.quarantine "Rave Laboratory"` once.
- Anything else: `data/crash.log`, and `python ravelab.py --selftest` output, are what to include in a bug report.

Rave Laboratory is not affiliated with Konami, Project OutFox or StepManiaX.
