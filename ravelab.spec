# PyInstaller spec for the ALTERNATIVE frozen build (see build_frozen.py and docs/BUILDING.md).
# The official packages come from build_release.py and ship a real Python instead; this is kept for
# anyone who wants a single conventional executable.  Run:  python build_frozen.py
import os
import sys

block_cipher = None
HERE = os.path.abspath(SPECPATH)
NAME = 'Rave Laboratory'

datas = [(os.path.join(HERE, 'Rave Laboratory.ico'), '.'), (os.path.join(HERE, 'Rave Laboratory.png'), '.')]
if os.path.isdir(os.path.join(HERE, 'data-static')):
    datas.append((os.path.join(HERE, 'data-static'), 'data-static'))
try:
    import imageio_ffmpeg
    exe_path = imageio_ffmpeg.get_ffmpeg_exe()
    datas.append((exe_path, os.path.join('tools')))
    # the game looks for tools/ffmpeg(.exe); imageio names it ffmpeg-<os>-<arch>-v<ver>
    ffmpeg_alias = 'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg'
except Exception:
    exe_path = None
    ffmpeg_alias = None

a = Analysis(
    [os.path.join(HERE, 'ravelab.py')],
    pathex=[HERE],
    binaries=[],
    datas=datas,
    hiddenimports=['pad_screen', 'lab_screen', 'labai', 'labaudio', 'labchart', 'claudecode', 'coach', 'filedialog',
                   'mutagen', 'mutagen.mp3', 'mutagen.oggvorbis', 'mutagen.wave', 'mutagen.flac', 'mutagen.mp4', 'mutagen.id3'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'anthropic', 'PIL', 'matplotlib', 'scipy', 'pandas', 'IPython', 'jupyter', 'pytest', 'setuptools', 'PyInstaller'],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

icon = os.path.join(HERE, 'Rave Laboratory.ico') if sys.platform == 'win32' else os.path.join(HERE, 'Rave Laboratory.png')
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name=NAME)

if exe_path and ffmpeg_alias:
    # give the bundled ffmpeg the plain name the game looks for
    import shutil
    out_tools = os.path.join(DISTPATH, NAME, '_internal', 'tools')
    try:
        os.makedirs(out_tools, exist_ok=True)
        src = os.path.join(out_tools, os.path.basename(exe_path))
        dst = os.path.join(out_tools, ffmpeg_alias)
        if os.path.isfile(src) and not os.path.isfile(dst):
            shutil.copy2(src, dst)
            os.remove(src)
    except OSError:
        pass

if sys.platform == 'darwin':
    app = BUNDLE(coll, name=NAME + '.app', icon=icon, bundle_identifier='com.ravelaboratory.game',
                 info_plist={'NSHighResolutionCapable': True, 'CFBundleShortVersionString': '1.0.0',
                             'NSRequiresAquaSystemAppearance': False})
