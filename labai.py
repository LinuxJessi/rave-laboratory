"""Lab mode chat: talk to Claude or a local Ollama model about the chart that is open in the editor.

The model sees the song's shape (BPM, loudness per measure, repeated measures), the open chart in a compact
text form, and where the editor cursor/selection is. It answers with JSON: something to say, plus edit
actions (labchart.ACTION_HELP) that the editor applies as one undoable step.

Provider 'auto' uses Claude Code when it is installed (the player's Claude subscription, no API credits), then the
Claude API when a key is set up, then Ollama when it is running, then the built-in generator only.
If a provider fails in auto mode the next one answers, and the reply says why.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

import claudecode
import coach
import labchart

SYSTEM = """You are the step-chart assistant inside Rave Laboratory's Lab mode, a DDR-style editor for a 4-panel pad \
(Left, Down, Up, Right). You and the player edit the chart together; they can also drag arrows with the mouse.

Every message from the player comes with the current song and chart. Measures are numbered from 1, four beats each.
Chart notation, one measure: "1 L | 1.5 D | 2 UR | 3 R~2 | 4 *U"
  beat within the measure (1, 1.5, 2.25, 3+1/3 for triplets), then panels: several letters = a jump,
  ~N after a panel = freeze arrow N beats long, ^N = roll, * before a panel = mine. "-" = empty measure.

Reply with ONE JSON object and nothing else:
{"say": "short friendly reply, 1-3 sentences, plain text", "actions": [ ... ]}
Actions (leave the list empty when just talking):
""" + labchart.ACTION_HELP + """

How to work:
- For a new chart or a big change ("easier", "more jumps", "fewer freezes") use generate with style values; it follows \
the music's rhythm and repeats patterns when the music repeats. Use a new seed for "try again".
- For precise changes to a few measures use write (or copy/transform). Only write measures that exist in the song.
- Levels: 1-3 beginner (quarter notes), 4-6 easy (mostly on-beat, about 1.5-2.2 steps per second, few off-beats), \
7-9 medium (8th notes), 10+ hard (16ths, more jumps).
- What makes charts feel good for these players: steps on the beat, the same rhythm and arrows reused when the music \
repeats, some jacks (same arrow twice) are fine, no crossovers or twisted stances below level 10, no quick 8th-note \
Up/Down swaps below level 8, feet returning to Left/Right, freezes on held notes and long vocals.
- If the player asks about something in the song (a drop, the chorus), use the loudness map to find the measures.
- Mention measure numbers in "say" so the player can find your change."""


def claude_available():
    if os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN') or os.environ.get('ANTHROPIC_PROFILE'):
        return True
    home = os.path.expanduser('~')
    return any(os.path.isdir(os.path.join(home, p)) for p in ('.config/anthropic', 'AppData/Roaming/anthropic'))


PROVIDERS = ['auto', 'claude-code', 'claude', 'ollama', 'built-in']


def provider_chain(setting):
    """Providers to try in order."""
    if setting in PROVIDERS[1:]:
        return [setting]
    chain = []
    if claudecode.installed():
        chain.append('claude-code')
    if claude_available():
        chain.append('claude')
    return chain + ['ollama', 'built-in']


def pick_provider(setting):
    return provider_chain(setting)[0]


def context_block(project, diff, cursor_measure, selection):
    an = project.analysis or {}
    chart = project.chart(diff)
    charts = ', '.join('%s %d (%d arrows)%s' % (c.diff, c.meter, len(c.notes), ' <- open' if c.diff == diff else '')
                       for c in project.charts) or 'none yet'
    lines = ['SONG: "%s"%s, %.2f BPM, offset %.3f s, %.0f s long, %d measures%s' % (
        project.title, ' by ' + project.artist if project.artist else '', project.bpm, project.offset,
        an.get('length', 0), an.get('measures', 0), ', key ' + an['key'] if an.get('key') else ''),
        'SONG MAP (measure:loudness 0-9, =mN sounds like measure N): ' + labchart.song_map(project),
        'CHARTS: ' + charts]
    if chart is not None:
        lines.append('OPEN CHART: %s level %d, stats %s' % (diff, chart.meter, json.dumps(chart.stats(project.bpm))))
    else:
        lines.append('OPEN CHART: %s (empty, not created yet)' % diff)
    where = 'EDITOR: cursor at measure %d' % cursor_measure
    if selection:
        where += ', player has measures %d-%d selected' % selection
    lines.append(where)
    if chart is not None and chart.notes:
        lines.append('NOTES:\n' + labchart.chart_digest(project, chart, cursor_measure))
    return '\n'.join(lines)


def parse_reply(text):
    """Find the JSON object in a model reply. Returns (say, actions)."""
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()
    m = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S)
    raw = m.group(1) if m else text[text.find('{'):text.rfind('}') + 1] if '{' in text else ''
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            acts = d.get('actions') or []
            return str(d.get('say') or '').strip(), acts if isinstance(acts, list) else [acts]
    except ValueError:
        pass
    return text[:1200], []


# ---------------------------------------------------------------------------- providers

def _ask_claude(model, system, messages):
    try:
        import anthropic
    except ImportError:
        return None, 'Claude needs the anthropic package: pip install anthropic'
    client = anthropic.Anthropic(timeout=240.0)
    kwargs = dict(model=model, max_tokens=16000, system=system, messages=messages)
    try:
        if model == 'claude-opus-5':
            # thinking is on by default; medium effort keeps replies quick. Fallbacks re-run a declined request.
            resp = client.beta.messages.create(betas=['server-side-fallback-2026-07-01'], fallbacks='default',
                                               output_config={'effort': 'medium'}, **kwargs)
        elif model == 'claude-sonnet-5':
            resp = client.messages.create(thinking={'type': 'adaptive'}, output_config={'effort': 'medium'}, **kwargs)
        else:
            resp = client.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        return None, 'auth'
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
            return None, 'auth'
        return None, 'Claude: unexpected request error (%s)' % e
    if resp.stop_reason == 'refusal':
        return None, 'Claude declined to answer that one.'
    text = '\n'.join(b.text for b in resp.content if b.type == 'text').strip()
    if resp.stop_reason == 'max_tokens' and '}' not in text[-5:]:
        return None, 'Claude ran out of room writing that; try a smaller range of measures.'
    return (text or None), (None if text else 'Claude returned no text.')


def _ask_ollama(system, messages):
    cfg = coach.load_config()
    url = cfg['ollama_url'].rstrip('/')
    models = coach.ollama_models(url)
    if models is None:
        return None, 'Ollama is not running at %s.' % url, ''
    general = [m for m in models if not re.search(r'coder|code|vl|vision|embed|llava', m, re.I)]
    model = cfg.get('lab_model') or cfg.get('ollama_model') or (general or models or [''])[0]
    if not model:
        return None, 'Ollama has no models installed (try: ollama pull qwen3:8b).', ''
    body = json.dumps({'model': model, 'stream': False, 'format': 'json', 'think': False,
                       'options': {'temperature': 0.4, 'num_ctx': 16384},
                       'messages': [{'role': 'system', 'content': system}] + messages}).encode()
    req = urllib.request.Request(url + '/api/chat', data=body, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            text = json.load(r).get('message', {}).get('content', '')
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, 'Ollama request failed: %s' % e, model
    return (text or None), (None if text else 'Ollama returned no text.'), model


class ChatRequest:
    """One turn in a background thread. The editor polls .done, then reads .say / .actions / .error."""

    def __init__(self, setting, claude_model, history, context, user_text, claude_code_model='claude-sonnet-5'):
        self.setting, self.claude_model, self.claude_code_model = setting, claude_model, claude_code_model
        self.history, self.context, self.user_text = history, context, user_text
        self.say, self.actions, self.error = '', [], None
        self.label = ''
        self.done = False
        self.started = time.perf_counter()
        self.followup = None          # set by the editor after a "show" action
        threading.Thread(target=self._run, daemon=True).start()

    def _messages(self):
        msgs = []
        for h in self.history[-16:]:
            if h.get('role') in ('user', 'assistant') and h.get('text'):
                text = h['text'] + ('\n[applied: %s]' % '; '.join(h['log']) if h.get('log') else '')
                if msgs and msgs[-1]['role'] == h['role']:
                    msgs[-1]['content'] += '\n' + text
                else:
                    msgs.append({'role': h['role'], 'content': text})
        while msgs and msgs[0]['role'] != 'user':
            msgs.pop(0)
        turn = self.context + '\n\nPLAYER: ' + self.user_text
        if msgs and msgs[-1]['role'] == 'user':
            msgs[-1]['content'] += '\n\n' + turn
        else:
            msgs.append({'role': 'user', 'content': turn})
        return msgs

    def _run(self):
        try:
            msgs = self._messages()
            chain = provider_chain(self.setting)
            skipped = []
            for i, provider in enumerate(chain):
                last = i == len(chain) - 1
                text = err = None
                if provider == 'claude-code':
                    self.label = 'Claude Code (%s)' % self.claude_code_model
                    text, err = claudecode.ask(self.claude_code_model, SYSTEM, claudecode.transcript(msgs), name='lab')
                elif provider == 'claude':
                    self.label = 'Claude API (%s)' % self.claude_model
                    text, err = _ask_claude(self.claude_model, SYSTEM, msgs)
                    if err == 'auth':
                        err = 'Claude API: no valid API key (set ANTHROPIC_API_KEY and restart the game).'
                elif provider == 'ollama':
                    text, err, model = _ask_ollama(SYSTEM, msgs)
                    self.label = 'Ollama (%s)' % (model or '?')
                else:
                    self.label = 'built-in generator'
                    self.say, self.actions = builtin_reply(self.user_text)
                    break
                if err:
                    if last:
                        self.error = err
                    else:
                        skipped.append(err)
                    continue
                self.say, self.actions = parse_reply(text)
                if not self.say and not self.actions:
                    self.error = 'The model reply could not be read.'
                break
            if skipped and not self.error:
                self.say = '(%s)\n%s' % (' '.join(skipped), self.say)
        except Exception as e:           # never let the chat take the game down
            self.error = 'Chat failed: %s' % e
        self.done = True


def builtin_reply(text):
    """No AI available: understand a few plain requests so the buttons still work."""
    t = text.lower()
    diff = next((d for key, d in (('beginner', 'Beginner'), ('basic', 'Easy'), ('easy', 'Easy'), ('medium', 'Medium'),
                                  ('difficult', 'Medium'), ('hard', 'Hard'), ('expert', 'Hard'), ('challenge', 'Challenge'))
                 if re.search(r'\b%s\b' % key, t)), None)
    m = re.search(r'\b(?:level|lv|meter)\s*(\d{1,2})\b', t)
    act = {'do': 'generate'}
    if diff:
        act['difficulty'] = diff
    if m:
        act['meter'] = int(m.group(1))
    style = {}
    if 'easier' in t:
        style['density'] = 0.75
    if 'harder' in t or 'more steps' in t:
        style['density'] = 1.3
    if 'more jump' in t:
        style['jumps'] = 0.15
    if 'no jump' in t or 'fewer jump' in t:
        style['jumps'] = 0.0
    if 'more freeze' in t:
        style['freezes'] = 0.9
    if 'no freeze' in t or 'fewer freeze' in t:
        style['freezes'] = 0.0
    if style:
        act['style'] = style
    if any(w in t for w in ('generate', 'make', 'chart', 'again', 'easier', 'harder', 'jump', 'freeze', 'start')):
        return ('No AI model is available, so I used the built-in generator. Install and sign in to Claude Code '
                '(uses your Claude plan) or start Ollama to chat about changes.'), [act]
    return ('No AI model is available right now (sign in to Claude Code, or start Ollama). '
            'Try "generate easy level 4", "easier", "more freezes" or edit with the mouse.'), []
