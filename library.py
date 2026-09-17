"""Song library index (cached) and local score book."""
import json
import os
import threading
import time

import chartstats
import paths
import simfile

GAME = paths.GAME
SONGS = paths.SONGS
DATA = paths.DATA
CACHE = os.path.join(DATA, 'library-cache.json')
SCORES = os.path.join(DATA, 'scores.json')
RUNS = os.path.join(DATA, 'runs')
CACHE_VERSION = 5   # 5: entries carry their folder ('dir'), extra song roots. 4: warps, DWI 24ths, song length


def _write_json(path, obj, indent=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


def _probe_length(path):
    """ffmpeg's idea of the duration; mutagen misreads some wav and VBR mp3 files."""
    import bgvideo
    return bgvideo.probe_duration(path)


class Library:
    """Scans Songs/<group>/<song>/ in a background thread. Entries are plain dicts."""

    def __init__(self):
        self.groups = []          # [(group name, [entry, ...])]
        self.by_rel = {}
        self.roots = [SONGS]
        self.ready = False
        self.progress = (0, 0)
        self.status = 'Reading song list...'
        self.generation = 0       # goes up each time a scan finishes, so the song list can rebuild
        self.scanning = True
        threading.Thread(target=self._safe_scan, daemon=True).start()

    def _safe_scan(self):
        try:
            self._scan()
        except Exception as e:          # a broken song folder must never leave the game stuck on "Loading"
            self.status = 'Song scan failed: %s' % e
            self.scanning = False
            self.ready = True
            self.generation += 1

    def _scan(self):
        try:
            with open(CACHE, encoding='utf-8') as f:
                cache = json.load(f)
            if cache.get('version') != CACHE_VERSION:
                cache = {}
        except (FileNotFoundError, ValueError):
            cache = {}
        old = cache.get('songs', {})
        folders = []
        seen = set()
        self.roots = paths.song_roots()
        for root in self.roots:
            try:
                groups = sorted(os.listdir(root), key=str.lower)
            except OSError:
                continue
            for g in groups:
                gp = os.path.join(root, g)
                if not os.path.isdir(gp):
                    continue
                try:
                    names = sorted(os.listdir(gp), key=str.lower)
                except OSError:
                    continue
                for s in names:
                    sp = os.path.join(gp, s)
                    if os.path.isdir(sp) and (g + '/' + s) not in seen:
                        seen.add(g + '/' + s)
                        folders.append((g, s, sp))
        if not folders:
            self.status = 'No songs found in %s' % SONGS
        new, changed = {}, 0
        for i, (g, s, sp) in enumerate(folders):
            self.progress = (i, len(folders))
            rel = g + '/' + s
            path = simfile.pick_simfile(sp)
            if not path:
                continue
            stamp = os.path.getmtime(path)
            entry = old.get(rel)
            if entry and entry.get('dir') != sp:
                entry = None
            if not entry or entry.get('stamp') != stamp:
                changed += 1
                self.status = 'Indexing ' + rel
                try:
                    song = simfile.load_song(sp, rel)
                except Exception as e:   # a broken simfile shouldn't stop the scan
                    print('skip', rel, e)
                    continue
                if not song or not song.charts:
                    continue
                lo, hi = song.timing.bpm_range()
                length = chartstats.music_length(song.music) if song.music else 0.0
                stats = []
                for c in song.charts:
                    try:
                        st = chartstats.compute(song, c, length)
                    except Exception as e:
                        print('stats failed', rel, c.diff, e)
                        st = None
                    if st:
                        official = chartstats.official_radar(s, song.title, c.diff)
                        if official:
                            st['radar'], st['radar_official'] = official, True
                    stats.append(st)
                    if st and st.get('chart_end', 0) > length:
                        length = max(length, _probe_length(song.music) or 0.0)
                    c.notes = []
                entry = {
                    'rel': rel, 'group': g, 'dir': sp, 'stamp': stamp, 'title': song.title, 'subtitle': song.subtitle,
                    'artist': song.artist, 'music': song.music, 'banner': song.banner, 'jacket': song.jacket,
                    'background': song.background, 'sample_start': song.sample_start, 'sample_length': song.sample_length,
                    'bpm': song.display_bpm or ('%d' % round(hi) if abs(hi - lo) < 0.5 else '%d-%d' % (round(lo), round(hi))),
                    'bpm_max': hi, 'charts': [[c.diff, c.meter, c.desc] for c in song.charts], 'stats': stats,
                    'length': round(length, 1),
                }
            new[rel] = entry
        if changed or len(new) != len(old):
            _write_json(CACHE, {'version': CACHE_VERSION, 'songs': new})
        groups = {}
        for e in new.values():
            groups.setdefault(e['group'], []).append(e)
        self.groups = [(g, sorted(v, key=lambda e: e['title'].lower())) for g, v in sorted(groups.items(), key=lambda x: x[0].lower())]
        self.by_rel = new
        self.progress = (len(folders), len(folders))
        self.generation += 1
        self.scanning = False
        self.ready = True

    def rescan(self):
        """Pick up songs added or changed while the game runs (Lab mode saves)."""
        if self.ready and not self.scanning:
            self.scanning = True
            threading.Thread(target=self._safe_scan, daemon=True).start()

    def search(self, query):
        words = [chartstats._norm(w) for w in query.split() if chartstats._norm(w)]
        if not words:
            return []
        hits = []
        for e in self.by_rel.values():
            hay = chartstats._norm(' '.join((e['title'], e.get('subtitle', ''), e['artist'], e['rel'])))
            if all(w in hay for w in words):
                hits.append(e)
        return sorted(hits, key=lambda e: (not chartstats._norm(e['title']).startswith(words[0]), e['title'].lower()))


class ScoreBook:
    def __init__(self, path=SCORES, runs_dir=RUNS):
        self.path, self.runs_dir = path, runs_dir
        try:
            with open(path, encoding='utf-8') as f:
                self.data = json.load(f)
        except (FileNotFoundError, ValueError):
            self.data = {}
        self.data.setdefault('best', {})
        self.data.setdefault('recent', [])
        self.data.setdefault('last', {})
        self.data.setdefault('favorites', [])

    def best(self, rel, chart_key):
        return self.data['best'].get(rel + '#' + chart_key)

    def record(self, rel, chart_key, result, run_detail):
        k = rel + '#' + chart_key
        prev = self.data['best'].get(k)
        is_best = not prev or result['score'] > prev['score']
        entry = dict(prev or {})
        if is_best:
            entry.update({kk: result[kk] for kk in ('score', 'grade', 'ex')}, date=time.strftime('%Y-%m-%d'))
        if result['lamp_rank'] > entry.get('lamp_rank', -1):
            entry.update(lamp=result['lamp'], lamp_rank=result['lamp_rank'])
        entry['plays'] = entry.get('plays', 0) + 1
        self.data['best'][k] = entry
        recent = [r for r in self.data['recent'] if r != rel]
        self.data['recent'] = [rel] + recent[:29]
        self.data['last_played'] = time.strftime('%Y-%m-%d')
        self.save()
        os.makedirs(self.runs_dir, exist_ok=True)
        name = '%s-%s.json' % (time.strftime('%Y%m%d-%H%M%S'), ''.join(ch if ch.isalnum() else '_' for ch in rel)[-60:])
        _write_json(os.path.join(self.runs_dir, name), run_detail, indent=1)
        return is_best, prev

    def is_favorite(self, rel):
        return rel in self.data['favorites']

    def toggle_favorite(self, rel):
        favs = self.data['favorites']
        if rel in favs:
            favs.remove(rel)
        else:
            favs.append(rel)
        self.save()
        return rel in favs

    def plays(self):
        """Plays per song in this app."""
        out = {}
        for k, v in self.data['best'].items():
            rel = k.split('#', 1)[0]
            out[rel] = out.get(rel, 0) + v.get('plays', 0)
        return out

    def remember(self, **kw):
        self.data['last'].update(kw)
        self.save()

    def save(self):
        _write_json(self.path, self.data, indent=1)
