# Building the packages, and notes on the ports

Rave Laboratory is released as plain Python files **plus its own Python runtime**, so a player unzips and
double-clicks. Nothing is compiled or frozen: the game stays editable, and the bundled interpreter is a normal
CPython that anyone can use to tinker (`runtime/python.exe ravelab.py --selftest` on Windows,
`runtime/bin/python3 ravelab.py` elsewhere).

## Make the packages

```bash
python -m pip install -r requirements.txt pillow
python build_release.py                  # all four targets + source zip
python build_release.py windows          # one target
```

Any operating system can build every target, because nothing is compiled: the script downloads a Python for
the target and the wheels for it with pip. Outputs in `dist/`:

| Package | Python inside | Player double-clicks |
|---|---|---|
| `Rave-Laboratory-<v>-windows-x64.zip` | python.org embeddable 3.11 in `runtime/` | `Rave Laboratory.exe` |
| `Rave-Laboratory-<v>-macos-apple-silicon.tar.gz` | python-build-standalone 3.11 in `runtime/` | `Rave Laboratory.app` |
| `Rave-Laboratory-<v>-macos-intel.tar.gz` | same, x86_64 build | `Rave Laboratory.app` |
| `Rave-Laboratory-<v>-linux-x64.tar.gz` | python-build-standalone 3.11 in `runtime/` | `Rave Laboratory.sh` |
| `Rave-Laboratory-<v>-source.zip` | none (uses the player's Python 3) | `Rave Laboratory.pyw` / `.command` / `.sh` |

Each runtime has pygame-ce, numpy, mutagen and imageio-ffmpeg installed, and imageio-ffmpeg carries an ffmpeg
binary for that platform, so video backgrounds and Lab mode work with nothing else installed.

### How the launchers work

- **Windows**: `Rave Laboratory.exe` is the embeddable distribution's `pythonw.exe`, renamed. It keeps its
  Python Software Foundation code signature. Next to it sit `python311.dll`, `python3.dll`, the two `vcruntime`
  DLLs and `python311._pth`, which lists `runtime/` as the search path and ends with `import site`; `site` imports
  `runtime/sitecustomize.py`, which runs `ravelab.py` when the interpreter's file name starts with "Rave Laboratory"
  and does nothing when it is `runtime\python.exe`. `Rave Laboratory (console).bat` runs the game with a console
  and passes switches through (`--selftest`, `--windowed`).
- **macOS**: `Rave Laboratory.app/Contents/MacOS/Rave Laboratory` is a four-line shell script that runs
  `runtime/bin/python3 ravelab.py` from the folder that contains the app. `Rave Laboratory.command` does the
  same from Terminal or Finder and accepts switches.
- **Linux**: `Rave Laboratory.sh` runs `runtime/bin/python3 ravelab.py`.

The macOS and Linux tarballs are written straight from the python-build-standalone tarball, so symlinks and
executable bits survive even when the package is built on Windows.

## The other way: a frozen executable (kept for transparency, not the release)

`build_frozen.py` with `ravelab.spec` makes a single conventional executable with PyInstaller into
`dist-frozen/`. It was the first packaging attempt and is kept so both options stay visible and reproducible:

| | Bundled runtime (`build_release.py`, the release) | Frozen (`build_frozen.py`) |
|---|---|---|
| The game is editable `.py` files | yes | no, it is inside the bundle |
| Build every OS from one machine | yes, nothing is compiled | no, build on each OS |
| Launcher signature | Python Software Foundation (renamed `pythonw.exe`) | none, unsigned bootloader |
| Antivirus / SmartScreen | rarely | often (shared bootloader) |
| Startup | direct | unpacks itself first |
| Debugging | `runtime\python.exe ravelab.py --selftest` | no interpreter to run |
| Size (Windows) | 68 MB zip, ~250 MB unpacked | 91 MB zip, ~230 MB unpacked |
| Claude API provider, tkinter | included, pip-installable | left out |

The GitHub workflow can build the frozen variant on request (`workflow_dispatch` with `frozen: true`); it is
uploaded as an artifact and never attached to a release.

## GitHub

`.github/workflows/build.yml` builds all packages on one Linux runner, then downloads each package on a Windows,
macOS and Linux runner and runs its launcher with `--selftest`. Push a tag such as `v1.0.1` and the packages are
attached to the release.

## Testing a package by hand

```
Rave Laboratory (console).bat --selftest        Windows
./Rave\ Laboratory.command --selftest           macOS
./Rave\ Laboratory.sh --selftest                Linux
```

It prints the folders found, the ffmpeg in use, how many songs indexed, the players and the pads, then `ok`.

## Signing and Gatekeeper

The packages are not code-signed by us. Windows: the launcher carries the Python Software Foundation signature,
but SmartScreen may still ask on a fresh download ("More info > Run anyway"). macOS: the first launch needs
right-click > Open; if macOS refuses the bundled `python3`, clear the download quarantine once:

```bash
xattr -dr com.apple.quarantine "Rave Laboratory"
```

Signing and notarising the `.app` with an Apple developer account is an optional step for the workflow.

## Porting notes (what differs per system)

- **Paths**: everything goes through `paths.py`. `APP_DIR` is the folder of the sources. OutFox is found by walking
  up from there, then per-OS candidate folders and Steam libraries. Non-portable OutFox installs keep `Save/` and
  `Cache/` in the user profile: `%APPDATA%\Project OutFox`, `~/Library/Preferences/Project OutFox`,
  `~/.project-outfox`.
- **Subprocesses** (ffmpeg, Claude Code): `CREATE_NO_WINDOW` / priority flags are only applied on Windows.
- **File picker** (`filedialog.py`): Windows uses `GetOpenFileNameW` through ctypes, macOS an AppleScript
  `choose file`, Linux zenity / kdialog / yad; a Tk picker is the last resort.
- **Fonts** (`gfx.py`): Segoe UI / Yu Gothic on Windows, Helvetica Neue / Hiragino on macOS, DejaVu / Noto on Linux,
  with pygame's built-in font as the final fallback.
- **Window**: `SetProcessDPIAware` and the taskbar id are Windows-only and guarded. Fullscreen uses SDL's scaled mode.
- **ffmpeg** (`bgvideo.ffmpeg_path`): `tools/` next to the game, the PATH, imageio-ffmpeg, then WinGet / Homebrew /
  MacPorts / apt locations. Durations come from ffmpeg itself, so ffprobe is not needed.
- **Claude Code** (`claudecode.py`): looked for on the PATH and in `~/.local/bin`, `~/.claude/local`, npm's global
  bin, Homebrew, because an app launched from Finder or a `.pyw` has a shorter PATH than a terminal.
- **Audio**: `pygame.mixer` at 44.1 kHz with a 512-sample buffer. On Linux, PipeWire/PulseAudio work through SDL;
  set `SDL_AUDIODRIVER=alsa` if there is no sound.

## Version

`VERSION` at the top of `ravelab.py` is the release version; `build_release.py` reads it for the package names.
