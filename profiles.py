"""Player profiles: each has its own scores, favorites, recent songs, runs and personal settings.

data/profiles/index.json            {"last": id, "outfox_imported": true}
data/profiles/<id>/profile.json     {"id", "name", "created", "outfox": {...}, "settings": {personal overrides}}
data/profiles/<id>/scores.json      same shape as the old data/scores.json
data/profiles/<id>/runs/            per-run timing detail

Importing from OutFox reads Save/LocalProfiles/*/ (Editable.ini + Stats.xml) and converts each chart's
best OutFox result to a DDR money score from its step counts (W1..W4 = Marvelous..Good, W5/Boo and
Miss = Miss, Held = O.K., LetGo/MissedHold = N.G.). OutFox files are only read, never written.
"""
import json
import os
import re
import shutil
import time

import library
import paths
from settings import PERSONAL

ROOT = os.path.join(paths.DATA, 'profiles')
INDEX = os.path.join(ROOT, 'index.json')
OUTFOX_PROFILES = paths.LOCAL_PROFILES

DIFFS = {'Beginner', 'Easy', 'Medium', 'Hard', 'Challenge', 'Edit'}
GRADES = [(990000, 'AAA'), (950000, 'AA+'), (900000, 'AA'), (890000, 'AA-'), (850000, 'A+'), (800000, 'A'),
          (790000, 'A-'), (750000, 'B+'), (700000, 'B'), (690000, 'B-'), (650000, 'C+'), (600000, 'C'),
          (590000, 'C-'), (550000, 'D+'), (0, 'D')]
LAMPS = ['FAILED', 'CLEAR', 'LIFE4 CLEAR', 'GOOD FULL COMBO', 'GREAT FULL COMBO', 'PERFECT FULL COMBO', 'MARVELOUS FULL COMBO']


def _read_json(path, default):
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def _slug(name):
    s = re.sub(r'[^A-Za-z0-9]+', '-', name).strip('-').lower() or 'player'
    base, n = s, 2
    while os.path.exists(os.path.join(ROOT, s)):
        s = '%s-%d' % (base, n)
        n += 1
    return s


class Profile:
    def __init__(self, pid):
        self.id = pid
        self.dir = os.path.join(ROOT, pid)
        self.data = _read_json(os.path.join(self.dir, 'profile.json'), {'id': pid, 'name': pid, 'settings': {}})
        self.data.setdefault('settings', {})

    @property
    def name(self):
        return self.data.get('name', self.id)

    @property
    def scores_path(self):
        return os.path.join(self.dir, 'scores.json')

    @property
    def runs_dir(self):
        return os.path.join(self.dir, 'runs')

    def save(self):
        library._write_json(os.path.join(self.dir, 'profile.json'), self.data, indent=1)

    def summary(self):
        scores = _read_json(self.scores_path, {})
        best = scores.get('best', {})
        plays = sum(v.get('plays', 0) for v in best.values())
        aaa = sum(1 for v in best.values() if v.get('grade', '').startswith('AA'))
        songs = len({k.split('#', 1)[0] for k in best})
        last = max([scores.get('last_played', '')] + [v.get('date', '') for v in best.values()])
        return {'plays': plays, 'songs': songs, 'aa': aaa, 'last': last}


class Profiles:
    def __init__(self):
        os.makedirs(ROOT, exist_ok=True)
        self.index = _read_json(INDEX, {})

    def all(self):
        out = []
        for pid in sorted(os.listdir(ROOT)):
            if os.path.isfile(os.path.join(ROOT, pid, 'profile.json')):
                out.append(Profile(pid))
        order = self.index.get('order', [])
        out.sort(key=lambda p: (order.index(p.id) if p.id in order else 999, p.name.lower()))
        return out

    def save_index(self):
        library._write_json(INDEX, self.index, indent=1)

    def create(self, name, settings=None, outfox=None):
        pid = _slug(name)
        p = Profile(pid)
        p.data = {'id': pid, 'name': name, 'created': time.strftime('%Y-%m-%d %H:%M:%S'),
                  'settings': dict(settings or {}), 'outfox': outfox}
        os.makedirs(p.dir, exist_ok=True)
        p.save()
        self.index.setdefault('order', []).append(pid)
        self.save_index()
        return p

    def set_last(self, profile):
        self.index['last'] = profile.id
        order = [x for x in self.index.get('order', []) if x != profile.id]
        self.index['order'] = [profile.id] + order     # most recent player first
        self.save_index()

    def find_by_name(self, name):
        return next((p for p in self.all() if p.name.lower() == name.lower()), None)

    # ------------------------------------------------------------------ first run / migration

    def migrate_legacy(self, cfg_values):
        """Move the single pre-profile score book into a profile named after the OutFox profile 00000000."""
        legacy = os.path.join(paths.DATA, 'scores.json')
        if self.index.get('legacy_migrated') or not os.path.isfile(legacy):
            return None
        name = _outfox_name(os.path.join(OUTFOX_PROFILES, '00000000')) or 'Player 1'
        p = self.find_by_name(name) or self.create(name, {k: cfg_values[k] for k in PERSONAL if k in cfg_values})
        if not os.path.exists(p.scores_path):
            shutil.copy2(legacy, p.scores_path)
        runs = os.path.join(paths.DATA, 'runs')
        if os.path.isdir(runs):
            os.makedirs(p.runs_dir, exist_ok=True)
            for f in os.listdir(runs):
                dst = os.path.join(p.runs_dir, f)
                if not os.path.exists(dst):
                    shutil.copy2(os.path.join(runs, f), dst)
        self.index['legacy_migrated'] = True
        self.index.setdefault('last', p.id)
        self.save_index()
        return p

    def import_outfox(self, lib, cfg_values):
        """Create/merge a profile for every OutFox local profile. Returns a list of (name, charts imported)."""
        report = []
        self.index['outfox_imported'] = time.strftime('%Y-%m-%d %H:%M:%S')
        self.index['outfox_stats_stamp'] = outfox_stats_stamp()
        self.save_index()
        if not os.path.isdir(OUTFOX_PROFILES):
            return report
        base_by_name = {}
        for rel in lib.by_rel:
            base_by_name.setdefault(rel.split('/')[-1].lower(), []).append(rel)
        for d in sorted(os.listdir(OUTFOX_PROFILES)):
            folder = os.path.join(OUTFOX_PROFILES, d)
            stats_path = os.path.join(folder, 'Stats.xml')
            name = _outfox_name(folder)
            if not name or not os.path.isfile(stats_path):
                continue
            text = open(stats_path, encoding='utf-8', errors='replace').read()
            guid = (re.search(r'<Guid>([^<]*)</Guid>', text) or [None, ''])[1]
            p = next((x for x in self.all() if (x.data.get('outfox') or {}).get('guid') == guid), None) \
                or self.find_by_name(name) \
                or self.create(name, {k: cfg_values[k] for k in PERSONAL if k in cfg_values})
            p.data['outfox'] = {'dir': d, 'guid': guid, 'imported': time.strftime('%Y-%m-%d %H:%M:%S')}
            p.save()
            n = _merge_stats(p, text, lib, base_by_name)
            report.append((p.name, n))
        return report

    def outfox_changed(self):
        """True when OutFox has been played since the last import (its Stats.xml files are newer)."""
        return os.path.isdir(OUTFOX_PROFILES) and outfox_stats_stamp() != self.index.get('outfox_stats_stamp')


def outfox_stats_stamp():
    """Newest modification time of any OutFox profile's Stats.xml, or 0."""
    newest = 0
    try:
        for d in os.listdir(OUTFOX_PROFILES):
            p = os.path.join(OUTFOX_PROFILES, d, 'Stats.xml')
            if os.path.isfile(p):
                newest = max(newest, int(os.path.getmtime(p)))
    except OSError:
        pass
    return newest


def _outfox_name(folder):
    try:
        text = open(os.path.join(folder, 'Editable.ini'), encoding='utf-8', errors='replace').read()
    except OSError:
        return None
    m = re.search(r'^DisplayName=(.*)$', text, re.M)
    return m.group(1).strip() if m and m.group(1).strip() else None


def _map_song(song_dir, lib, base_by_name):
    rel = song_dir.strip('/')
    if rel.lower().startswith('songs/'):
        rel = rel[6:]
    if rel in lib.by_rel:
        return rel
    hits = base_by_name.get(rel.split('/')[-1].lower(), [])
    return hits[0] if len(hits) == 1 else None


def _num(block, tag):
    m = re.search(r'<%s>([-\d.]+)</%s>' % (tag, tag), block)
    return float(m.group(1)) if m else 0.0


def _convert(hs):
    """OutFox HighScore XML -> DDR money score result dict."""
    taps = {k: int(_num(hs, k)) for k in ('W1', 'W2', 'W3', 'W4', 'W5', 'Miss')}
    held, letgo, missed = int(_num(hs, 'Held')), int(_num(hs, 'LetGo')), int(_num(hs, 'MissedHold'))
    total = sum(taps.values()) + held + letgo + missed
    if total == 0:
        return None
    unit = 1000000.0 / total
    raw = taps['W1'] * unit + taps['W2'] * (unit - 10) + taps['W3'] * (unit * 0.6 - 10) + taps['W4'] * (unit * 0.2 - 10) + held * unit
    score = int(max(0, raw) // 10 * 10)
    grade_tier = (re.search(r'<Grade>([^<]*)</Grade>', hs) or [None, ''])[1]
    failed = grade_tier == 'Failed'
    misses = taps['W5'] + taps['Miss'] + letgo + missed
    if failed:
        lamp = 0
    elif misses == 0 and taps['W4'] == 0 and taps['W3'] == 0 and taps['W2'] == 0:
        lamp = 6
    elif misses == 0 and taps['W4'] == 0 and taps['W3'] == 0:
        lamp = 5
    elif misses == 0 and taps['W4'] == 0:
        lamp = 4
    elif misses == 0:
        lamp = 3
    else:
        lamp = 1
    grade = 'E' if failed else next(g for s, g in GRADES if score >= s)
    ex = taps['W1'] * 3 + taps['W2'] * 2 + taps['W3'] + held * 3
    date = (re.search(r'<DateTime>([^<]*)</DateTime>', hs) or [None, ''])[1]
    return {'score': score, 'grade': grade, 'ex': ex, 'lamp': LAMPS[lamp], 'lamp_rank': lamp, 'date': date[:10],
            'datetime': date, 'imported': 'outfox', 'outfox_percent': round(_num(hs, 'PercentDP') * 100, 2)}


def _merge_stats(profile, text, lib, base_by_name):
    book = _read_json(profile.scores_path, {})
    best = book.setdefault('best', {})
    book.setdefault('recent', [])
    book.setdefault('last', {})
    favs = book.setdefault('favorites', [])
    imported = book.setdefault('outfox_plays', {})     # plays already counted from OutFox, per chart
    recent = {}
    count = 0
    for m in re.finditer(r"<Song Dir='([^']*)'>(.*?)</Song>", text, re.S):
        rel = _map_song(m.group(1), lib, base_by_name)
        if not rel:
            continue
        entry = lib.by_rel[rel]
        for s in re.finditer(r"<Steps Difficulty='(\w+)'(?: Description='([^']*)')?[^>]*StepsType='dance-single'>(.*?)</Steps>",
                             m.group(2), re.S):
            diff, desc, block = s.group(1), s.group(2) or '', s.group(3)
            if diff not in DIFFS:
                continue
            chart = next((c for c in entry['charts'] if c[0] == diff and (diff != 'Edit' or c[2] == desc)), None)
            if not chart:
                continue
            key = '%s#%s|%s' % (rel, chart[0], chart[2])
            plays = int(_num(block, 'NumTimesPlayed'))
            results = [r for r in (_convert(h) for h in re.findall(r'<HighScore>(.*?)</HighScore>', block, re.S)) if r]
            cur = best.get(key, {})
            new_plays = plays - imported.get(key, 0)      # re-imports only add plays made since last time
            if new_plays > 0:
                cur['plays'] = cur.get('plays', 0) + new_plays
                imported[key] = plays
            if results:
                top = max(results, key=lambda r: r['score'])
                if not cur.get('score') or (cur.get('imported') and top['score'] > cur['score']):
                    lamp_keep = cur.get('lamp_rank', -1)
                    cur.update({k: v for k, v in top.items() if k != 'datetime'})
                    if lamp_keep > top['lamp_rank']:
                        cur['lamp_rank'] = lamp_keep
                        cur['lamp'] = LAMPS[lamp_keep]
                last = max(r['datetime'] for r in results)
                recent[rel] = max(recent.get(rel, ''), last)
            if cur:
                best[key] = cur
                count += 1
    for fav in re.findall(r"<Song Dir='([^']*)'\s*/>", (re.search(r'<FavSongs>(.*?)</FavSongs>', text, re.S) or [None, ''])[1]):
        rel = _map_song(fav, lib, base_by_name)
        if rel and rel not in favs:
            favs.append(rel)
    ordered = [r for r, _ in sorted(recent.items(), key=lambda x: x[1], reverse=True)]
    book['recent'] = (book['recent'] + [r for r in ordered if r not in book['recent']])[:30]
    library._write_json(profile.scores_path, book, indent=1)
    return count
