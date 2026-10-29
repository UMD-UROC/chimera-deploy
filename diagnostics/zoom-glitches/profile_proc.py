#!/usr/bin/env python3
"""Sample process and thread CPU use through procfs."""
import json
import os
import time
from collections import defaultdict


def snapshot():
    result = {}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            command = open(f'/proc/{pid}/cmdline', 'rb').read().replace(b'\0', b' ').decode()
            for tid in os.listdir(f'/proc/{pid}/task'):
                fields = open(f'/proc/{pid}/task/{tid}/stat').read().rsplit(')', 1)[1].split()
                name = open(f'/proc/{pid}/task/{tid}/comm').read().strip()
                result[(pid, tid)] = (int(fields[11]) + int(fields[12]), name, command)
        except (OSError, UnicodeError):
            continue
    return result

start = time.monotonic()
a = snapshot()
time.sleep(10)
b = snapshot()
elapsed = time.monotonic() - start
hz = os.sysconf('SC_CLK_TCK')
processes = defaultdict(float)
threads = []
for key, (ticks, name, command) in b.items():
    if key not in a:
        continue
    cpu = (ticks - a[key][0]) / hz / elapsed * 100
    processes[command] += cpu
    if cpu:
        threads.append(dict(pid=key[0], tid=key[1], name=name, cpu_percent=round(cpu, 2)))
print(json.dumps(dict(unix_time=time.time(), duration=elapsed,
    processes=sorted([dict(command=c, cpu_percent=round(v, 2)) for c, v in processes.items()],
                     key=lambda x: -x['cpu_percent']),
    threads=sorted(threads, key=lambda x: -x['cpu_percent'])), indent=2))
