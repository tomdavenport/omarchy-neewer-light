#!/usr/bin/env python3
"""Widget entry point; explicit setup only, no downloads during status checks."""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
APP = Path.home() / '.local/share/neewer-omarchy'
STATE = Path.home() / '.local/state/neewer-omarchy'
VERSION = json.loads((ROOT / 'manifest.json').read_text())['version']


def unavailable(message, ok=True):
    return dict(ok=ok, backend_ready=False, configured=False, setup_complete=False,
                test_success=False, connection_state='unconfigured', scanning=False,
                devices=[], roles=[], message=message)


def ready():
    marker = APP / 'installed-version'
    return (marker.is_file() and marker.read_text().strip() == VERSION
            and (APP / 'venv/bin/python').is_file() and (APP / 'controller.py').is_file())


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if action == 'install':
        STATE.mkdir(parents=True, exist_ok=True)
        log = STATE / 'setup.log'
        fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w') as output:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/install_backend.py')],
                                    stdout=output, stderr=subprocess.STDOUT, timeout=900)
        if result.returncode:
            reason = next((line.removeprefix('NEEWER_SETUP_ERROR: ') for line in reversed(log.read_text().splitlines()) if line.startswith('NEEWER_SETUP_ERROR: ')), 'Setup could not finish.')
            return unavailable(reason + ' Try setup again. Details: ~/.local/state/neewer-omarchy/setup.log', False)
        action = 'status'
    if not ready():
        return unavailable('Enable light controls once, then connect your RGB1.')
    result = subprocess.run([str(APP / 'venv/bin/python'), str(APP / 'controller.py'),
                             action, *(sys.argv[2:] if action != 'status' else [])],
                            capture_output=True, text=True, timeout=30)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return unavailable('Light controls could not start. Try Enable light controls to repair the local helper.', False)
    data['backend_ready'] = True
    return data


if __name__ == '__main__':
    try:
        result = main()
    except Exception:
        result = unavailable('Setup or light controls took too long. Try again; your saved light settings are kept.', False)
    print(json.dumps(result))
    sys.exit(0 if result.get('ok') else 1)
