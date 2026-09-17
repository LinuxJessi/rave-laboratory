"""ALTERNATIVE packaging: a single conventional executable made with PyInstaller (frozen build).

This is not how Rave Laboratory is released. The official packages (build_release.py) ship the game as plain .py
files together with a real Python in runtime/, so players can read and edit the game. This script is kept so the
other option stays visible and reproducible:

    python -m pip install -r requirements.txt pyinstaller pillow
    python build_frozen.py          -> dist-frozen/Rave Laboratory/  (Rave Laboratory.exe / .app / binary) + zip

Trade-offs against the bundled runtime: smaller and hides Python completely, but the game is no longer editable,
it must be built on each operating system, unsigned frozen executables trip antivirus and SmartScreen more often,
startup is slower, and the anthropic package and tkinter are left out to keep it small.
"""
import os
import platform
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
NAME = 'Rave Laboratory'
DIST = os.path.join(HERE, 'dist-frozen')


def read_version():
    with open(os.path.join(HERE, 'ravelab.py'), encoding='utf-8') as f:
        for line in f:
            if line.startswith('VERSION ='):
                return line.split('=', 1)[1].strip().strip("'\"")
    return '0.0.0'


def os_tag():
    return {'win32': 'windows', 'darwin': 'macos'}.get(sys.platform, 'linux') + '-' + platform.machine().lower()


def zip_dir(zip_path, folder, arc_root):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d not in ('__pycache__', '.venv', 'data')]
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.join(arc_root, os.path.relpath(full, folder)))


def main():
    import importlib.util
    if importlib.util.find_spec('PyInstaller') is None:
        sys.exit('PyInstaller is not installed:  python -m pip install pyinstaller')
    os.makedirs(DIST, exist_ok=True)
    work = os.path.join(HERE, 'build-frozen')
    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--distpath', DIST, '--workpath', work,
           os.path.join(HERE, 'ravelab.spec')]
    print(' '.join(cmd), flush=True)
    subprocess.check_call(cmd, cwd=HERE)
    out_dir = os.path.join(DIST, NAME)
    if sys.platform == 'darwin':
        app = os.path.join(DIST, NAME + '.app')
        bundle = os.path.join(DIST, NAME + '-mac')
        shutil.rmtree(bundle, ignore_errors=True)
        os.makedirs(bundle)
        shutil.move(app, os.path.join(bundle, NAME + '.app'))
        shutil.rmtree(out_dir, ignore_errors=True)
        out_dir = bundle
    for f in ('README.md', 'requirements.txt'):
        shutil.copy2(os.path.join(HERE, f), out_dir)
    if os.path.isdir(os.path.join(HERE, 'docs')):
        shutil.copytree(os.path.join(HERE, 'docs'), os.path.join(out_dir, 'docs'), dirs_exist_ok=True)
    zip_path = os.path.join(DIST, '%s-%s-%s-frozen.zip' % (NAME.replace(' ', '-'), read_version(), os_tag()))
    zip_dir(zip_path, out_dir, NAME)
    shutil.rmtree(work, ignore_errors=True)
    print('wrote', zip_path)


if __name__ == '__main__':
    main()
