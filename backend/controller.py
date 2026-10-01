#!/usr/bin/env python3
"""Fast local requests to the RGB1 utility; see README.md."""
import argparse
import json
import socket
import subprocess
import sys
import time
from light_config import SOCKET, load, packet, selected


def request(action, value):
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(3)
        client.connect(str(SOCKET))
        client.sendall((json.dumps(dict(action=action, value=value)) + '\n').encode())
        data = b''
        while b'\n' not in data:
            block = client.recv(65536)
            if not block:
                raise RuntimeError('The light service closed its connection.')
            data += block
            if len(data) > 262144:
                raise RuntimeError('Invalid response from the light service.')
        return json.loads(data)


def main():
    parser = argparse.ArgumentParser(description='Your Omarchy light utility.')
    parser.add_argument('action', choices=['status', 'probe', 'theme', 'on', 'off', 'brightness',
        'follow', 'hook', 'role', 'preview', 'mode', 'speed', 'scan', 'select', 'test', 'confirm'])
    parser.add_argument('value', nargs='?')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.dry_run:
        cfg = load()
        if args.action == 'role':
            cfg['role'] = args.value
        theme, roles, colour = selected(cfg)
        print(json.dumps(dict(theme=theme, role=cfg['role'], hex=colour, roles=roles,
            packet=packet(cfg, args.action, colour).hex(' ') if cfg['address'] else None)))
        return
    try:
        result = request(args.action, args.value)
    except (FileNotFoundError, ConnectionRefusedError):
        subprocess.run(['systemctl', '--user', 'start', 'neewer-light.service'],
                       check=True, capture_output=True, timeout=8)
        for attempt in range(15):
            try:
                result = request(args.action, args.value)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if attempt == 14:
                    raise RuntimeError('Light controls are starting. Try again in a moment.')
                time.sleep(0.1)
    print(json.dumps(result))
    if not result.get('ok'):
        sys.exit(1)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        message = 'Unable to start light controls. Open Light setup and try again.' if isinstance(error, subprocess.SubprocessError) else str(error)
        print(json.dumps(dict(ok=False, message=message or 'Light controls are unavailable.')))
        sys.exit(1)
