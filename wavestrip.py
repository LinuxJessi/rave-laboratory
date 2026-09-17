"""Scrolling waveform strip for the left side of the playfield (Design Mode > Training > Waveform).

The song is decoded by a separate ffmpeg process (never through the game's own audio), then analysed:
  loudness   RMS every 10 ms, drawn as the bar width
  pitch      strongest pitch class every 20 ms (chroma), drawn as the bar colour, plus the loudest
             note in the 80-1000 Hz range for the PITCH label
  key        whole-song key from the summed chroma (Krumhansl-Schmuckler profiles)
Results are cached in data/wave-cache so a song is only analysed once.
"""
import colorsys
import hashlib
import os
import subprocess
import threading

import numpy as np
import pygame

import gfx
from gfx import COLORS, u

import paths

CACHE = os.path.join(paths.DATA, 'wave-cache')
RATE = 22050
ENV_STEP = 0.010
PITCH_STEP = 0.020
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
PITCH_COLORS = [tuple(int(v * 255) for v in colorsys.hsv_to_rgb(i / 12.0, 0.65, 1.0)) for i in range(12)]


def _cache_path(path):
    st = os.stat(path)
    key = hashlib.sha1(('%s|%d|%d|v1' % (path, st.st_size, int(st.st_mtime))).encode('utf-8', 'replace')).hexdigest()
    return os.path.join(CACHE, key + '.npz')


def analyse(path):
    cached = _cache_path(path)
    if os.path.isfile(cached):
        d = np.load(cached)
        return {k: d[k] for k in d.files}
    import bgvideo
    exe = bgvideo.ffmpeg_path()
    if not exe:
        return None
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0
    raw = subprocess.run([exe, '-v', 'error', '-nostdin', '-i', path, '-ac', '1', '-ar', str(RATE), '-f', 's16le', '-'],
                         capture_output=True, creationflags=flags).stdout
    a = np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0
    if len(a) < RATE:
        return None
    hop = int(RATE * ENV_STEP)
    n = len(a) // hop
    env = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(axis=1))
    env = env / (np.percentile(env, 99) or 1.0)
    # chroma + main pitch
    win, phop = 4096, int(RATE * PITCH_STEP)
    freqs = np.fft.rfftfreq(win, 1.0 / RATE)
    valid = (freqs >= 55) & (freqs <= 2000)
    midi = np.zeros_like(freqs)
    midi[valid] = 69 + 12 * np.log2(freqs[valid] / 440.0)
    pc = np.round(midi).astype(int) % 12
    melody = (freqs >= 80) & (freqs <= 1000)
    window = np.hanning(win).astype(np.float32)
    frames = max(0, (len(a) - win) // phop)
    pitch_class = np.zeros(frames, np.int8)
    pitch_strength = np.zeros(frames, np.float32)
    main_note = np.zeros(frames, np.int16)
    total = np.zeros(12)
    for start in range(0, frames, 1500):
        count = min(frames, start + 1500) - start
        idx = np.arange(win)[None, :] + phop * np.arange(start, start + count)[:, None]
        mag = np.abs(np.fft.rfft(a[idx] * window, axis=1))
        chroma = np.zeros((count, 12), np.float32)
        for k in range(12):
            chroma[:, k] = mag[:, valid & (pc == k)].sum(axis=1)
        total += chroma.sum(axis=0)
        s = chroma.sum(axis=1) + 1e-9
        pitch_class[start:start + count] = chroma.argmax(axis=1)
        pitch_strength[start:start + count] = chroma.max(axis=1) / s
        mel = np.where(melody[None, :], mag, 0)
        main_note[start:start + count] = np.round(midi[mel.argmax(axis=1)]).astype(np.int16)
    scores = []
    for shift in range(12):
        prof = np.roll(total, -shift)
        scores.append((np.corrcoef(prof, MAJOR)[0, 1], NAMES[shift] + ' major'))
        scores.append((np.corrcoef(prof, MINOR)[0, 1], NAMES[shift] + ' minor'))
    key = max(scores)[1]
    out = {'env': env.astype(np.float32), 'pitch_class': pitch_class, 'pitch_strength': pitch_strength,
           'main_note': main_note, 'key': np.array(key)}
    os.makedirs(CACHE, exist_ok=True)
    np.savez_compressed(cached, **out)
    return out


def note_name(midi):
    return '%s%d' % (NAMES[int(midi) % 12], int(midi) // 12 - 1)


class WaveStrip:
    def __init__(self, music_path):
        self.data = None
        self.failed = False
        threading.Thread(target=self._load, args=(music_path,), daemon=True).start()

    def _load(self, path):
        try:
            self.data = analyse(path)
            self.failed = self.data is None
        except Exception:
            self.failed = True

    def draw(self, surf, timing, cur_beat, vis_t, ry, direction, px_beat, px_sec, constant, field_x0):
        w = u(120)
        x = max(u(8), min(u(24), field_x0 - w - u(40)))
        panel = pygame.Rect(x, 0, w, gfx.H)
        surf.blit(_shade(panel.size), panel)
        cx = panel.centerx
        bpm = timing._bpm_at(cur_beat)
        if self.data is None:
            _label(surf, x, u(6), w, 'BPM', '%d' % round(bpm), COLORS['text'])
            gfx.blit_text(surf, 'analysing...' if not self.failed else 'no waveform', 12, (x + u(8), u(64)), COLORS['dim'])
            return
        d = self.data
        env, pcls, pstr, notes = d['env'], d['pitch_class'], d['pitch_strength'], d['main_note']
        # the rows of the strip, mapped to song time the same way the arrows are
        step = max(2, u(3))
        ys = np.arange(0, gfx.H, step, dtype=np.float32)
        if constant:
            times = vis_t + (ys - ry) / (direction * px_sec)
        else:
            beats = cur_beat + (ys - ry) / (direction * px_beat)
            times = np.array([timing.time_at(b) for b in beats])
        ei = np.clip((times / ENV_STEP).astype(int), 0, len(env) - 1)
        pi = np.clip((times / PITCH_STEP).astype(int), 0, len(pcls) - 1)
        amp = np.where((times >= 0) & (times / ENV_STEP < len(env)), np.minimum(env[ei], 1.2), 0)
        half = (w // 2 - u(6))
        for y, a, k, s in zip(ys, amp, pcls[pi], pstr[pi]):
            if a <= 0.01:
                continue
            length = int(a * half)
            colr = PITCH_COLORS[int(k)] if s > 0.12 else (150, 160, 190)
            pygame.draw.line(surf, colr, (cx - length, int(y)), (cx + length, int(y)), step - 1 if step > 2 else 1)
        pygame.draw.line(surf, (255, 255, 255), (x, ry), (x + w, ry), max(1, u(2)))
        # labels on dark tabs so the bars never hide them
        _label(surf, x, u(6), w, 'BPM', '%d' % round(bpm), COLORS['text'])
        now_i = int(min(len(pcls) - 1, max(0, vis_t / PITCH_STEP)))
        sounding = 0 <= vis_t / PITCH_STEP < len(pcls) and env[int(min(len(env) - 1, max(0, vis_t / ENV_STEP)))] > 0.05
        _label(surf, x, u(58), w, 'PITCH', note_name(notes[now_i]) if sounding else '-',
               PITCH_COLORS[int(pcls[now_i])] if sounding else COLORS['dim'])
        _label(surf, x, gfx.H - u(58), w, 'KEY', str(d['key']), COLORS['text'], small=True)


def _label(surf, x, y, w, title, value, colr, small=False):
    tab = pygame.Rect(x, y, w, u(46))
    surf.blit(_shade(tab.size, 215), tab)
    gfx.blit_text(surf, title, 12, (x + u(8), y + u(3)), COLORS['dim'], True)
    gfx.blit_text(surf, value, 16 if small else 22, (x + u(8), y + u(17)), colr, True, max_w=w - u(12))


_shades = {}


def _shade(size, alpha=140):
    key = (size, alpha)
    if key not in _shades:
        s = pygame.Surface(size, pygame.SRCALPHA)
        s.fill((0, 0, 0, alpha))
        _shades[key] = s
    return _shades[key]
