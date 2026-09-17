"""Ask Claude through the Claude Code command line, so a Claude Pro/Max subscription pays instead of API credits.

Runs `claude -p` with every tool turned off, no saved session, and the game's own system prompt, from an empty
folder (so no project CLAUDE.md is picked up). The prompt goes in on stdin. It needs Claude Code installed and
signed in once: open a terminal, run `claude`, then /login.
"""
import json
import os
import shutil
import subprocess

import paths

WORK = os.path.join(paths.DATA, 'claude-code')
LOGIN_HELP = ('Claude Code is not signed in. Open a terminal, run: claude  then type /login and sign in with your '
              'Claude subscription. Then ask again.')


def path():
    found = shutil.which('claude')
    if found:
        return found
    home = os.path.expanduser('~')
    cands = [os.path.join(home, '.local', 'bin', 'claude.exe'), os.path.join(home, '.local', 'bin', 'claude'),
             os.path.join(home, '.claude', 'local', 'claude'), os.path.join(home, '.claude', 'local', 'bin', 'claude'),
             os.path.join(os.environ.get('APPDATA', ''), 'npm', 'claude.cmd'),
             '/opt/homebrew/bin/claude', '/usr/local/bin/claude', '/usr/bin/claude', os.path.join(home, '.npm-global', 'bin', 'claude')]
    for cand in cands:
        if cand and os.path.isfile(cand):
            return cand
    return None


def installed():
    return path() is not None


def ask(model, system, prompt, name='assistant', effort='medium', timeout=300):
    """Returns (text, error). error is a sentence meant for the player."""
    exe = path()
    if not exe:
        return None, 'Claude Code is not installed (https://claude.com/claude-code).'
    os.makedirs(WORK, exist_ok=True)
    sys_file = os.path.join(WORK, '%s-system.txt' % name)
    with open(sys_file, 'w', encoding='utf-8') as f:
        f.write(system)
    env = dict(os.environ)
    if env.get('CLAUDECODE'):
        # started from inside a Claude Code session: don't inherit that session's connection settings
        for k in list(env):
            if k == 'CLAUDECODE' or k.startswith('CLAUDE_CODE_') or k == 'ANTHROPIC_BASE_URL':
                env.pop(k)
    cmd = [exe, '-p', '--model', model, '--system-prompt-file', sys_file, '--tools', '', '--output-format', 'json',
           '--no-session-persistence', '--strict-mcp-config', '--disable-slash-commands', '--effort', effort]
    try:
        run = subprocess.run(cmd, input=prompt.encode('utf-8'), capture_output=True, timeout=timeout, cwd=WORK, env=env,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except subprocess.TimeoutExpired:
        return None, 'Claude Code took longer than %d s.' % timeout
    except OSError as e:
        return None, 'Could not start Claude Code: %s' % e
    out = run.stdout.decode('utf-8', 'replace').strip()
    try:
        data = json.loads(out[out.find('{'):]) if '{' in out else {}
    except ValueError:
        data = {}
    result = str(data.get('result') or '')
    if not data:
        err = (run.stderr.decode('utf-8', 'replace') or out).strip()
        if 'login' in err.lower() or 'logged in' in err.lower():
            return None, LOGIN_HELP
        return None, 'Claude Code failed: %s' % (err[:200] or 'no output')
    if data.get('is_error'):
        low = result.lower()
        if 'not logged in' in low or '/login' in low or 'authentication' in low:
            return None, LOGIN_HELP
        if 'limit' in low:
            return None, 'Claude Code: %s' % result[:200]
        return None, 'Claude Code: %s' % (result[:200] or 'request failed')
    return (result.strip() or None), (None if result.strip() else 'Claude Code returned no text.')


def transcript(messages):
    """Flatten a user/assistant message list into one prompt (Claude Code -p takes a single message)."""
    if len(messages) == 1:
        return messages[0]['content']
    parts = ['Conversation so far (the last PLAYER message is the one to answer):']
    for m in messages:
        parts.append('%s:\n%s' % ('PLAYER' if m['role'] == 'user' else 'YOU', m['content']))
    return '\n\n'.join(parts)
