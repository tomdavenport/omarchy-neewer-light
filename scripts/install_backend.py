#!/usr/bin/env python3
"""Explicit per-user setup with a staged environment and rollback; no root."""
import fcntl
import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parent.parent
FILES = ('controller.py', 'light_ble.py', 'light_commands.py', 'light_config.py',
         'light_daemon.py', 'light_effects.py', 'light_palette.py', 'light_service.py',
         'light_transition.py', 'theme_watch.py', 'light_state.py', 'light_power.py',
         'lock_watch.py', 'shutdown_watch.py')
UNIT = '''[Unit]
Description=NEEWER light theme utility
After=graphical-session.target

[Service]
Type=simple
ExecStart=%h/.local/share/neewer-omarchy/venv/bin/python %h/.local/share/neewer-omarchy/light_daemon.py
Restart=on-failure
RestartSec=3
TimeoutStopSec=12
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
'''
LAUNCHER = '''#!/bin/bash
exec "$HOME/.local/share/neewer-omarchy/venv/bin/python" "$HOME/.local/share/neewer-omarchy/controller.py" "$@"
'''
HOOK = '''#!/bin/bash
umask 077
mkdir -p "$HOME/.local/state/neewer-omarchy"
timeout 48 "$HOME/.local/bin/neewer-light" hook > "$HOME/.local/state/neewer-omarchy/theme-sync.log" 2>&1 &
'''
STAGE = 'preparing local setup'


def run(args, timeout=20, **kwargs):
    return subprocess.run(args, check=True, timeout=timeout, **kwargs)


def service(action, check=True):
    return subprocess.run(['systemctl', '--user', action, 'neewer-light.service'],
                          check=check, timeout=20, capture_output=True)


def install(home):
    global STAGE
    if sys.version_info < (3, 11):
        raise RuntimeError('Python 3.11 or newer is required.')
    app = home / '.local/share/neewer-omarchy'
    app.mkdir(parents=True, exist_ok=True, mode=0o700)
    app.chmod(0o700)
    with (app / 'setup.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        STAGE = 'checking the user service manager'
        run(['systemctl', '--user', 'show-environment'], capture_output=True)
        environments = app / 'environments'
        environments.mkdir(exist_ok=True, mode=0o700)
        candidate = Path(tempfile.mkdtemp(prefix='runtime-', dir=environments))
        venv = app / 'venv'
        try:
            STAGE = 'creating the private Python environment'
            run([sys.executable, '-m', 'venv', str(candidate)], timeout=60)
            interpreter = candidate / 'bin/python'
            STAGE = 'downloading the Bluetooth dependencies (check internet access)'
            run([str(interpreter), '-m', 'pip', 'install', '--disable-pip-version-check',
                 '--requirement', str(ROOT / 'requirements.txt')], timeout=180)
            run([str(interpreter), '-c', 'import bleak, dbus_fast'])
            commit(app, home, candidate, venv)
        except Exception:
            if candidate.exists() and not (venv.is_symlink() and venv.resolve() == candidate):
                shutil.rmtree(candidate)
            raise


def commit(app, home, candidate, venv):
    global STAGE
    STAGE = 'saving the previous helper'
    unit = home / '.config/systemd/user/neewer-light.service'
    launcher = home / '.local/bin/neewer-light'
    hook = home / '.config/omarchy/hooks/theme-set.d/50-neewer-light'
    marker = app / 'installed-version'
    targets = [*(app / name for name in FILES), unit, launcher, hook, marker]
    backups = app / 'backups'
    backups.mkdir(exist_ok=True, mode=0o700)
    backup = Path(tempfile.mkdtemp(prefix='before-setup-', dir=backups))
    saved = {}
    for index, target in enumerate(targets):
        if target.exists():
            copy = backup / str(index)
            shutil.copy2(target, copy)
            saved[target] = copy
    (backup / 'paths.json').write_text(json.dumps({str(k):v.name for k,v in saved.items()}, indent=2))
    was_active = service('is-active', check=False).returncode == 0
    was_enabled = service('is-enabled', check=False).returncode == 0
    switched = False
    try:
        STAGE = 'updating the local helper'
        if was_active:
            service('stop')
        if venv.exists() or venv.is_symlink():
            venv.rename(backup / 'previous-venv')
        switched = True
        venv.symlink_to(candidate, target_is_directory=True)
        for name in FILES:
            shutil.copy2(ROOT / 'backend' / name, app / name)
            py_compile.compile(str(app / name), doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH)
        for target, content, mode in ((unit, UNIT, 0o644), (launcher, LAUNCHER, 0o755), (hook, HOOK, 0o755)):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            target.chmod(mode)
        STAGE = 'starting the helper (check your active Omarchy theme)'
        run(['systemctl', '--user', 'daemon-reload'])
        run(['systemctl', '--user', 'enable', '--now', 'neewer-light.service'])
        interpreter = candidate / 'bin/python'
        for attempt in range(30):
            status = subprocess.run([str(interpreter), str(app / 'controller.py'), 'status'],
                                    capture_output=True, text=True, timeout=3)
            if status.returncode == 0 and json.loads(status.stdout).get('ok'):
                break
            time.sleep(.2)
        else:
            raise RuntimeError('The light service did not become ready.')
        marker.write_text(json.loads((ROOT / 'manifest.json').read_text())['version'] + '\n')
        print('Light controls are ready. Saved preferences were preserved.')
    except Exception:
        STAGE += '; restoring the previous helper'
        service('stop', check=False)
        if not was_enabled:
            service('disable', check=False)
        for target in targets:
            if target in saved:
                shutil.copy2(saved[target], target)
            else:
                target.unlink(missing_ok=True)
        if switched:
            venv.unlink(missing_ok=True)
            old = backup / 'previous-venv'
            if old.exists() or old.is_symlink():
                old.rename(venv)
        run(['systemctl', '--user', 'daemon-reload'])
        if was_active:
            service('start')
        raise


if __name__ == '__main__':
    try:
        install(Path.home())
    except Exception as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        print('NEEWER_SETUP_ERROR: Setup stopped while ' + STAGE + '.', file=sys.stderr)
        sys.exit(1)
