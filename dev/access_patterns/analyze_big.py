"""Summarize the real-time simulated-network results."""

import glob
import json
import sys
from collections import defaultdict

PROFILES = ["LAN/HPC", "cloud same-region", "laptop->cloud", "cross-continent"]
SHORT = {
    "LAN/HPC": "LAN",
    "cloud same-region": "cloud",
    "laptop->cloud": "laptop",
    "cross-continent": "x-cont",
}
SHIPPED = ["s3fs default", "gcsfs default", "adlfs default", "http default"]


def load(pattern):
    rows = []
    for f in glob.glob(pattern):
        rows += [json.loads(line) for line in open(f)]
    return rows


def t(r):
    return float("inf") if r["timeout"] or r.get("error") else r["wall"]


def fmt(x):
    return "capped" if x == float("inf") else f"{x:.1f}" if x >= 10 else f"{x:.2f}"


def files():
    rows = load("results/files_*.jsonl") + load("results/hybrid_*.jsonl")
    by = defaultdict(dict)
    for r in rows:
        by[(r["workload"], r["profile"])][r["config"]] = r
    workloads = list(dict.fromkeys(r["workload"] for r in rows))
    print("## File-object workloads: wall seconds (real sleeps)\n")
    for p in PROFILES:
        print(f"### {p}")
        print(
            "| workload | needed | s3fs | gcsfs | adlfs | http | none | bc/1M | bc/16M"
            " | auto | hybrid@auto | best (config) |"
        )
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for w in workloads:
            cfg = by.get((w, p))
            if not cfg or w.startswith("paged"):
                continue
            need = cfg["LOCAL (no network)"]["bytes"] / 1e6
            nets = {k: v for k, v in cfg.items() if k != "LOCAL (no network)"}
            best_k = min(nets, key=lambda k: t(nets[k]))
            autos = [k for k, v in nets.items() if v.get("is_auto")]
            a = t(nets[autos[0]]) if autos else None
            cells = [
                fmt(t(nets[k])) if k in nets else "-"
                for k in SHIPPED + ["none", "blockcache/1M", "blockcache/16M"]
            ]
            a_s = f"{fmt(a)} ({autos[0]})" if autos else "-"
            hy = [k for k, v in nets.items() if v.get("is_hybrid_auto")]
            h_s = f"{fmt(t(nets[hy[0]]))} ({hy[0]})" if hy else "-"
            print(
                f"| {w} | {need:.0f}MB | "
                + " | ".join(cells)
                + f" | {a_s} | {h_s} | {fmt(t(nets[best_k]))} ({best_k}) |"
            )
        print()
    print("### paged h5ad (writer fix) vs default layout, best config each")
    print(
        "| profile | workload | default-layout best"
        " | paged, page_buf 16M | paged, page_buf 64M |"
    )
    print("|---|---|---|---|---|")
    for p in PROFILES:
        for w in ["obs+var", "X rows slice 2k", "X rows random 256"]:
            d = by.get((f"h5ad: {w}", p), {})
            pg = by.get((f"paged h5ad: {w}", p), {})
            if not d or not pg:
                continue
            db = min((v for k, v in d.items() if k != "LOCAL (no network)"), key=t)
            p16, p64 = pg["none, page_buf 16M"], pg["none, page_buf 64M"]
            print(
                f"| {SHORT[p]} | {w} | {fmt(t(db))} ({db['config']}) | "
                f"{fmt(t(p16))} ({p16['n_get']} GETs) | "
                f"{fmt(t(p64))} ({p64['n_get']} GETs) |"
            )


def bytes_table():
    rows = load("results/files_*.jsonl") + load("results/hybrid_*.jsonl")
    print("\n## Bytes fetched (MB), cloud same-region\n")
    by = defaultdict(dict)
    for r in rows:
        if r["profile"] == "cloud same-region":
            by[r["workload"]][r["config"]] = r
    for w, cfg in by.items():
        if w.startswith("paged"):
            continue
        need = cfg["LOCAL (no network)"]["bytes"] / 1e6
        parts = [
            f"{k.replace(' default', '')}={v['bytes'] / 1e6:.0f}/{v['n_get']}"
            for k, v in cfg.items()
            if k != "LOCAL (no network)"
        ]
        print(f"- {w} (needs {need:.0f}MB): " + ", ".join(parts))


def model_check():
    rows = [
        r
        for r in load("results/files_*.jsonl")
        if r["config"] != "LOCAL (no network)"
        and not r["timeout"]
        and not r.get("error")
    ]
    import numpy as np

    ratios = np.array(
        [r["wall"] / (r["model"] + r["cpu"]) for r in rows if r["model"] > 0.5]
    )
    print(
        f"\nmodel check: wall / (network model + cpu) over {len(ratios)} runs: "
        f"median {np.median(ratios):.2f}, p10 {np.percentile(ratios, 10):.2f}, "
        f"p90 {np.percentile(ratios, 90):.2f}"
    )


def zarr_tbl():
    rows = load("results/zarr.jsonl")
    print("\n## zarr: wall seconds by concurrency (real sleeps)\n")
    by = defaultdict(dict)
    for r in rows:
        by[(r["workload"], r["profile"])][r["concurrency"]] = r
    print("| workload | profile | C=10 (default) | C=64 | C* formula | GETs | MB |")
    print("|---|---|---|---|---|---|---|")
    for (w, p), cs in by.items():
        r10 = cs.get(10)
        cstar = next((r["c_star"] for r in cs.values() if r["c_star"]), None)
        star = f"{fmt(t(cs[cstar]))} (C={cstar})" if cstar and cstar in cs else "-"
        print(
            f"| {w} | {SHORT[p]} | {fmt(t(r10))} | {fmt(t(cs[64]))} | {star} "
            f"| {r10['n_get']} | {r10['bytes'] / 1e6:.0f} |"
        )


if __name__ == "__main__":
    what = sys.argv[1:] or ["files", "bytes", "model", "zarr"]
    if "files" in what:
        files()
    if "bytes" in what:
        bytes_table()
    if "model" in what:
        model_check()
    if "zarr" in what:
        zarr_tbl()
