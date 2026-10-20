#!/usr/bin/env python3
"""Share aircraft identity and atomic environment updates across native services."""
import argparse
import os
from pathlib import Path
import re
import shlex
import stat
import tempfile

HOST_ENV = Path('/etc/environment')
LEGACY_MODELS = {'1': 'v3', '2': 'v3', '3': 'v2', '4': 'v2'}


def read_env(path, missing_ok=False):
    """Read assignments without shell evaluation or variable expansion."""
    try:
        lines = Path(path).read_text().splitlines()
    except FileNotFoundError:
        if missing_ok:
            return {}
        raise
    values = {}
    for line in lines:
        key, separator, value = line.strip().removeprefix('export ').partition('=')
        if separator and re.fullmatch(r'[A-Z_][A-Z0-9_]*', key):
            values[key] = ' '.join(shlex.split(value, comments=True))
    return values


def aircraft_identity(host=None):
    """Use the host declaration, with the existing number rule for older hosts."""
    host = read_env(HOST_ENV) if host is None else host
    number = host.get('UAS_NUM', '')
    if not re.fullmatch('[1-9]', number):
        raise RuntimeError('UAS_NUM must be 1 to 9 in /etc/environment')
    model = host.get('CHIMERA_MODEL') or LEGACY_MODELS.get(number)
    if model not in {'v2', 'v3'}:
        raise RuntimeError('CHIMERA_MODEL must be v2 or v3 in /etc/environment')
    return {'UAS_NUM': number, 'UAS_MODEL': model}


def selected_cameras():
    """Apply day/night isolation from the selector, independent of derived fields."""
    host = read_env(HOST_ENV, missing_ok=True)
    env_file = Path.home() / 'px4-sim-stack' / '.env'
    values = read_env(env_file, missing_ok=not bool(host.get('UAS_NUM')))
    aircraft = 'aircraft' in values.get('COMPOSE_PROFILES', '').split(',')
    if not host.get('UAS_NUM'):
        if not aircraft or values.get('UAS_BASE') != '0':
            return None
        raise RuntimeError('Aircraft configuration requires UAS_NUM in /etc/environment')
    identity = aircraft_identity(host)
    if not aircraft or values.get('UAS_BASE') != '0':
        raise RuntimeError('Aircraft .env requires COMPOSE_PROFILES=aircraft and UAS_BASE=0')
    if identity['UAS_MODEL'] != 'v3':
        return None
    camera = values.get('ONBOARD_CAMERA') or 'rgb'
    if camera not in {'rgb', 'thermal'}:
        raise RuntimeError(f'Invalid ONBOARD_CAMERA={camera!r}')
    return frozenset({'pilot', camera})


def update_env(path, updates):
    """Replace assignments together, preserve other text, and remove duplicate keys."""
    path = Path(path)
    for key, value in updates.items():
        if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', key):
            raise ValueError(f'Invalid environment key: {key!r}')
        if any(char in value for char in '\n\r'):
            raise ValueError(f'Invalid newline in {key}')
    original = path.read_text()
    lines, seen = [], set()
    for line in original.splitlines(keepends=True):
        key = line.strip().removeprefix('export ').partition('=')[0]
        if key in updates:
            if key not in seen:
                lines.append(f'{key}={shlex.quote(updates[key])}\n')
                seen.add(key)
        else:
            lines.append(line)
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    lines.extend(f'{key}={shlex.quote(value)}\n' for key, value in updates.items() if key not in seen)
    replacement = ''.join(lines)
    if replacement == original:
        return False
    attributes = path.stat()
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            os.fchmod(stream.fileno(), stat.S_IMODE(attributes.st_mode))
            if (attributes.st_uid, attributes.st_gid) != (os.getuid(), os.getgid()):
                os.fchown(stream.fileno(), attributes.st_uid, attributes.st_gid)
            stream.write(replacement)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', action='store_true')
    parser.add_argument('--update-env', type=Path)
    parser.add_argument('--repair-identity', action='store_true')
    parser.add_argument('assignments', nargs='*')
    args = parser.parse_args()
    try:
        if args.identity:
            host = read_env(HOST_ENV)
            values = aircraft_identity(host)
            values['DECLARED_MODEL'] = host.get('CHIMERA_MODEL', '')
            print(' '.join(f'{key}={shlex.quote(value)}' for key, value in values.items()))
        if args.update_env:
            if len(args.assignments) % 2:
                raise ValueError('Environment updates require KEY VALUE pairs')
            updates = dict(zip(args.assignments[::2], args.assignments[1::2]))
            if args.repair_identity:
                updates.update(aircraft_identity())
            print(int(update_env(args.update_env, updates)))
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(1, f'Aircraft configuration: {error}\n')


if __name__ == '__main__':
    main()
