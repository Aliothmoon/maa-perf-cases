#!/usr/bin/env python3
"""
Analyze bench_matcher output and print timing distribution.
Usage: python analyze_bench.py bench_result.txt
"""

import re
import sys
from collections import defaultdict

def parse(path):
    pattern = re.compile(
        r'(\S+)\s+min=\s*(\d+)\s+p50=\s*(\d+)\s+p95=\s*(\d+)\s+avg=\s*(\d+)\s+max=\s*(\d+)'
    )
    rows = []
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            m = pattern.search(line)
            if m:
                rows.append({
                    'label': m.group(1),
                    'min':   int(m.group(2)),
                    'p50':   int(m.group(3)),
                    'p95':   int(m.group(4)),
                    'avg':   int(m.group(5)),
                    'max':   int(m.group(6)),
                })
    return rows

def percentile(vals, p):
    vals = sorted(vals)
    if not vals:
        return 0
    idx = int(len(vals) * p / 100)
    return vals[min(idx, len(vals) - 1)]

def histogram(vals, buckets):
    counts = defaultdict(int)
    for v in vals:
        for lo, hi, label in buckets:
            if lo <= v < hi:
                counts[label] += 1
                break
        else:
            counts[f'>={buckets[-1][1]//1000}ms'] += 1
    return counts

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else 'bench_result.txt'
    rows = parse(path)
    if not rows:
        print('no data found')
        return

    avgs = [r['avg'] for r in rows]
    p50s = [r['p50'] for r in rows]
    p95s = [r['p95'] for r in rows]

    n = len(rows)
    print(f'samples: {n}')
    print()

    print('=== avg 分布 (us) ===')
    for p in [50, 75, 90, 95, 99, 100]:
        print(f'  p{p:3d}: {percentile(avgs, p):8d} us  ({percentile(avgs, p)/1000:.2f} ms)')
    print(f'  min: {min(avgs):8d} us  ({min(avgs)/1000:.2f} ms)')
    print(f'  mean:{int(sum(avgs)/n):8d} us  ({sum(avgs)/n/1000:.2f} ms)')
    print()

    # bucket: [lo, hi) us
    ms = 1000
    buckets = [
        (0,       1*ms,   '<1ms'),
        (1*ms,    2*ms,   '1-2ms'),
        (2*ms,    5*ms,   '2-5ms'),
        (5*ms,    10*ms,  '5-10ms'),
        (10*ms,   20*ms,  '10-20ms'),
        (20*ms,   50*ms,  '20-50ms'),
        (50*ms,   100*ms, '50-100ms'),
        (100*ms,  200*ms, '100-200ms'),
        (200*ms,  float('inf'), '>=200ms'),
    ]
    # fix last bucket
    buckets[-1] = (200*ms, 10**9, '>=200ms')

    print('=== avg 耗时区间分布 ===')
    hist = histogram(avgs, buckets)
    for lo, hi, label in buckets:
        c = hist.get(label, 0)
        bar = '#' * (c * 60 // n) if n else ''
        print(f'  {label:>12s}: {c:6d} ({c*100/n:5.1f}%)  {bar}')
    print()

    print('=== TOP 20 最慢样本 (avg) ===')
    top = sorted(rows, key=lambda r: r['avg'], reverse=True)[:20]
    print(f'  {"label":<40s}  {"avg":>8s}  {"p95":>8s}  {"max":>8s}')
    for r in top:
        print(f'  {r["label"]:<40s}  {r["avg"]:>8d}  {r["p95"]:>8d}  {r["max"]:>8d}  us')
    print()

    print('=== p95 分布 (us) ===')
    for p in [50, 75, 90, 95, 99]:
        print(f'  p{p:3d}: {percentile(p95s, p):8d} us  ({percentile(p95s, p)/1000:.2f} ms)')

if __name__ == '__main__':
    main()
