#!/usr/bin/env python3
"""P1 resource sampler (docs/preregistration/P1-performance.md): one JSON line every 0.5 s until stopped.

    sample.py OUT.jsonl

Per line: the system CPU share and RAM in use (/proc), the GPU memory, utilisation, power and temperature
(nvidia-smi), and RSS and CPU share for two process groups: `ollama` (the model server and its runners) and
`aries` (any python process whose command line names aries or uvicorn). No dependency beyond the standard
library; reads nothing but counters."""
import json
import os
import signal
import subprocess
import sys
import time

PERIOD = 0.5
TICK = os.sysconf('SC_CLK_TCK')
PAGE_MB = os.sysconf('SC_PAGE_SIZE') / 2**20
GROUPS = {'ollama': lambda cmd: 'ollama' in cmd[:1][0] if cmd else False,
          'aries': lambda cmd: bool(cmd) and 'python' in cmd[0] and any('aries' in c or 'uvicorn' in c for c in cmd)}


def cpu_total():
    with open('/proc/stat') as f:
        parts = [int(x) for x in f.readline().split()[1:]]
    idle = parts[3] + parts[4]
    return sum(parts), idle


def mem_used_mb():
    info = {}
    with open('/proc/meminfo') as f:
        for line in f:
            k, v = line.split(':', 1)
            info[k] = int(v.split()[0])
    return round((info['MemTotal'] - info['MemAvailable']) / 1024, 1)


def processes():
    out = {g: {'rss_mb': 0.0, 'ticks': 0, 'n': 0} for g in GROUPS}
    for pid in os.listdir('/proc'):
        if not pid.isdigit():
            continue
        try:
            with open(f'/proc/{pid}/cmdline', 'rb') as f:
                cmd = [c.decode(errors='ignore') for c in f.read().split(b'\0') if c]
            with open(f'/proc/{pid}/stat') as f:
                st = f.read().rsplit(')', 1)[1].split()
        except OSError:
            continue
        for g, match in GROUPS.items():
            if match(cmd):
                out[g]['rss_mb'] += int(st[21]) * PAGE_MB
                out[g]['ticks'] += int(st[11]) + int(st[12])
                out[g]['n'] += 1
                break
    return out


def gpu():
    try:
        line = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,utilization.gpu,power.draw,temperature.gpu',
                               '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5).stdout
        mem, util, power, temp = (x.strip() for x in line.splitlines()[0].split(','))
        return {'gpu_mem_mb': float(mem), 'gpu_util_pct': float(util), 'gpu_power_w': float(power),
                'gpu_temp_c': float(temp)}
    except Exception as exc:
        return {'gpu_error': type(exc).__name__}


def main():
    out = open(sys.argv[1], 'x')
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: stop.append(1))
    signal.signal(signal.SIGINT, lambda *_: stop.append(1))
    ncpu = os.cpu_count()
    t_prev, (tot_prev, idle_prev), p_prev = time.monotonic(), cpu_total(), processes()
    out.write(json.dumps({'header': True, 'period_s': PERIOD, 'cpus': ncpu, 'started_at': time.time()}) + '\n')
    while not stop:
        time.sleep(PERIOD)
        t, (tot, idle), p = time.monotonic(), cpu_total(), processes()
        wall_ticks = (t - t_prev) * TICK
        row = {'t': round(time.time(), 3),
               'cpu_pct': round(100 * (1 - (idle - idle_prev) / max(tot - tot_prev, 1)), 1),
               'mem_used_mb': mem_used_mb(), **gpu()}
        for g in GROUPS:
            row[g] = {'rss_mb': round(p[g]['rss_mb'], 1), 'n': p[g]['n'],
                      # share of one core; 100 = one core fully busy
                      'cpu_pct': round(100 * max(p[g]['ticks'] - p_prev[g]['ticks'], 0) / max(wall_ticks, 1e-9), 1)}
        out.write(json.dumps(row) + '\n')
        out.flush()
        t_prev, tot_prev, idle_prev, p_prev = t, tot, idle, p
    out.close()


if __name__ == '__main__':
    main()
