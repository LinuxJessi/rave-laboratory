"""A native "open file" dialog on Windows, macOS and Linux, safe to call from a background thread
and from a PyInstaller build (no Tk needed).

Windows: the classic GetOpenFileName dialog through ctypes.   macOS: an AppleScript "choose file".
Linux: zenity, kdialog or yad, whichever is installed.   Last resort: a Tk picker in a helper Python.
Returns the chosen path, or '' when cancelled or no dialog is available.
"""
import os
import shutil
import subprocess
import sys


def ask_open_file(title, patterns, description='Files'):
    """patterns: list like ['*.mp3', '*.ogg']."""
    if sys.platform == 'win32':
        return _windows(title, patterns, description)
    if sys.platform == 'darwin':
        return _mac(title, patterns)
    return _linux(title, patterns, description) or _tk(title, patterns, description)


def _windows(title, patterns, description):
    import ctypes
    from ctypes import wintypes

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [('lStructSize', wintypes.DWORD), ('hwndOwner', wintypes.HWND), ('hInstance', wintypes.HINSTANCE),
                    ('lpstrFilter', wintypes.LPCWSTR), ('lpstrCustomFilter', wintypes.LPWSTR), ('nMaxCustFilter', wintypes.DWORD),
                    ('nFilterIndex', wintypes.DWORD), ('lpstrFile', wintypes.LPWSTR), ('nMaxFile', wintypes.DWORD),
                    ('lpstrFileTitle', wintypes.LPWSTR), ('nMaxFileTitle', wintypes.DWORD), ('lpstrInitialDir', wintypes.LPCWSTR),
                    ('lpstrTitle', wintypes.LPCWSTR), ('Flags', wintypes.DWORD), ('nFileOffset', wintypes.WORD),
                    ('nFileExtension', wintypes.WORD), ('lpstrDefExt', wintypes.LPCWSTR), ('lCustData', wintypes.LPARAM),
                    ('lpfnHook', ctypes.c_void_p), ('lpTemplateName', wintypes.LPCWSTR), ('pvReserved', ctypes.c_void_p),
                    ('dwReserved', wintypes.DWORD), ('FlagsEx', wintypes.DWORD)]

    buf = ctypes.create_unicode_buffer(4096)
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.lpstrFilter = '%s\0%s\0All files\0*.*\0\0' % (description, ';'.join(patterns))
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buf, wintypes.LPWSTR)
    ofn.nMaxFile = 4096
    ofn.lpstrTitle = title
    ofn.Flags = 0x00080000 | 0x00001000 | 0x00000800 | 0x00000004   # EXPLORER | FILEMUSTEXIST | PATHMUSTEXIST | HIDEREADONLY
    try:
        ctypes.windll.ole32.CoInitialize(None)
    except Exception:
        pass
    ok = ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(ofn))
    return buf.value if ok else ''


def _mac(title, patterns):
    script = 'set f to choose file with prompt "%s"\nPOSIX path of f' % title.replace('"', '')
    try:
        out = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=600)
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _linux(title, patterns, description):
    if shutil.which('zenity'):
        cmd = ['zenity', '--file-selection', '--title', title, '--file-filter', '%s | %s' % (description, ' '.join(patterns)),
               '--file-filter', 'All files | *']
    elif shutil.which('kdialog'):
        cmd = ['kdialog', '--getopenfilename', os.path.expanduser('~'), '%s (%s)' % (description, ' '.join(patterns)), '--title', title]
    elif shutil.which('yad'):
        cmd = ['yad', '--file', '--title', title, '--file-filter', '%s | %s' % (description, ' '.join(patterns))]
    else:
        return ''
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        return out.stdout.strip() if out.returncode == 0 else ''
    except (OSError, subprocess.SubprocessError):
        return ''


def _tk(title, patterns, description):
    """Tk in a helper process (Tk and SDL don't share a thread well). Only when a Python is around."""
    exe = sys.executable
    if getattr(sys, 'frozen', False):
        exe = shutil.which('python3') or shutil.which('python') or ''
    elif exe.lower().endswith('pythonw.exe'):
        exe = exe[:-5] + '.exe' if os.path.isfile(exe[:-5] + '.exe') else exe
    if not exe:
        return ''
    code = ('import sys, tkinter as tk, tkinter.filedialog as fd\n'
            'sys.stdout.reconfigure(encoding="utf-8")\n'
            'r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)\n'
            'print(fd.askopenfilename(parent=r, title=%r, filetypes=[(%r, %r), ("All files", "*.*")]))\n'
            % (title, description, ' '.join(patterns)))
    try:
        out = subprocess.run([exe, '-c', code], capture_output=True, timeout=600,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        return out.decode('utf-8', 'replace').strip()
    except (OSError, subprocess.SubprocessError):
        return ''
