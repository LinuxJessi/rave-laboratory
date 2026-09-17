"""Lab mode audio: bring a song or music video into Songs/Rave Lab/, then find its tempo and beat grid.

import_media()  copies/converts the file (videos: audio pulled out to .ogg, video kept for the background)
analyse()       BPM, offset, loudness per measure, onset strength on a 16th-note grid, repeated measures

Everything goes through a separate ffmpeg process, like chartsync and wavestrip, so the game's audio never stutters.
"""
import os
import re
import shutil
import subprocess

import numpy as np

import bgvideo
import chartstats
import chartsync
import simfile
import wavestrip

import paths

LAB_GROUP = paths.LAB_GROUP
LAB_DIR = paths.LAB_DIR
AUDIO_EXTS = ('.ogg', '.mp3', '.wav', '.flac', '.m4a', '.aac', '.opus', '.wma', '.oga')
KEEP_AUDIO = ('.ogg', '.mp3', '.wav')        # pygame and OutFox both play these as they are
VIDEO_EXTS = bgvideo.VIDEO_EXTS
_FLAGS = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0


def _ff(args):
    exe = bgvideo.ffmpeg_path()
    if not exe:
        raise RuntimeError('ffmpeg is needed for Lab mode imports')
    r = subprocess.run([exe, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y'] + args,
                       capture_output=True, creationflags=_FLAGS)
    return r.returncode == 0


def safe_name(s):
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '', s).strip(' .')
    return s[:80] or 'Untitled'


def guess_tags(path):
    """(title, artist) from the file's tags, else from an 'Artist - Title' file name."""
    title = artist = ''
    try:
        import mutagen
        f = mutagen.File(path, easy=True)
        if f is not None and f.tags:
            title = (f.tags.get('title') or [''])[0]
            artist = (f.tags.get('artist') or [''])[0]
    except Exception:
        pass
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = re.sub(r'\s*[\(\[](official|music|lyric|audio|video|hd|4k|mv)[^\)\]]*[\)\]]', '', stem, flags=re.I).strip()
    if not title:
        if ' - ' in stem:
            artist, title = [x.strip() for x in stem.split(' - ', 1)]
        else:
            title = stem
    return title.strip() or 'Untitled', artist.strip()


def kind_of(path):
    ext = os.path.splitext(path)[1].lower()
    return 'video' if ext in VIDEO_EXTS else 'audio' if ext in AUDIO_EXTS else None


def import_media(path, status=lambda s: None):
    """Make Songs/Rave Lab/<title>/ from an audio or video file. Returns the project info dict."""
    kind = kind_of(path)
    if not kind:
        raise ValueError('Not a song or video file: %s' % os.path.basename(path))
    title, artist = guess_tags(path)
    name = safe_name(title if not artist else '%s - %s' % (artist, title))
    folder = os.path.join(LAB_DIR, name)
    n = 2
    while os.path.exists(folder):
        folder = os.path.join(LAB_DIR, '%s (%d)' % (name, n))
        n += 1
    os.makedirs(folder)
    ext = os.path.splitext(path)[1].lower()
    info = {'title': title, 'artist': artist, 'music': '', 'video': '', 'background': '', 'source': os.path.basename(path)}
    if kind == 'audio' and ext in KEEP_AUDIO:
        status('Copying the song')
        info['music'] = 'song' + ext
        shutil.copy2(path, os.path.join(folder, info['music']))
    else:
        status('Pulling the audio out of the video' if kind == 'video' else 'Converting the song to .ogg')
        info['music'] = 'song.ogg'
        if not _ff(['-i', path, '-vn', '-sn', '-c:a', 'libvorbis', '-q:a', '6', os.path.join(folder, 'song.ogg')]):
            shutil.rmtree(folder, ignore_errors=True)
            if kind == 'video':
                raise RuntimeError('that video has no sound track. Import the song first, then use Add video in the editor')
            raise RuntimeError('ffmpeg could not read the audio in that file')
    if kind == 'video':
        info['video'] = add_video(folder, path, status)
        if os.path.isfile(os.path.join(folder, 'bg.jpg')):
            info['background'] = 'bg.jpg'
    else:
        status('Looking for cover art')
        if _ff(['-i', path, '-an', '-frames:v', '1', os.path.join(folder, 'bg.jpg')]) and os.path.isfile(os.path.join(folder, 'bg.jpg')):
            info['background'] = 'bg.jpg'
    return folder, info


def add_video(folder, path, status=lambda s: None):
    """Copy a video into the project and grab a still from it for the background image."""
    status('Copying the video')
    name = 'video' + os.path.splitext(path)[1].lower()
    dst = os.path.join(folder, name)
    if os.path.abspath(path) != os.path.abspath(dst):
        shutil.copy2(path, dst)
    length = chartstats.music_length(dst) or 60.0
    _ff(['-ss', '%.2f' % (length * 0.3), '-i', dst, '-frames:v', '1', '-vf', 'scale=1280:-2', os.path.join(folder, 'bg.jpg')])
    return name


# ---------------------------------------------------------------------------- tempo

def _comb_scores(env, dt, bpms, bins=96):
    """For each BPM: how sharply the onset envelope piles up at one phase of the beat."""
    t = np.arange(len(env)) * dt
    out = []
    for bpm in bpms:
        p = 60.0 / bpm
        idx = ((t % p) / p * bins).astype(int) % bins
        hist = np.bincount(idx, weights=env, minlength=bins) / np.maximum(1, np.bincount(idx, minlength=bins))
        # a little smoothing so the peak isn't one noisy bin
        sm = (hist + np.roll(hist, 1) + np.roll(hist, -1)) / 3.0
        k = int(np.argmax(sm))
        out.append((float(sm[k] - np.median(sm)), (k + 0.5) / bins * p))
    return out


def _band_flux(spec, freqs, n, lo, hi, hop):
    f = np.where((freqs >= lo) & (freqs <= hi), spec, 0)
    b = np.fft.irfft(f, n=n).astype(np.float32)
    k = len(b) // hop
    e = np.log1p(np.sqrt((b[:k * hop].reshape(k, hop) ** 2).mean(axis=1)) * 50)
    d = np.maximum(0, np.diff(e, prepend=e[:1]))
    return d / (d.std() or 1.0)


def envelopes(path):
    """Onset strength (all bands) plus snare/hi-hat band onsets, 5 ms apart.
    The second one tells the beat from the off-beat: on 10 official DDR songs the 150-500 Hz and
    2-8 kHz bands hit harder on the beat every time, while kick-drum bands did not."""
    a, rate = chartsync._decode(path)
    hop = chartsync.HOP
    env, dt = chartsync._onset_envelope_from(a, rate)
    spec = np.fft.rfft(a)
    freqs = np.fft.rfftfreq(len(a), 1.0 / rate)
    beat = _band_flux(spec, freqs, len(a), 150, 500, hop) + _band_flux(spec, freqs, len(a), 2000, 8000, hop)
    del spec
    n = min(len(env), len(beat))
    return env[:n], beat[:n], dt


def detect_tempo(env, dt, bass=None):
    """(bpm, time of a beat in seconds). Songs are assumed to keep one tempo; the editor can change it."""
    x = env - env.mean()
    lo_lag, hi_lag = int(60.0 / 220 / dt), int(60.0 / 60 / dt)
    f = np.fft.rfft(x, n=1 << int(np.ceil(np.log2(len(x) * 2))))
    ac = np.fft.irfft(np.abs(f) ** 2)[:hi_lag + 1]
    lags = np.arange(lo_lag, hi_lag + 1)
    bpm_at = 60.0 / (lags * dt)
    prior = np.exp(-0.5 * (np.log2(bpm_at / 125.0) / 0.9) ** 2)          # most dance songs sit near 125
    rough = float(bpm_at[int(np.argmax(ac[lo_lag:hi_lag + 1] * prior))])
    while rough < 85:
        rough *= 2
    while rough > 190:
        rough /= 2
    cands = set()
    for base in (rough, rough * 2, rough / 2, rough * 1.5, rough / 1.5):
        if 70 <= base <= 220:
            cands.update(np.round(np.arange(base - 2.0, base + 2.0, 0.02), 2))
    cands = sorted(cands)
    scores = _comb_scores(env, dt, cands)
    best = {}
    for bpm, (s, ph) in zip(cands, scores):
        w = s * np.exp(-0.5 * (np.log2(bpm / 125.0) / 1.0) ** 2)
        if w > best.get('w', -1):
            best = {'w': w, 'bpm': bpm, 'phase': ph, 's': s}
    bpm = best['bpm']
    # snap to a whole or half BPM when that fits about as well (almost every produced song uses one)
    for snap in (round(bpm), round(bpm * 2) / 2.0):
        if abs(snap - bpm) <= 0.15:
            s, ph = _comb_scores(env, dt, [snap])[0]
            if s >= best['s'] * 0.97:
                bpm, best['phase'] = snap, ph
                break
    phase = best['phase']
    if bass is not None:
        # the strongest pulse overall is sometimes the off-beat; snares and hi-hats settle it
        p = 60.0 / bpm
        t = np.arange(len(bass)) * dt
        on = bass[np.abs(((t - phase + p / 2) % p) - p / 2) < 0.025].mean()
        off = bass[np.abs(((t - phase) % p) - p / 2) < 0.025].mean()
        if off > on:
            phase = (phase + p / 2) % p
    return float(bpm), float(phase)


def analyse(music_path, status=lambda s: None, bpm=None, offset=None):
    """Find the beat grid, or (with bpm and offset) just re-read the rhythm on a grid the player set."""
    status('Listening for the beat')
    if bpm:
        env, dt = chartsync._onset_envelope(music_path)
    else:
        env, bass, dt = envelopes(music_path)
        bpm, phase = detect_tempo(env, dt, bass)
    spb = 60.0 / bpm
    status('Reading loudness and pitch')
    wave = wavestrip.analyse(music_path) or {}
    loud = wave.get('env')
    length = len(env) * dt
    if offset is not None:
        return _rhythm(env, dt, loud, wave, bpm, -offset, length)
    beat_time = phase + chartsync.DETECTOR_BIAS_MS / 1000.0
    # which beat of four is "1": where the music gets suddenly louder (new sections start on a downbeat).
    # Right on 16 of 21 official charts; the loudest-onset beat alone was right on 10.
    beats = beat_time + np.arange(int((length - beat_time) / spb)) * spb
    if loud is not None and len(loud) and len(beats) > 8:
        per_beat = np.array([loud[int(t / 0.01):int((t + spb) / 0.01)].mean() if int(t / 0.01) < len(loud) else 0.0
                             for t in beats])
        rise = np.diff(per_beat)
        votes = np.zeros(4)
        for i in np.argsort(rise)[::-1][:8]:
            votes[(i + 1) % 4] += rise[i]
        down = int(np.argmax(votes))
    else:
        strength = np.array([_peak(env, dt, t) for t in beats])
        down = int(np.argmax([strength[k::4].mean() if len(strength[k::4]) else 0 for k in range(4)]))
    t_down = beat_time + down * spb
    t0 = t_down - np.ceil(t_down / (4 * spb)) * 4 * spb          # beat 0 at or just before the music starts
    return _rhythm(env, dt, loud, wave, bpm, t0, length)


def _rhythm(env, dt, loud, wave, bpm, t0, length):
    spb = 60.0 / bpm
    offset = round(-t0, 3)
    measures = int(np.ceil((length - t0) / (4 * spb)))
    # 16th-note onset strength, normalised against the song's own busy parts
    grid = np.zeros((measures, 16), np.float32)
    for m in range(measures):
        for k in range(16):
            grid[m, k] = _peak(env, dt, t0 + (m * 4 + k / 4.0) * spb, 0.02)
    # against the busy parts nearby, so a quiet intro still shows where its beats are
    overall = float(np.percentile(grid[grid > 0], 95)) if (grid > 0).any() else 1.0
    local = np.array([np.percentile(grid[max(0, m - 4):m + 5], 95) for m in range(measures)]) if measures else np.zeros(0)
    grid /= np.maximum(local, overall * 0.3)[:, None] if measures else 1.0
    grid = np.minimum(grid, 1.5)
    loudness = np.zeros(measures, np.float32)
    if loud is not None and len(loud):
        for m in range(measures):
            a, b = int((t0 + m * 4 * spb) / 0.01), int((t0 + (m + 1) * 4 * spb) / 0.01)
            seg = loud[max(0, a):max(0, min(len(loud), b))]
            loudness[m] = float(seg.mean()) if len(seg) else 0.0
    # measures that sound like an earlier one (same rhythm shape), for reusing patterns when the music repeats
    same_as = [-1] * measures
    norms = np.linalg.norm(grid, axis=1) + 1e-6
    for m in range(measures):
        for j in range(max(0, m - 64), m):
            if loudness[m] > 0.1 and abs(loudness[m] - loudness[j]) < 0.25 and grid[m] @ grid[j] / (norms[m] * norms[j]) > 0.93:
                same_as[m] = same_as[j] if same_as[j] >= 0 else j
                break
    notes = wave.get('main_note')
    sample = _loudest_window(loud, 15.0) if loud is not None else max(0.0, length * 0.35)
    return {'bpm': bpm, 'offset': offset, 'length': round(length, 2), 'measures': measures,
            'grid': grid.round(3).tolist(), 'loudness': loudness.round(3).tolist(), 'same_as': same_as,
            'key': str(wave.get('key', '')), 'sample_start': round(sample, 2),
            'pitch': _pitch_per_16th(notes, t0, spb, measures) if notes is not None else []}


def _peak(env, dt, t, win=0.025):
    a, b = int((t - win) / dt), int((t + win) / dt) + 1
    if b <= 0 or a >= len(env):
        return 0.0
    return float(env[max(0, a):min(len(env), b)].max())


def _loudest_window(loud, secs):
    n = int(secs / 0.01)
    if loud is None or len(loud) <= n:
        return 0.0
    c = np.cumsum(np.insert(loud, 0, 0))
    sums = c[n:] - c[:-n]
    return round(float(np.argmax(sums[: len(sums) - n // 2]) * 0.01), 2)


def _pitch_per_16th(notes, t0, spb, measures):
    out = []
    for m in range(measures):
        row = []
        for k in range(16):
            i = int((t0 + (m * 4 + k / 4.0) * spb) / wavestrip.PITCH_STEP)
            row.append(int(notes[i]) if 0 <= i < len(notes) else 0)
        out.append(row)
    return out


def song_timing(bpm, offset):
    return simfile.Timing(offset, [(0.0, bpm)])
