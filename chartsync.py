"""Automatic per-song sync check: compares a chart's beats with onsets in the song's audio.

Corrections are only kept in data/song-sync.json and applied at play time; simfiles are never edited
(OutFox still uses them). Calibrated on 30 official DDR A20/World songs: the onset detector reads
19 ms early on songs known to be in sync (interquartile range 17-19 ms).
"""
import json
import os
import queue
import subprocess
import threading
import time

import numpy as np
import pygame

import paths
import simfile

PATH = os.path.join(paths.DATA, 'song-sync.json')
DETECTOR_BIAS_MS = 19
HOP, WIN = 220, 1024          # 5 ms hop at 44.1 kHz
RECORD_VERSION = 2            # bump when timing maths changes so old measurements are redone


def _decode(path):
    """Mono float samples at 44.1 kHz. Uses a separate ffmpeg process so it can never interrupt the
    game's own audio (decoding through pygame on a thread made previews and songs stutter).
    ffmpeg's decode lines up with pygame's to the sample for both mp3 and ogg."""
    import bgvideo
    exe = bgvideo.ffmpeg_path()
    if exe:
        flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0
        raw = subprocess.run([exe, '-v', 'error', '-nostdin', '-i', path, '-ac', '2', '-ar', '44100', '-f', 's16le', '-'],
                             capture_output=True, creationflags=flags).stdout
        a = np.frombuffer(raw, np.int16).astype(np.float32).reshape(-1, 2)
        return a.mean(axis=1), 44100
    a = pygame.sndarray.array(pygame.mixer.Sound(path))
    a = a.mean(axis=1).astype(np.float32) if a.ndim > 1 else a.astype(np.float32)
    return a, pygame.mixer.get_init()[0]


def _onset_envelope(path):
    return _onset_envelope_from(*_decode(path))


def _onset_envelope_from(a, rate):
    n = (len(a) - WIN) // HOP
    window = np.hanning(WIN).astype(np.float32)
    prev, flux = None, np.zeros(max(0, n), np.float32)
    for start in range(0, n, 2000):           # chunked to keep memory small
        idx = np.arange(WIN)[None, :] + HOP * np.arange(start, min(n, start + 2000))[:, None]
        mag = np.log1p(np.abs(np.fft.rfft(a[idx] * window, axis=1))).astype(np.float32)
        if prev is not None:
            mag_all = np.vstack([prev[None, :], mag])
        else:
            mag_all = np.vstack([mag[:1], mag])
        flux[start:start + len(mag)] = np.maximum(0, np.diff(mag_all, axis=0)).sum(axis=1)
        prev = mag[-1]
    return flux / (flux.std() or 1.0), HOP / float(rate)


def measure(song):
    """Return {'lag_ms', 'confident', ...}. lag < 0 means the music is ahead of the chart."""
    chart = max(song.charts, key=lambda c: len(c.raw or ''))
    simfile.parse_chart(song, chart)
    timing = chart.timing or song.timing
    notes = [n for n in chart.notes if n.kind != 'mine']
    if len(notes) < 30:
        return {'confident': False, 'reason': 'too few notes'}
    env, dt = _onset_envelope(song.music)
    beats = np.array([timing.time_at(b) for b in range(int(notes[0].beat), int(notes[-1].beat) + 1)])
    ntimes = np.array(sorted({round(n.time, 4) for n in notes}))
    chart.notes = []
    # search less than half a beat either way, so an off-beat hi-hat can't win
    lo, hi = timing.bpm_range()
    reach = int(min(120, 0.4 * 60000.0 / max(hi, 1.0)))
    lags = np.arange(-reach, reach + 1) / 1000.0

    def best(times):
        scores = []
        for lag in lags:
            i = np.round((times + lag) / dt).astype(int)
            i = i[(i >= 0) & (i < len(env))]
            scores.append(env[i].mean() if len(i) else 0.0)
        scores = np.array(scores)
        k = int(np.argmax(scores))
        return lags[k] * 1000.0, float(scores[k] / (np.median(scores) or 1.0))
    lag_beats, _ = best(beats)
    lag_notes, strength = best(ntimes)
    lag = (lag_beats + lag_notes) / 2.0 + DETECTOR_BIAS_MS
    agree = abs(lag_beats - lag_notes)
    confident = ((agree <= 20 and strength >= 1.5) or (agree <= 5 and strength >= 1.3))         and abs(lag) <= 90 and abs(lag_notes) < reach - 2 and abs(lag_beats) < reach - 2
    return {'lag_ms': int(round(lag)), 'confident': bool(confident), 'beats_ms': round(lag_beats), 'notes_ms': round(lag_notes),
            'strength': round(strength, 2)}


class SyncBook:
    """Cached measurements plus a background worker."""

    def __init__(self):
        try:
            with open(PATH, encoding='utf-8') as f:
                self.data = json.load(f)
        except (FileNotFoundError, ValueError):
            self.data = {}
        self.lock = threading.Lock()
        self.q = queue.Queue()
        self.pending = set()
        self.paused = False
        self.hold_until = 0.0         # the song wheel pushes this forward while you scroll
        threading.Thread(target=self._worker, daemon=True).start()

    def get(self, entry):
        rec = self.data.get(entry['rel'])
        ok = rec and rec.get('stamp') == entry['stamp'] and rec.get('v') == RECORD_VERSION
        return rec if ok else None

    def request(self, entry):
        if self.get(entry) is None and entry['rel'] not in self.pending:
            self.pending.add(entry['rel'])
            self.q.put(entry)

    def correction_ms(self, entry, compute_now=False):
        rec = self.get(entry)
        if rec is None and compute_now:
            rec = self._measure(entry)
        if rec and rec.get('confident') and abs(rec.get('lag_ms', 0)) >= 15:
            return rec['lag_ms']
        return 0

    def _measure(self, entry):
        try:
            song = simfile.load_song(entry.get('dir') or os.path.join(paths.SONGS, *entry['rel'].split('/')), entry['rel'])
            rec = measure(song)
        except Exception as e:
            rec = {'confident': False, 'reason': str(e)[:120]}
        rec['stamp'] = entry['stamp']
        rec['v'] = RECORD_VERSION
        with self.lock:
            self.data[entry['rel']] = rec
            os.makedirs(os.path.dirname(PATH), exist_ok=True)
            tmp = PATH + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=1, ensure_ascii=False)
            os.replace(tmp, PATH)
        self.pending.discard(entry['rel'])
        return rec

    def _worker(self):
        while True:
            entry = self.q.get()
            # wait while a song is playing or the wheel is moving, so previews stay smooth
            while self.paused or time.perf_counter() < self.hold_until:
                time.sleep(0.25)
            if self.get(entry) is None:
                self._measure(entry)
