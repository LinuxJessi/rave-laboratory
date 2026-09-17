"""Package Rave Laboratory with its own Python, so players double-click and play: no Python install, no terminal.

    python build_release.py                 -> every target: windows, macos-arm64, macos-x86_64, linux, plus the source zip
    python build_release.py windows linux   -> only those
    python build_release.py --source        -> only the source zip

The game stays plain .py files (edit them, they run). What gets added is a private Python in runtime/ with
pygame-ce, numpy, mutagen and imageio-ffmpeg (which brings an ffmpeg binary) already installed:

  Windows   the official python.org "embeddable" Python. "Rave Laboratory.exe" is pythonw.exe renamed (still signed
            by the Python Software Foundation); a startup hook in runtime/sitecustomize.py runs ravelab.py.
  macOS     python-build-standalone (the relocatable CPython that uv uses), inside a "Rave Laboratory.app" whose
            executable is a short shell script. One package for Apple Silicon, one for Intel.
  Linux     python-build-standalone plus "Rave Laboratory.sh".

Every target can be built from any operating system: nothing is compiled, wheels are downloaded for the target
platform with pip. Needs network access and pip; Pillow makes the macOS icon (optional).
Outputs land in dist/. .github/workflows/build.yml runs this on GitHub and test-launches each package.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = 'Rave Laboratory'
PY = '3.11'
PY_WIN = '3.11.9'                                  # python.org embeddable build for Windows
EMBED_URL = 'https://www.python.org/ftp/python/%s/python-%s-embed-amd64.zip' % (PY_WIN, PY_WIN)
PBS_API = 'https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest'
REQUIREMENTS = ['pygame-ce>=2.5', 'numpy>=1.24', 'mutagen>=1.47', 'imageio-ffmpeg>=0.5']
BUILD = os.path.join(HERE, 'build')
DIST = os.path.join(HERE, 'dist')

TARGETS = {
    'windows': {'label': 'windows-x64', 'kind': 'embed', 'platforms': ['win_amd64']},
    'macos-arm64': {'label': 'macos-apple-silicon', 'kind': 'pbs', 'triple': 'aarch64-apple-darwin', 'min_os': '11.0',
                    'platforms': ['macosx_11_0_arm64', 'macosx_12_0_arm64', 'macosx_13_0_arm64', 'macosx_14_0_arm64', 'macosx_10_11_universal2']},
    'macos-x86_64': {'label': 'macos-intel', 'kind': 'pbs', 'triple': 'x86_64-apple-darwin', 'min_os': '10.13',
                     'platforms': ['macosx_10_9_x86_64', 'macosx_10_13_x86_64', 'macosx_10_15_x86_64', 'macosx_11_0_x86_64',
                                   'macosx_12_0_x86_64', 'macosx_10_11_universal2']},
    'linux': {'label': 'linux-x64', 'kind': 'pbs', 'triple': 'x86_64-unknown-linux-gnu',
              'platforms': ['manylinux2014_x86_64', 'manylinux_2_17_x86_64', 'manylinux_2_28_x86_64', 'manylinux_2_34_x86_64']},
}

# what goes into every package: the game itself
GAME_FILES = sorted(f for f in os.listdir(HERE) if f.endswith('.py') and f != 'build_release.py') + \
    ['README.md', 'requirements.txt', 'Rave Laboratory.ico', 'Rave Laboratory.png']
GAME_DIRS = ['docs', 'data-static']
SOURCE_EXTRA = ['build_release.py', 'Rave Laboratory.pyw', 'Rave Laboratory.command', 'Rave Laboratory.sh',
                'Play Rave Laboratory (console).bat', 'RUBRIC.md', '.gitignore']

SITECUSTOMIZE = '''"""Startup hook for the bundled Python (imported by "import site" in python311._pth).

When the interpreter is the double-click launcher ("Rave Laboratory.exe", which is pythonw.exe renamed), this runs the
game and exits. When it is runtime\\python.exe (a normal Python for tinkering: runtime\\python.exe ravelab.py --selftest)
it does nothing.
"""
import os
import sys

if os.path.basename(sys.executable).lower().startswith('rave laboratory'):
    _root = os.path.dirname(os.path.abspath(sys.executable))
    os.chdir(_root)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    sys.argv = [os.path.join(_root, 'ravelab.py')] + list(getattr(sys, 'argv', [''])[1:])
    _code = 0
    try:
        import runpy
        runpy.run_path(sys.argv[0], run_name='__main__')
    except SystemExit as e:
        _code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception:
        import traceback
        _code = 1
        try:
            os.makedirs(os.path.join(_root, 'data'), exist_ok=True)
            with open(os.path.join(_root, 'data', 'crash.log'), 'a', encoding='utf-8') as f:
                f.write('\\n==== launcher\\n')
                traceback.print_exc(file=f)
        except OSError:
            pass
        try:
            import ctypes
            _last = traceback.format_exc().strip().splitlines()[-1]
            ctypes.windll.user32.MessageBoxW(None, 'Rave Laboratory could not start.\\n\\n%s\\n\\nDetails are in data\\\\crash.log next to the game.' % _last,
                                             'Rave Laboratory', 0x10)
        except Exception:
            pass
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    os._exit(_code)
'''

CONSOLE_BAT = '''@echo off
rem Rave Laboratory with a console window, for seeing errors and passing switches:
rem   "Rave Laboratory (console).bat" --selftest     "Rave Laboratory (console).bat" --windowed
cd /d "%~dp0"
"runtime\\python.exe" ravelab.py %*
if errorlevel 1 pause
'''

MAC_APP_SCRIPT = '''#!/bin/bash
# Rave Laboratory.app: a thin shell around the Python in runtime/, in the folder that holds this app.
HERE="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$HERE"
exec "$HERE/runtime/bin/python3" "$HERE/ravelab.py" "$@"
'''

MAC_PLIST = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Rave Laboratory</string>
  <key>CFBundleDisplayName</key><string>Rave Laboratory</string>
  <key>CFBundleExecutable</key><string>Rave Laboratory</string>
  <key>CFBundleIdentifier</key><string>com.ravelaboratory.game</string>
  <key>CFBundleIconFile</key><string>Rave Laboratory.icns</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>%(version)s</string>
  <key>CFBundleVersion</key><string>%(version)s</string>
  <key>LSMinimumSystemVersion</key><string>%(min_os)s</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSRequiresAquaSystemAppearance</key><false/>
</dict>
</plist>
'''


# ---------------------------------------------------------------------------- helpers

def read_version():
    with open(os.path.join(HERE, 'ravelab.py'), encoding='utf-8') as f:
        for line in f:
            if line.startswith('VERSION ='):
                return line.split('=', 1)[1].strip().strip("'\"")
    return '0.0.0'


def log(*a):
    print(*a, flush=True)


def download(url, dest):
    if os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    log('downloading', url)
    req = urllib.request.Request(url, headers={'User-Agent': 'rave-laboratory-build'})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest + '.part', 'wb') as f:
        shutil.copyfileobj(r, f)
    os.replace(dest + '.part', dest)
    return dest


def pbs_asset(triple):
    """URL of the latest python-build-standalone install_only build of PY for a target triple."""
    cache = os.path.join(BUILD, 'downloads', 'pbs-latest.json')
    if not os.path.isfile(cache) or os.path.getmtime(cache) < __import__('time').time() - 86400:
        headers = {'User-Agent': 'rave-laboratory-build', 'Accept': 'application/vnd.github+json'}
        if os.environ.get('GITHUB_TOKEN'):
            headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
        with urllib.request.urlopen(urllib.request.Request(PBS_API, headers=headers), timeout=60) as r:
            data = r.read()
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, 'wb') as f:
            f.write(data)
    with open(cache, encoding='utf-8') as f:
        rel = json.load(f)
    pat = re.compile(r'^cpython-%s\.\d+\+\d+-%s-install_only\.tar\.gz$' % (re.escape(PY), re.escape(triple)))
    for a in rel['assets']:
        if pat.match(a['name']):
            return a['browser_download_url'], a['name']
    raise SystemExit('no python-build-standalone %s build for %s in release %s' % (PY, triple, rel.get('tag_name')))


def fetch_wheels(target):
    dest = os.path.join(BUILD, 'wheels', target)
    if os.path.isdir(dest) and any(f.endswith('.whl') for f in os.listdir(dest)):
        return dest
    os.makedirs(dest, exist_ok=True)
    cmd = [sys.executable, '-m', 'pip', 'download', '-q', '--dest', dest, '--only-binary=:all:',
           '--python-version', PY, '--implementation', 'cp']
    for p in TARGETS[target]['platforms']:
        cmd += ['--platform', p]
    cmd += REQUIREMENTS
    log('fetching wheels for', target)
    subprocess.check_call(cmd)
    return dest


def unpack_wheels(wheel_dir, site_packages):
    """Install wheels by unzipping them (pure and binary wheels are just zips laid out for site-packages)."""
    os.makedirs(site_packages, exist_ok=True)
    for name in sorted(os.listdir(wheel_dir)):
        if not name.endswith('.whl'):
            continue
        with zipfile.ZipFile(os.path.join(wheel_dir, name)) as z:
            for info in z.infolist():
                rel = info.filename
                m = re.match(r'^[^/]+\.data/(purelib|platlib)/(.*)$', rel)
                if m:
                    rel = m.group(2)
                elif re.match(r'^[^/]+\.data/', rel):
                    continue                              # scripts, headers: not needed
                if not rel or rel.endswith('/'):
                    continue
                out = os.path.join(site_packages, *rel.split('/'))
                os.makedirs(os.path.dirname(out), exist_ok=True)
                with z.open(info) as src, open(out, 'wb') as dst:
                    shutil.copyfileobj(src, dst)
        log('  installed', name)


def game_tree():
    """[(absolute source path, path inside the package)] for the game files that every package gets."""
    out = []
    for f in GAME_FILES:
        p = os.path.join(HERE, f)
        if os.path.isfile(p):
            out.append((p, f))
    for d in GAME_DIRS:
        full = os.path.join(HERE, d)
        for root, dirs, files in os.walk(full):
            dirs[:] = [x for x in dirs if x != '__pycache__']
            for f in files:
                p = os.path.join(root, f)
                out.append((p, os.path.relpath(p, HERE).replace(os.sep, '/')))
    return out


def make_icns(dest):
    try:
        from PIL import Image
        im = Image.open(os.path.join(HERE, 'Rave Laboratory.png')).convert('RGBA')
        im.save(dest, format='ICNS', sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512)])
        return True
    except Exception as e:
        log('  (no .icns icon: %s)' % e)
        return False


def rm(path):
    if os.path.isdir(path):
        shutil.rmtree(path)


# ---------------------------------------------------------------------------- packages

def source_zip(version):
    out = os.path.join(DIST, '%s-%s-source.zip' % (NAME.replace(' ', '-'), version))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for src, rel in game_tree():
            z.write(src, NAME + '/' + rel)
        for f in SOURCE_EXTRA:
            p = os.path.join(HERE, f)
            if os.path.isfile(p):
                z.write(p, NAME + '/' + f)
        wf = os.path.join(HERE, '.github', 'workflows', 'build.yml')
        if os.path.isfile(wf):
            z.write(wf, NAME + '/.github/workflows/build.yml')
    log('wrote', out)
    return out


def build_windows(version):
    t = TARGETS['windows']
    stage = os.path.join(BUILD, 'stage', 'windows', NAME)
    rm(os.path.dirname(stage))
    runtime = os.path.join(stage, 'runtime')
    os.makedirs(runtime)
    embed = download(EMBED_URL, os.path.join(BUILD, 'downloads', os.path.basename(EMBED_URL)))
    with zipfile.ZipFile(embed) as z:
        z.extractall(runtime)
    # the runtime's own path file: itself, its site-packages, and the game folder above it
    with open(os.path.join(runtime, 'python311._pth'), 'w', encoding='ascii') as f:
        f.write('python311.zip\n.\nsite-packages\n..\nimport site\n')
    with open(os.path.join(runtime, 'sitecustomize.py'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(SITECUSTOMIZE)
    unpack_wheels(fetch_wheels('windows'), os.path.join(runtime, 'site-packages'))
    # the double-click launcher: pythonw.exe renamed, with the DLLs it must find beside itself
    shutil.copy2(os.path.join(runtime, 'pythonw.exe'), os.path.join(stage, NAME + '.exe'))
    for dll in ('python311.dll', 'python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
        if os.path.isfile(os.path.join(runtime, dll)):
            shutil.copy2(os.path.join(runtime, dll), os.path.join(stage, dll))
    with open(os.path.join(stage, 'python311._pth'), 'w', encoding='ascii') as f:
        f.write('runtime/python311.zip\nruntime\nruntime/site-packages\n.\nimport site\n')
    with open(os.path.join(stage, NAME + ' (console).bat'), 'w', encoding='ascii', newline='\r\n') as f:
        f.write(CONSOLE_BAT)
    for src, rel in game_tree():
        dst = os.path.join(stage, *rel.split('/'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    out = os.path.join(DIST, '%s-%s-%s.zip' % (NAME.replace(' ', '-'), version, t['label']))
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(stage):
            for f in files:
                p = os.path.join(root, f)
                z.write(p, NAME + '/' + os.path.relpath(p, stage).replace(os.sep, '/'))
    log('wrote', out)
    return out


def build_pbs(target, version):
    """macOS / Linux: stream python-build-standalone straight into the output tar (keeps symlinks and modes,
    even when building on Windows), then add site-packages, the game and the launchers."""
    t = TARGETS[target]
    url, asset = pbs_asset(t['triple'])
    src_tar = download(url, os.path.join(BUILD, 'downloads', asset))
    stage = os.path.join(BUILD, 'stage', target)
    rm(stage)
    site = os.path.join(stage, 'site-packages')
    unpack_wheels(fetch_wheels(target), site)
    mac = target.startswith('macos')
    app = os.path.join(stage, NAME + '.app', 'Contents')
    if mac:
        os.makedirs(os.path.join(app, 'MacOS'))
        os.makedirs(os.path.join(app, 'Resources'))
        with open(os.path.join(app, 'MacOS', NAME), 'w', encoding='utf-8', newline='\n') as f:
            f.write(MAC_APP_SCRIPT)
        with open(os.path.join(app, 'Info.plist'), 'w', encoding='utf-8', newline='\n') as f:
            f.write(MAC_PLIST % {'version': version, 'min_os': t['min_os']})
        make_icns(os.path.join(app, 'Resources', NAME + '.icns'))
    out = os.path.join(DIST, '%s-%s-%s.tar.gz' % (NAME.replace(' ', '-'), version, t['label']))
    exec_dirs = ('/bin/', '/binaries/', '.app/Contents/MacOS/')

    def mode_for(rel, default=0o644):
        return 0o755 if any(x in rel for x in exec_dirs) or rel.endswith(('.sh', '.command')) else default

    def add_file(tar, src, rel):
        info = tar.gettarinfo(src, arcname=NAME + '/' + rel)
        info.mode = mode_for(rel)
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        with open(src, 'rb') as f:
            tar.addfile(info, f)

    with tarfile.open(out, 'w:gz', compresslevel=6) as tar:
        with tarfile.open(src_tar, 'r:gz') as src:
            for m in src:
                parts = m.name.split('/', 1)
                if len(parts) < 2:
                    continue                               # the top "python" dir itself
                m.name = NAME + '/runtime/' + parts[1]
                if m.islnk():
                    lp = m.linkname.split('/', 1)
                    m.linkname = NAME + '/runtime/' + (lp[1] if len(lp) > 1 else lp[0])
                m.uid = m.gid = 0
                m.uname = m.gname = ''
                tar.addfile(m, src.extractfile(m) if m.isfile() else None)
        for root, dirs, files in os.walk(stage):
            for f in files:
                p = os.path.join(root, f)
                rel = os.path.relpath(p, stage).replace(os.sep, '/')
                if rel.startswith('site-packages/'):
                    rel = 'runtime/lib/python%s/site-packages/' % PY + rel[len('site-packages/'):]
                add_file(tar, p, rel)
        for src_path, rel in game_tree():
            add_file(tar, src_path, rel)
        launcher = 'Rave Laboratory.command' if mac else 'Rave Laboratory.sh'
        add_file(tar, os.path.join(HERE, launcher), launcher)
    log('wrote', out)
    return out


# ---------------------------------------------------------------------------- main

if __name__ == '__main__':
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    version = read_version()
    os.makedirs(DIST, exist_ok=True)
    source_zip(version)
    if '--source' in sys.argv:
        sys.exit(0)
    wanted = args or list(TARGETS)
    for target in wanted:
        if target not in TARGETS:
            sys.exit('unknown target %s (choose from %s)' % (target, ', '.join(TARGETS)))
    for target in wanted:
        log('==== %s' % target)
        if TARGETS[target]['kind'] == 'embed':
            build_windows(version)
        else:
            build_pbs(target, version)
    log('done: %s' % ', '.join(sorted(os.listdir(DIST))))
