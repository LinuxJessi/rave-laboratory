"""Song backgrounds from #BGCHANGES: videos decoded by ffmpeg in a background thread, plus images.

ffmpeg decodes at half size and this thread smooth-scales to the render size, so the game thread only blits.
Frames are paced against the song clock: late frames are dropped, early ones wait.
"""
import glob
import os
import re
import shutil
import subprocess
import threading
import time

import pygame

import paths
import simfile

VIDEO_EXTS = ('.avi', '.mp4', '.mpg', '.mpeg', '.wmv', '.webm', '.mkv', '.mov', '.m4v', '.flv', '.ogv')
FPS = 30
_ffmpeg = None
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
LOW_PRIORITY = NO_WINDOW | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)


def ffmpeg_path():
    """ffmpeg from, in order: a tools/ folder next to the game, the PATH, the imageio-ffmpeg package (bundled in
    the ready-made builds), and the usual per-OS install spots (WinGet, Homebrew, MacPorts, Linux)."""
    global _ffmpeg
    if _ffmpeg is None:
        exe = 'ffmpeg.exe' if os.name == 'nt' else 'ffmpeg'
        cands = [os.path.join(paths.APP_DIR, 'tools', exe), os.path.join(paths.RESOURCES, 'tools', exe), os.path.join(paths.APP_DIR, exe)]
        found = next((c for c in cands if os.path.isfile(c)), None) or shutil.which('ffmpeg')
        if not found:
            try:
                import imageio_ffmpeg
                found = imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                found = None
        if not found:
            patterns = [os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WinGet\Packages\*FFmpeg*\*\bin\ffmpeg.exe'),
                        os.path.expandvars(r'%ProgramFiles%\ffmpeg*\bin\ffmpeg.exe'), r'C:\ffmpeg\bin\ffmpeg.exe',
                        '/opt/homebrew/bin/ffmpeg', '/usr/local/bin/ffmpeg', '/opt/local/bin/ffmpeg', '/usr/bin/ffmpeg',
                        '/snap/bin/ffmpeg', os.path.expanduser('~/.local/bin/ffmpeg')]
            for pattern in patterns:
                hits = glob.glob(pattern)
                if hits:
                    found = hits[0]
                    break
        _ffmpeg = found or ''
    return _ffmpeg or None


def probe_duration(path):
    """Seconds of audio/video in a file, read with ffmpeg (no ffprobe needed). None if unknown."""
    exe = ffmpeg_path()
    if not exe:
        return None
    try:
        err = subprocess.run([exe, '-hide_banner', '-nostdin', '-i', path, '-f', 'null', '-'], capture_output=True,
                             creationflags=LOW_PRIORITY, timeout=120).stderr.decode('utf-8', 'replace')
    except (OSError, subprocess.SubprocessError):
        return None
    best = None
    for m in re.finditer(r'time=(\d+):(\d\d):(\d\d(?:\.\d+)?)', err):
        best = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    if best is None:
        m = re.search(r'Duration: (\d+):(\d\d):(\d\d(?:\.\d+)?)', err)
        if m:
            best = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return best


def bg_changes(song_folder, simfile_path, timing):
    """[(song_time, 'video'|'image', path, loop)] from #BGCHANGES, in time order."""
    if not simfile_path or not simfile_path.lower().endswith(('.sm', '.ssc')):
        return []
    text = simfile.read_text(simfile_path)
    m = re.search(r'#BGCHANGES:([^;]*);', text)
    if not m:
        return []
    files = {f.lower(): f for f in os.listdir(song_folder)}
    out = []
    for part in re.sub(r'//[^\n]*', '', m.group(1)).split(','):
        bits = [b.strip() for b in part.split('=')]
        if len(bits) < 2 or not bits[1] or bits[1].startswith('-'):
            continue
        try:
            beat = float(bits[0])
        except ValueError:
            continue
        if beat >= 99999:
            continue
        name = files.get(bits[1].replace('\\', '/').split('/')[-1].lower())
        if not name:
            continue
        ext = os.path.splitext(name)[1].lower()
        kind = 'video' if ext in VIDEO_EXTS else 'image' if ext in simfile.IMAGES else None
        if not kind:
            continue
        loop = len(bits) > 5 and bits[5] == '1'
        out.append((timing.time_at(beat), kind, os.path.join(song_folder, name), loop))
    out.sort(key=lambda x: x[0])
    return out


class VideoPlayer:
    def __init__(self, path, start_time, size, clock, loop=False):
        self.path, self.start_time, self.size, self.clock, self.loop = path, start_time, size, clock, loop
        self.frame = None
        self.shown = 0
        # decode at half size (much less data through the pipe), smooth-scale up in this thread
        self.decode_size = (max(2, size[0] // 2 // 2 * 2), max(2, size[1] // 2 // 2 * 2))
        self.proc = None
        self.stopped = False
        self.failed = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _spawn(self, seek):
        w, h = self.decode_size
        cmd = [ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin']
        if self.loop:
            cmd += ['-stream_loop', '-1']
        if seek > 0.05:
            cmd += ['-ss', '%.3f' % seek]
        cmd += ['-i', self.path, '-an', '-sn',
                '-vf', 'fps=%d,scale=%d:%d:force_original_aspect_ratio=increase,crop=%d:%d' % (FPS, w, h, w, h),
                '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-']
        return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=w * h * 3 * 2,
                                creationflags=NO_WINDOW)

    def _run(self):
        w, h = self.decode_size
        nbytes = w * h * 3
        seek = max(0.0, self.clock() - self.start_time)
        try:
            self.proc = self._spawn(seek)
        except OSError:
            self.failed = True
            return
        k = 0
        while not self.stopped:
            data = self.proc.stdout.read(nbytes)
            if len(data) < nbytes:
                break
            frame_time = self.start_time + seek + k / float(FPS)
            k += 1
            if frame_time < self.clock() - 1.5 / FPS:
                continue                        # behind: drop this frame
            # Windows sleeps in ~15 ms steps, so wake up to one frame early rather than late
            wait = frame_time - self.clock() - 1.0 / FPS
            if wait > 0:
                time.sleep(wait)
            if self.stopped:
                break
            small = pygame.image.frombuffer(data, (w, h), 'RGB')
            self.frame = pygame.transform.smoothscale(small, self.size)
            self.shown += 1
        self.stop()

    def stop(self):
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.kill()
            except OSError:
                pass


class Background:
    """Picks the right background for the current song time."""

    def __init__(self, app, song, simfile_path, timing, clock):
        self.app = app
        self.clock = clock
        self.size = (app.screen.get_width(), app.screen.get_height())
        self.changes = bg_changes(song.folder, simfile_path, timing) if app.cfg.video_backgrounds else []
        if any(c[1] == 'video' for c in self.changes) and not ffmpeg_path():
            app.toast('Video backgrounds need ffmpeg; showing the still background')
            self.changes = [c for c in self.changes if c[1] == 'image']
        self.fallback = song.background
        self.index = -1
        self.player = None

    def current(self):
        """Return a Surface to draw full-screen, or None."""
        now = self.clock()
        idx = -1
        for i, (t, kind, path, loop) in enumerate(self.changes):
            if t <= now + 0.3:                  # start the decoder slightly early
                idx = i
        if idx != self.index:
            self.index = idx
            if self.player:
                self.player.stop()
                self.player = None
            if idx >= 0 and self.changes[idx][1] == 'video':
                t, _, path, loop = self.changes[idx]
                self.player = VideoPlayer(path, t, self.size, self.clock, loop)
        if self.player and not self.player.failed:
            if self.player.frame is not None and now >= self.changes[self.index][0]:
                return self.player.frame
        if idx >= 0 and self.changes[idx][1] == 'image':
            return self.app.images.get(self.changes[idx][2], self.size, 'cover')
        return self.app.images.get(self.fallback, self.size, 'cover')

    def close(self):
        if self.player:
            self.player.stop()
            self.player = None
