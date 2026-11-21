"""Cost-model tables for results/sweep_other.json: python analyze_other.py [profiles]"""

import json
import sys
from collections import defaultdict

PROFILES = {  # rtt, per-stream bw, rule block (MiB) = clamp(pow2(2*BDP), 1, 16)
    "LAN": (0.0005, 400e6, 1),
    "cloud": (0.020, 100e6, 4),
    "laptop": (0.040, 12e6, 1),
    "x-cont": (0.150, 25e6, 8),
}
rows = json.load(open("results/sweep_other.json"))
by = defaultdict(dict)
for r in rows:
    by[(r["file"], r["workload"])][r["config"]] = r


def T(r, rtt, bw):
    return (r["n_get"] + r["n_meta"]) * rtt + r["bytes"] / bw


def f(x):
    return f"{x:.1f}" if x >= 10 else f"{x:.2f}"


profiles = sys.argv[1:] or ["cloud", "laptop", "x-cont"]
for p in profiles:
    rtt, bw, rb = PROFILES[p]
    print(f"\n### {p}  (seconds, network only)")
    print(
        "| file: workload | needed | s3fs | gcsfs | adlfs | http | none"
        " | hybrid@rule | best |"
    )
    print("|---|---|---|---|---|---|---|---|---|")
    for (fn, w), cfg in by.items():
        need = cfg["none"]["bytes"] / 1e6
        t = {k: T(v, rtt, bw) for k, v in cfg.items()}
        best = min(t, key=t.get)
        print(
            f"| {fn}: {w} | {need:.0f}MB | {f(t['s3fs (readahead/50M)'])} | "
            f"{f(t['gcsfs (readahead/5M)'])} | {f(t['adlfs (bytes/50M)'])} | "
            f"{f(t['http (bytes/5M)'])} | {f(t['none'])} | {f(t[f'hybrid/{rb}M'])} | "
            f"{f(t[best])} ({best}) |"
        )
