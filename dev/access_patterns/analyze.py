import json
import sys
from collections import defaultdict

d = json.load(open("results/sweep_small.json"))
R = d["results"]
P = d["profiles"]
S = d["shipped"]
M = 2**20


def lbl(r):
    bs = r["block_size"]
    return r["cache_type"] + (
        f"/{bs // 1024}K" if bs and bs < M else f"/{bs // M}M" if bs else ""
    )


def cost(r, rtt, bw):
    return (r["n_get"] + r["n_meta"]) * rtt + r["bytes"] / bw


by = defaultdict(list)
for r in R:
    by[r["workload"]].append(r)
mode = sys.argv[1] if len(sys.argv) > 1 else "best"
if mode == "best":
    for pname, (rtt, bw) in P.items():
        print(f"\n### {pname}")
        print(
            f"{'workload':34s} {'best config':24s} {'T_best':>7s} | "
            f"{'s3fs':>6s} {'gcsfs':>6s} {'adlfs':>6s} {'http':>6s}"
            "  (x slower than best)"
        )
        for w, rs in by.items():
            best = min(rs, key=lambda r: cost(r, rtt, bw))
            tb = cost(best, rtt, bw)
            outs = []
            for ct, bs in S.values():
                r = next(
                    r for r in rs if r["cache_type"] == ct and r["block_size"] == bs
                )
                outs.append(f"{cost(r, rtt, bw) / tb:6.1f}")
            print(f"{w:34s} {lbl(best):24s} {tb:6.2f}s | {' '.join(outs)}")
elif mode == "detail":
    w = sys.argv[2]
    rtt, bw = P[sys.argv[3]] if len(sys.argv) > 3 else (0.02, 100e6)
    rs = sorted(by[w], key=lambda r: cost(r, rtt, bw))
    for r in rs:
        print(
            f"{lbl(r):24s} gets={r['n_get']:6d} bytes={r['bytes'] / M:8.1f}M  "
            f"T={cost(r, rtt, bw):7.2f}s"
        )
