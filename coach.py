"""Optional AI step coach. Off by default; turned on in Design Mode > Coach.

Providers
  claude-code  `claude -p` through Claude Code (the player's Claude plan, no API credits), see claudecode.py
  claude  Anthropic API through the official `anthropic` SDK. Credentials come from the environment
          (ANTHROPIC_API_KEY, or a profile from `ant auth login`); the game never stores a key.
  ollama  A local Ollama server (default http://localhost:11434), model from data/coach.json.

Only a numeric summary of the run is sent (judgments, timing, where misses happened and what the
arrows were there, recent history on this chart). No player names, files or audio.
"""
import json
import os
import re
import statistics
import threading
import time
import urllib.error
import urllib.request

import paths

CONFIG = os.path.join(paths.DATA, 'coach.json')
DEFAULT_CONFIG = {'ollama_url': 'http://localhost:11434', 'ollama_model': ''}
COLS = 'LDUR'

SYSTEM = (
    "You are a friendly dance-game coach for a 4-panel arcade DDR-style game played on a dance pad. "
    "Judging uses arcade DDR windows: Marvelous within 16.7 ms, Perfect 33.3 ms, Great 91.7 ms, Good 141.7 ms, "
    "otherwise Miss. Offsets are step time minus arrow time, so positive means late. "
    "The game's global timing offset has already been calibrated; never tell the player to change offsets or "
    "settings, coach their stepping instead. Base every point on the numbers given and do not invent details. "
    "Reply in plain text with at most 3 short numbered tips (about 120 words total), most useful first. "
    "Each tip names what to practise and where in the song it matters (use the time in seconds or the measure)."
)


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG, encoding='utf-8') as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, ValueError):
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    return cfg


# ---------------------------------------------------------------------------- summary of a run

def summarize(res, history):
    """Compact, model-friendly description of one run. `history` = earlier run dicts for this chart."""
    song, chart = res['song'], res['chart']
    notes = [n for n in chart.notes if n.kind != 'mine']
    offs = res['offsets_ms']
    c = res['counts']
    out = {
        'song': song.title, 'artist': song.artist,
        'chart': {'difficulty': {'Beginner': 'BEGINNER', 'Easy': 'BASIC', 'Medium': 'DIFFICULT', 'Hard': 'EXTREME',
                                 'Challenge': 'CHALLENGE'}.get(chart.diff, chart.diff),
                  'level': chart.meter, 'steps': len({round(n.time, 3) for n in notes}),
                  'freezes': sum(1 for n in notes if n.kind in ('hold', 'roll')),
                  'length_s': round(max(n.time for n in notes), 1) if notes else 0},
        'result': {'score': res['score'], 'grade': res['grade'], 'lamp': res['lamp'], 'max_combo': res['max_combo'],
                   'marvelous': c['marvelous'], 'perfect': c['perfect'], 'great': c['great'], 'good': c['good'],
                   'miss': c['miss'], 'freeze_ok': c['ok'], 'freeze_ng': c['ng'], 'fast': res['fast'], 'slow': res['slow']},
    }
    if offs:
        out['timing_ms'] = {'median': round(statistics.median(offs)), 'spread_stdev': round(statistics.pstdev(offs)),
                            'within_33ms_pct': round(100 * sum(1 for o in offs if abs(o) <= 33.3) / len(offs))}
        n = len(offs)
        out['timing_ms']['median_by_fifth_of_song'] = [round(statistics.median(offs[i * n // 5:(i + 1) * n // 5] or [0]))
                                                       for i in range(5)]
    # timing by rhythm and by panel, from raw presses matched to the nearest arrow in that column
    events = res.get('events') or []
    by_quant, by_col = {}, {}
    for t, col in events:
        cand = [nn for nn in notes if nn.col == col and abs(t - nn.time) <= 0.15]
        if cand:
            nn = min(cand, key=lambda x: abs(t - x.time))
            d = (t - nn.time) * 1000
            by_quant.setdefault({4: '4ths', 8: '8ths', 12: '12ths', 16: '16ths'}.get(nn.quant, 'finer'), []).append(d)
            by_col.setdefault(COLS[col], []).append(d)
    out['median_ms_by_rhythm'] = {k: [round(statistics.median(v)), len(v)] for k, v in by_quant.items()}
    out['median_ms_by_panel'] = {k: [round(statistics.median(v)), len(v)] for k, v in by_col.items()}
    # where the misses clustered, with the arrows around them
    missed = [nn for nn in notes if not any(col == nn.col and abs(t - nn.time) <= 0.1417 for t, col in events)]
    clusters = []
    for nn in missed:
        if clusters and nn.time - clusters[-1][-1].time < 2.5:
            clusters[-1].append(nn)
        else:
            clusters.append([nn])
    worst = sorted(clusters, key=len, reverse=True)[:4]
    out['miss_clusters'] = []
    for cl in sorted(worst, key=lambda x: x[0].time):
        start, end = cl[0].time - 1.0, cl[-1].time + 0.5
        pattern = ''.join(COLS[x.col] + ('8' if x.quant == 8 else '' if x.quant == 4 else '+')
                          for x in notes if start <= x.time <= end)[:40]
        pressed = ''.join(COLS[col] for t, col in sorted(events) if start <= t <= end)[:40]
        out['miss_clusters'].append({'from_s': round(cl[0].time, 1), 'to_s': round(cl[-1].time, 1),
                                     'measure': int(cl[0].beat // 4) + 1, 'misses': len(cl),
                                     'arrows_there': pattern, 'panels_you_stepped': pressed})
    out['legend'] = "arrows_there: L/D/U/R per arrow; '8' after a letter = 8th note, '+' = finer than 8th"
    if history:
        out['earlier_runs_on_this_chart'] = [{'date': h.get('time', '')[:10], 'score': h.get('score'), 'grade': h.get('grade'),
                                              'median_ms': (h.get('timing') or {}).get('median_ms'),
                                              'spread_ms': (h.get('timing') or {}).get('stdev_ms'),
                                              'miss': (h.get('counts') or {}).get('miss')} for h in history[-5:]]
    return out


# ---------------------------------------------------------------------------- providers

def _ask_claude(model, summary):
    try:
        import anthropic
    except ImportError:
        return None, 'The Claude coach needs the anthropic package: pip install anthropic'
    client = anthropic.Anthropic(timeout=90.0)
    kwargs = dict(model=model, max_tokens=16000, system=SYSTEM,
                  messages=[{'role': 'user', 'content': 'Here is my run. What should I work on?\n\n' + json.dumps(summary, indent=1)}])
    try:
        if model == 'claude-opus-5':
            # thinking is on by default for Opus 5; medium effort is plenty for three tips.
            # Server-side fallbacks re-run on another model if the request is ever declined.
            resp = client.beta.messages.create(betas=['server-side-fallback-2026-07-01'], fallbacks='default',
                                               output_config={'effort': 'medium'}, **kwargs)
        elif model == 'claude-sonnet-5':
            resp = client.messages.create(thinking={'type': 'adaptive'}, output_config={'effort': 'medium'}, **kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        return None, 'Claude: no valid API key. Set ANTHROPIC_API_KEY (or run `ant auth login`) and restart the game.'
    except anthropic.PermissionDeniedError:
        return None, 'Claude: this API key cannot use %s.' % model
    except anthropic.NotFoundError:
        return None, 'Claude: model %s was not found.' % model
    except anthropic.RateLimitError:
        return None, 'Claude: rate limited, try again in a minute.'
    except anthropic.APIStatusError as e:
        return None, 'Claude: API error %s.' % e.status_code
    except anthropic.APIConnectionError:
        return None, 'Claude: could not reach the API (network?).'
    except TypeError as e:
        if 'authentication' in str(e).lower():
            return None, 'Claude: no API key found. Set ANTHROPIC_API_KEY (or run `ant auth login`) and restart the game.'
        return None, 'Claude: unexpected request error (%s). Try: pip install -U anthropic' % e
    if resp.stop_reason == 'refusal':
        return None, 'Claude declined to answer this one.'
    text = '\n'.join(b.text for b in resp.content if b.type == 'text').strip()
    return (text or None), (None if text else 'Claude returned no text.')


def ollama_models(url):
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/api/tags', timeout=3) as r:
            return [m['name'] for m in json.load(r).get('models', [])]
    except (urllib.error.URLError, OSError, ValueError):
        return None


def _ask_ollama(cfg, summary):
    url = cfg['ollama_url'].rstrip('/')
    models = ollama_models(url)
    if models is None:
        return None, 'Ollama is not running at %s.' % url
    # default: the first general chat model (skip coding, vision and embedding models)
    general = [m for m in models if not re.search(r'coder|code|vl|vision|embed|llava', m, re.I)]
    model = cfg.get('ollama_model') or (general or models or [''])[0]
    if not model:
        return None, 'Ollama has no models installed (try: ollama pull llama3.1).'
    if model not in models and model + ':latest' not in models:
        return None, 'Ollama model "%s" is not installed. Installed: %s' % (model, ', '.join(models[:5]))
    body = json.dumps({'model': model, 'stream': False, 'options': {'temperature': 0.3},
                       'messages': [{'role': 'system', 'content': SYSTEM},
                                    {'role': 'user', 'content': 'Here is my run. What should I work on?\n\n' + json.dumps(summary, indent=1)}]}).encode()
    req = urllib.request.Request(url + '/api/chat', data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            text = json.load(r).get('message', {}).get('content', '')
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.S).strip()     # thinking models (qwen3, deepseek-r1)
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, 'Ollama request failed: %s' % e
    return (text or None), (None if text else 'Ollama returned no text.')


class CoachRequest:
    """Runs one request in a background thread; poll .done / .text / .error from the game loop."""

    def __init__(self, provider, claude_model, summary, on_done=None, claude_code_model='claude-sonnet-5'):
        self.provider, self.model, self.cc_model = provider, claude_model, claude_code_model
        self.summary = summary
        self.text = self.error = None
        self.done = False
        self.started = time.perf_counter()
        self.on_done = on_done
        threading.Thread(target=self._run, daemon=True).start()

    @property
    def label(self):
        if self.provider == 'claude-code':
            return 'Claude Code (%s)' % self.cc_model
        if self.provider == 'claude':
            return 'Claude (%s)' % self.model
        return 'Ollama (%s)' % (load_config().get('ollama_model') or 'first installed chat model')

    def _run(self):
        try:
            if self.provider == 'claude-code':
                import claudecode
                prompt = 'Here is my run. What should I work on?\n\n' + json.dumps(self.summary, indent=1)
                self.text, self.error = claudecode.ask(self.cc_model, SYSTEM, prompt, name='coach')
            elif self.provider == 'claude':
                self.text, self.error = _ask_claude(self.model, self.summary)
            else:
                self.text, self.error = _ask_ollama(load_config(), self.summary)
        except Exception as e:           # never let the coach take the game down
            self.error = 'Coach failed: %s' % e
        self.done = True
        if self.on_done:
            try:
                self.on_done(self)
            except Exception:
                pass
