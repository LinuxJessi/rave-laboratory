"""Double-click launcher for Windows: starts Rave Laboratory with no console window.

If the game can't start, a message box explains why; full details go to data/crash.log.
Needs Python 3.10+ with pygame-ce (see README.md), or use the ready-made build instead.
"""
import os
import runpy
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
os.chdir(HERE)
sys.path.insert(0, HERE)

try:
    runpy.run_path(os.path.join(HERE, 'ravelab.py'), run_name='__main__')
except SystemExit:
    pass
except Exception:
    os.makedirs(os.path.join(HERE, 'data'), exist_ok=True)
    with open(os.path.join(HERE, 'data', 'crash.log'), 'a', encoding='utf-8') as f:
        f.write('\n==== launcher\n')
        traceback.print_exc(file=f)
    last = traceback.format_exc().strip().splitlines()[-1]
    if 'No module named' in last:
        last += '\n\nInstall the game\'s packages first:  python -m pip install -r requirements.txt'
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, 'Rave Laboratory could not start.\n\n%s\n\nDetails are in data\crash.log next to the game.' % last,
            'Rave Laboratory', 0x10)
    except Exception:
        print(last)
