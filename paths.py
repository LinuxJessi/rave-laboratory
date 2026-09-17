"""Where everything lives: this game's folder and data, bundled resources, and the OutFox install
(its Songs, Save and Cache folders).

Rave Laboratory reads songs from a Project OutFox (or StepMania) install. It looks, in order, at
  1. "outfox_dir" in data/settings.json (set it by hand, or run with --outfox "C:/path/to/OutFox")
  2. the folders above this one (the usual case: this folder sits inside the OutFox folder)
  3. the usual install places on this operating system, including Steam libraries
  4. a Songs folder next to this file (Lab mode still works with no OutFox at all)

Works the same from source and from a PyInstaller build (data/ stays next to the executable).
"""
import glob
import json
import os
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if FROZEN else __file__))
RESOURCES = getattr(sys, '_MEIPASS', APP_DIR)          # icon and other files bundled into a build
DATA = os.path.join(APP_DIR, 'data')
SETTINGS_PATH = os.path.join(DATA, 'settings.json')
IS_WIN = sys.platform == 'win32'
IS_MAC = sys.platform == 'darwin'
LAB_GROUP = 'Rave Lab'


def _read_settings():
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def looks_like_outfox(folder):
    """A StepMania-family install: has a Songs folder plus something only the game ships with."""
    if not folder or not os.path.isdir(os.path.join(folder, 'Songs')):
        return False
    return any(os.path.exists(os.path.join(folder, x)) for x in
               ('portable.ini', 'Program', 'Appearance', 'Themes', 'Save', 'BGAnimations', 'Data'))


def _steam_libraries():
    """steamapps folders of every Steam library on this machine."""
    roots = []
    if IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as k:
                roots.append(winreg.QueryValueEx(k, 'SteamPath')[0])
        except OSError:
            pass
        roots += [r'C:\Program Files (x86)\Steam', r'C:\Program Files\Steam']
    elif IS_MAC:
        roots.append(os.path.expanduser('~/Library/Application Support/Steam'))
    else:
        roots += [os.path.expanduser(p) for p in ('~/.steam/steam', '~/.local/share/Steam', '~/.var/app/com.valvesoftware.Steam/.local/share/Steam')]
    libs = []
    for r in roots:
        if not os.path.isdir(r):
            continue
        libs.append(os.path.join(r, 'steamapps'))
        vdf = os.path.join(r, 'steamapps', 'libraryfolders.vdf')
        try:
            import re
            text = open(vdf, encoding='utf-8', errors='replace').read()
            for m in re.finditer(r'"path"\s+"([^"]+)"', text):
                libs.append(os.path.join(m.group(1).replace('\\\\', '\\'), 'steamapps'))
        except OSError:
            pass
    out = []
    for lib in libs:
        if os.path.isdir(lib) and lib not in out:
            out.append(lib)
    return out


def _candidates():
    for lib in _steam_libraries():
        yield from sorted(glob.glob(os.path.join(lib, 'common', 'Project OutFox*')))
        yield from sorted(glob.glob(os.path.join(lib, 'common', 'OutFox*')))
    if IS_WIN:
        for base in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)'),
                     os.environ.get('LOCALAPPDATA', ''), os.path.expanduser('~'), 'C:\\', 'D:\\'):
            if base:
                yield from sorted(glob.glob(os.path.join(base, 'Project OutFox*')))
                yield from sorted(glob.glob(os.path.join(base, 'OutFox*')))
                yield from sorted(glob.glob(os.path.join(base, 'StepMania*')))
        yield os.path.join(os.environ.get('APPDATA', ''), 'Project OutFox')
    elif IS_MAC:
        yield os.path.expanduser('~/Library/Application Support/Project OutFox')
        yield os.path.expanduser('~/Library/Preferences/Project OutFox')
        yield from sorted(glob.glob('/Applications/Project OutFox*'))
        yield from sorted(glob.glob(os.path.expanduser('~/Applications/Project OutFox*')))
        yield from sorted(glob.glob('/Applications/StepMania*'))
    else:
        for p in ('~/.project-outfox', '~/.outfox', '~/.local/share/project-outfox', '~/.stepmania-5.1', '~/.stepmania-5',
                  '/opt/outfox', '/opt/project-outfox', '~/Games/Project OutFox', '~/Games/OutFox', '~/OutFox', '~/Project OutFox'):
            yield os.path.expanduser(p)
        yield from sorted(glob.glob(os.path.expanduser('~/Games/Project OutFox*')))
        yield from sorted(glob.glob('/usr/share/stepmania*'))


def find_outfox():
    """The OutFox/StepMania folder that holds Songs, or None."""
    cfg = _read_settings()
    chosen = cfg.get('outfox_dir')
    if chosen and looks_like_outfox(os.path.expanduser(chosen)):
        return os.path.abspath(os.path.expanduser(chosen))
    here = APP_DIR
    for _ in range(4):
        if looks_like_outfox(here):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    for cand in _candidates():
        if looks_like_outfox(cand):
            return os.path.abspath(cand)
    return None


def _user_data_dir(game):
    """Where a non-portable OutFox keeps Save/ and Cache/ (portable installs keep them next to Songs)."""
    if game and os.path.isfile(os.path.join(game, 'portable.ini')):
        return game
    if game and os.path.isdir(os.path.join(game, 'Save')):
        return game
    if IS_WIN:
        return os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'Project OutFox')
    if IS_MAC:
        return os.path.expanduser('~/Library/Preferences/Project OutFox')
    return os.path.expanduser('~/.project-outfox')


GAME = find_outfox()
SONGS = os.path.join(GAME, 'Songs') if GAME else os.path.join(APP_DIR, 'Songs')
USER = _user_data_dir(GAME)
SAVE = os.path.join(USER, 'Save')
OUTFOX_CACHE = os.path.join(USER, 'Cache', 'Songs')
LAB_DIR = os.path.join(SONGS, LAB_GROUP)
PREFERENCES = os.path.join(SAVE, 'Preferences.ini')
KEYMAPS = os.path.join(SAVE, 'Keymaps.ini')
LOCAL_PROFILES = os.path.join(SAVE, 'LocalProfiles')


def song_roots():
    """Songs/ plus OutFox's AdditionalSongFolders, if any."""
    roots = [SONGS]
    try:
        text = open(PREFERENCES, encoding='utf-8', errors='replace').read()
    except OSError:
        return roots
    for line in text.splitlines():
        if line.startswith('AdditionalSongFolders='):
            for p in line.split('=', 1)[1].split(','):
                p = p.strip().rstrip('/\\')
                if p and os.path.isdir(p) and p not in roots:
                    roots.append(p)
    return roots


def outfox_cache_file(rel):
    """OutFox's cached parse of a song ("Songs_<group>_<song>.ofcache"); stale after the chart changes."""
    return os.path.join(OUTFOX_CACHE, 'Songs_' + rel.replace('/', '_') + '.ofcache')


def drop_outfox_cache(rel):
    """Delete OutFox's cache entry so it re-reads the song next start (OutFox FastLoad skips changed files)."""
    path = outfox_cache_file(rel)
    try:
        if os.path.isfile(path):
            os.remove(path)
            return True
    except OSError:
        pass
    return False


def theme_files(name):
    """Every file called `name` in any installed theme (used for the official DDR radar table)."""
    if not GAME:
        return []
    out = []
    for base in ('Appearance/Themes', 'Themes'):
        out += glob.glob(os.path.join(GAME, base, '*', '*', name))
        out += glob.glob(os.path.join(GAME, base, '*', name))
    return sorted(out)


def resource(name):
    return os.path.join(RESOURCES, name)


def describe():
    lines = ['Rave Laboratory folder: %s' % APP_DIR, 'Data: %s' % DATA,
             'OutFox: %s' % (GAME or 'not found'), 'Songs: %s' % SONGS, 'Save: %s' % SAVE]
    extra = song_roots()[1:]
    if extra:
        lines.append('Extra song folders: ' + ', '.join(extra))
    return '\n'.join(lines)


if __name__ == '__main__':
    print(describe())
