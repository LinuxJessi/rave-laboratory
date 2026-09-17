# Rave Laboratory: try-out rubric

Start it from the **Rave Laboratory** shortcut on the desktop (or double-click `Rave Laboratory.pyw` in this folder; see README.md for the other systems).
The first launch takes a few seconds to index about 2,200 songs. After that the index is cached.

Score each line 1 to 5 (5 = feels like arcade DDR). Anything you mark 3 or lower, press **F2** right there
and type a short note. Notes are saved with the song, chart and song time to `data/design-notes.jsonl`
so Claude can see what you were looking at.

## Controls

| | Pad | Keyboard |
|---|---|---|
| Move through songs / folders | Left / Right (hold to scroll) | Left / Right, PgUp/PgDn jump folder |
| Change difficulty | Up / Down | Up / Down |
| Open folder, start song | Start, or jump Left+Right | Enter |
| Add/remove favorite | Hold Left+Right on a song (0.6 s) | F |
| Back / close folder | Back, or jump Up+Down | Esc |
| Switch player | Jump Up+Down with all folders closed, or pick "Player" at the top of the list | Esc with folders closed |
| Quit the game | "Quit game" card at the end of Who's playing? | same |
| Quit a song | Stand on Up+Down for 2 s | Hold Esc 1 s |
| Results: accept offset / continue | Up / any other arrow | O / Enter |
| Search songs | "Search songs" at the top: arrows pick a letter, Left+Right types it, Up+Down closes | Space twice or `/`, then type |
| Favorites, Most played, Recently played | Folders at the top of the list | |
| Sort by group / level / title | | Tab |
| Speed, audio offset | | `-` `=`, `[` `]` |
| Design Mode, feedback note | | F1, F2 |
| Set up a pad | Who's playing? > Set up pad | P there, or F1 > Controls |

## 1. Menus (was: OutFox menus are cumbersome)

| # | Try this | Score |
|---|---|---|
| 1.1 | From launch, get to a level 5 Basic chart you like using only the pad. How many steps did it take? | |
| 1.2 | Hold Left/Right to scroll a long folder. Is the speed right? (Design > Menu > wheel speed and delay) | |
| 1.3 | Tab to **level** sort and open "Level 5". Is that a useful way to find songs? | |
| 1.4 | Up/Down to change difficulty. Does it keep your difficulty as you move between songs? | |
| 1.5 | Music preview: does it start fast enough and at a good part of the song? | |
| 1.6 | After a song, do you land back on the same song? Is "Recently played" useful? | |
| 1.7 | Search from the pad: is the on-screen keyboard quick enough? | |
| 1.8 | Song panel: are Sensory, the ladder, the groove radar, BPM and length useful for picking songs? | |
| 1.9 | Is anything you use in OutFox missing (favourites, options before a song, profiles)? | |

## 2. Scoring (was: harsh compared to arcade DDR)

Scoring uses the DDR A20/World money score: 1,000,000 points shared across steps, freezes and shock rows.
Perfect = −10, Great = 60 % −10, Good = 20 % −10, Miss = 0. Grades run from AAA (990k) down to D, and E means failed.
Windows start at arcade values: Marvelous ±16.7 ms, Perfect ±33, Great ±92, Good ±142.

| # | Try this | Score |
|---|---|---|
| 2.1 | Play two charts you know well from OutFox. Do the grades feel closer to arcade? | |
| 2.2 | Do Marvelous and Perfect feel reachable, or too tight? (Design > Judging) | |
| 2.3 | Freeze arrows: is 350 ms of lift-off grace too loose or too tight? | |
| 2.4 | Life gauge: does failing feel fair? Try `normal`, `no fail` and `life4`. | |
| 2.5 | Are the FAST/SLOW labels and the timing chart on the results screen useful? | |

**Do this first:** after your first song the results screen shows your median timing. If it offers
"Set audio offset to X ms", step Up to accept. Then play the same song again and compare. A lot of
"harsh" judging turns out to be a latency offset.

## 3. Frame rate and smoothness

Measured on your PC: a steady 100 fps with VSync at 1080p and at 1440p. The worst single frame was
12 to 16 ms, and the target is 10 ms at 100 Hz.

| # | Try this | Score |
|---|---|---|
| 3.1 | Does scrolling look smooth, with no stutter or tearing? (FPS shows top right) | |
| 3.2 | Try Design > Display > Render resolution 1440 (restart). Sharper, and still smooth? | |
| 3.3 | Try VSync off (restart). Does input feel tighter, or does tearing bother you? | |
| 3.4 | Does anything hitch: song start, the first arrows, background loading? | |

## 4. Look and feel

| # | Try this | Score |
|---|---|---|
| 4.1 | Arrow shape and colours (red 4ths, blue 8ths, yellow 16ths). Readable? | |
| 4.2 | Speed: one read speed for every song (225 to start). Does every song scroll the same? Adjust only Design > Speed > Read speed. | |
| 4.3 | Receptor height, arrow size, background brightness. Adjust in Design > Look | |
| 4.4 | Judgment text and combo: in the way, or not noticeable enough? | |

## How tuning works

- **F1 Design Mode** works on every screen, including mid-song. Changes save instantly to `data/settings.json`.
- Claude can edit that same file while the game is running. The game reloads it within half a second.
- Scores are saved per player in `data/profiles/<player>/scores.json`. Every run's per-step timing goes to
  `data/profiles/<player>/runs/`, which lets Claude check windows and offsets against how you actually play.
- If the game crashes, the error is written to `data/crash.log`.

## Training extras

- **Waveform strip** (F1 > Training): the song scrolls up the left side with the arrows. Bar width is loudness and
  colour is pitch. Tabs show the current BPM, the current pitch and the song's key.
- **AI step coach** (F1 > Coach, off by default): step Up (or press C) on the results screen for three tips.
  - `claude` uses the Anthropic API. Set the `ANTHROPIC_API_KEY` environment variable (or run `ant auth login`),
    then restart the game. The default model is Claude Opus 5; Sonnet 5 and Haiku 4.5 are cheaper choices.
  - `ollama` uses a local model. The first installed chat model is picked unless `data/coach.json` names one.
  - Only run numbers are sent: judgments, timing, and where misses happened with the arrows there. No names or audio.
  - Every answer is saved to `data/profiles/<player>/coach.jsonl`.

## Lab mode (chart your own songs)

Pick **Lab mode** on the Who's playing? screen. Drop a song or a music video on the window (or click Browse).
The game copies it into `Songs/Rave Lab/<song>/`, finds the BPM and beat grid, and the assistant makes a first chart.
Saved charts show up in the song list (and in OutFox, after clearing its song cache).

| | Mouse | Keyboard |
|---|---|---|
| Add an arrow / freeze | Click an empty spot / drag down (Alt+drag = roll) | 1-4 = Left Down Up Right; hold the key and move Up/Down for a freeze |
| Move arrows | Drag them (everything selected moves together) | Arrow keys move the cursor, Left/Right change snap |
| Freeze length | Drag the end of the freeze, or Shorter/Longer | |
| Change arrow type | Double click, or Tap/Freeze/Roll/Mine buttons | T |
| Delete | Right click | Delete |
| Select | Click, Ctrl+click adds, Shift+drag box | Shift+Up/Down, Ctrl+A |
| Copy / paste / mirror | Mirror, Flip buttons | Ctrl+C, Ctrl+X, Ctrl+V (at cursor), M, Shift+M |
| Jump around | Wheel (Shift = measure, Ctrl = zoom), click the beat markers or the song overview | PgUp/PgDn, Home/End, -/= zoom |
| Listen | Play button, Clap toggle | Space, K = clap |
| Play it on the pad | Playtest button (from the cursor's measure) | P (Shift+P from the start) |
| Talk to the assistant | Click the box at the bottom left, or the quick buttons | Enter, type, Enter |
| Undo / save | Undo, Redo, Save | Ctrl+Z, Ctrl+Y, Ctrl+S (it also saves by itself) |

If the grid is off: +/-0.1 BPM, x2 / ÷2, -5/+5 ms, and bar < > (moves where measures start by one beat).
The assistant is set in Design Mode (F1) > Lab: auto uses Claude Code when it is installed and signed in, else the Claude API when ANTHROPIC_API_KEY is set, else Ollama, else the built-in generator.

| # | Try this | Score |
|---|---|---|
| L.1 | Drop a song you like. Is the first chart's rhythm on the music? Are the bar lines where the music's phrases start? | |
| L.2 | Ask the assistant for changes ("easier", "jumps on the chorus", "measure 20 feels awkward"). Did it do what you meant? | |
| L.3 | Fix a few measures with the mouse. Is placing, dragging and deleting arrows quick? | |
| L.4 | Playtest from the middle, then from the start. Does it feel like a real chart? | |
