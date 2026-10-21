#!/usr/bin/env python3
"""Start and collect an onboard C1 PRO daytime comparison."""
import argparse
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import runpy
import shlex
import subprocess
import sys


REMOTE = '/home/user/.local/share/c1-daytest/c1_daytest.py'
RESULTS = '/home/user/c1-daytest-results'
UNIT = 'c1-daytest.service'


def ssh(target, argv, check=True, capture=False):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
                           target, shlex.join(argv)], check=check, text=True,
                          capture_output=capture, timeout=35)


def main():
    source = Path(__file__).resolve().parents[1] / 'remote' / 'c1_daytest.py'
    runner = runpy.run_path(str(source))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['preflight', 'smoke', 'start', 'observe',
                                           'status', 'stop', 'fetch'])
    parser.add_argument('-d', '--drone', default='10.200.142.61')
    parser.add_argument('--seconds', type=float, default=0.4, help='Measurement seconds per value, default 0.4.')
    parser.add_argument('--settle', type=float, default=0.4, help='Settling seconds per value, default 0.4.')
    parser.add_argument('--parameters', type=runner['parameters'], default=list(runner['TOUCHED']),
                        help='Comma-separated controls. The default includes all eight image controls.')
    parser.add_argument('--destination', default=str(Path.home() / 'c1-daytest-results'))
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', args.drone):
        parser.error('Use a host name or IPv4 address.')
    if any(not math.isfinite(value) or not 0.2 <= value <= 120
           for value in (args.seconds, args.settle)):
        parser.error('Measurement and settling seconds must be finite and between 0.2 and 120.')
    target = f'user@{args.drone}'
    if args.action == 'status':
        ssh(target, ['systemctl', '--user', 'status', UNIT, '--no-pager'], check=False)
        ssh(target, ['journalctl', f'_SYSTEMD_USER_UNIT={UNIT}', '-n', '15', '--no-pager'], check=False)
        ssh(target, ['/usr/bin/python3', '-c',
                     'import pathlib; p=sorted(pathlib.Path("/home/user/c1-daytest-results").glob("*/state.json")); '
                     'print(p[-1].read_text() if p else "No test state exists.")'])
        return
    if args.action == 'stop':
        ssh(target, ['systemctl', '--user', 'stop', UNIT])
        return
    if args.action == 'fetch':
        destination = Path(args.destination).resolve()
        destination.mkdir(parents=True, exist_ok=True)
        subprocess.run(['scp', '-r', f'{target}:{RESULTS}/*', str(destination)], check=True)
        print(destination)
        return
    active = ssh(target, ['systemctl', '--user', 'show', UNIT, '-p', 'ActiveState', '--value'],
                 check=False, capture=True)
    if active.returncode == 0 and active.stdout.strip() in ('active', 'activating', 'deactivating'):
        raise RuntimeError('A C1 test is active. Use status or stop first.')
    ssh(target, ['mkdir', '-p', str(Path(REMOTE).parent), RESULTS])
    subprocess.run(['scp', str(source), f'{target}:{REMOTE}.pending'], check=True)
    ssh(target, ['mv', f'{REMOTE}.pending', REMOTE])
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    output = f'{RESULTS}/{stamp}-{args.action}'
    if args.action == 'preflight':
        ssh(target, ['/usr/bin/python3', REMOTE, 'preflight', '--output', output])
        return
    seconds, settle = args.seconds, args.settle
    mode = 'observe' if args.action == 'observe' else 'run'
    blocks = 1 + sum(len(runner['COARSE_VALUES'][key]) for key in args.parameters)
    runtime = math.ceil(blocks * (seconds + settle + 2) + 120)
    if mode == 'observe':
        runtime = seconds + 120
    recovery = shlex.join(['/usr/bin/python3', REMOTE, 'restore', '--output', output])
    ssh(target, ['systemd-run', '--user', '--collect', '--unit', UNIT,
                 '--property', f'RuntimeMaxSec={runtime}',
                 '--property', 'TimeoutStopSec=15',
                 '--property', 'Nice=10', '--property', 'CPUWeight=20',
                 '--property', f'ExecStopPost={recovery}',
                 '--setenv', 'PYTHONUNBUFFERED=1',
                 '/usr/bin/python3', REMOTE, mode, '--output', output,
                 '--seconds', str(seconds), '--settle', str(settle),
                 '--parameters', ','.join(args.parameters),
                 '--interval', '0.4', '--image-interval', '0.4'])
    print(f'Results: {target}:{output}')
    print('The test runs onboard after SSH disconnects. Use status, stop, or fetch.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, subprocess.SubprocessError) as error:
        print(f'C1 test command failed: {error}', file=sys.stderr)
        sys.exit(1)
