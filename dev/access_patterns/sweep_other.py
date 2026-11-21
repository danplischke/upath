"""Trace + cost-model sweep for other formats read through UPath.open().

usage: python sweep_other.py DATA_DIR   (data from make_other.py)
"""

import json
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import pyarrow.feather as feather
import pyarrow.ipc as ipc
import pyarrow.orc as orc
import tifffile
import zarr
from astropy.io import fits
from scipy.io import netcdf_file
from simfs import TRACE

from upath import UPath
from upath.tuning import HybridBlockCache
from upath.tuning import fetch_options

warnings.filterwarnings("ignore")
fetch_options("scattered")  # register the hybrid cache
DATA = os.path.abspath(sys.argv[1])
M = 2**20


def tif_window(f):
    with tifffile.TiffFile(f) as tif:
        z = zarr.open(tif.aszarr(level=0), mode="r")
        z[5000:6024, 5000:6024]


def tif_overview(f):
    with tifffile.TiffFile(f) as tif:
        zarr.open(tif.aszarr(level=2), mode="r")[:]


WORKLOADS = {
    "image.tif": {
        "metadata": lambda f: tifffile.TiffFile(f).series[0].levels,
        "1024x1024 window": tif_window,
        "overview (1/16 px)": tif_overview,
        "full image": lambda f: tifffile.TiffFile(f).asarray(),
    },
    "table.feather": {
        "2 of 20 cols": lambda f: feather.read_table(f, columns=["f3", "i1"]),
        "1 record batch": lambda f: ipc.open_file(f).get_batch(10),
        "full": lambda f: feather.read_table(f),
    },
    "table.orc": {
        "2 of 20 cols": lambda f: orc.ORCFile(f).read(columns=["f3", "i1"]),
        "1 stripe, 2 cols": lambda f: orc.ORCFile(f).read_stripe(
            2, columns=["f3", "i1"]
        ),
        "full": lambda f: orc.ORCFile(f).read(),
    },
    "arrays.npz": {
        "1 of 10 arrays": lambda f: np.load(f)["a3"],
        "all arrays": lambda f: dict(np.load(f)),
    },
    "data.nc": {
        "header": lambda f: list(netcdf_file(f, mmap=False).variables),
        "1 of 10 variables": lambda f: netcdf_file(f, mmap=False)
        .variables["v3"][:]
        .copy(),
    },
    "image.fits": {
        "headers": lambda f: [h.header for h in fits.open(f)],
        "512x512 cutout": lambda f: fits.open(f)[2].section[1000:1512, 2000:2512],
        "1 of 3 HDUs": lambda f: fits.open(f)[2].data.copy(),
    },
    "table.csv.gz": {
        "full (stream)": lambda f: pd.read_csv(f, compression="gzip"),
    },
}

CONFIGS = {
    "none": {"cache_type": "none"},
    "all": {"cache_type": "all"},
    "s3fs (readahead/50M)": {"cache_type": "readahead", "block_size": 50 * M},
    "gcsfs (readahead/5M)": {"cache_type": "readahead", "block_size": 5 * M},
    "adlfs (bytes/50M)": {"cache_type": "bytes", "block_size": 50 * M},
    "http (bytes/5M)": {"cache_type": "bytes", "block_size": 5 * M},
    "readahead/16M": {"cache_type": "readahead", "block_size": 16 * M},
    **{
        f"blockcache/{b}M": {"cache_type": "blockcache", "block_size": b * M}
        for b in (1, 4, 16)
    },
    **{
        f"hybrid/{b}M": {"cache_type": HybridBlockCache.name, "block_size": b * M}
        for b in (1, 4, 8, 16)
    },
}

if __name__ == "__main__":
    out = []
    for fname, workloads in WORKLOADS.items():
        p = UPath(f"simremote://{DATA}/{fname}")
        for wname, fn in workloads.items():
            for cname, okw in CONFIGS.items():
                TRACE.reset()
                t0 = time.perf_counter()
                with p.open("rb", **okw) as f:
                    fn(f)
                gets = [e - s for k, _, s, e in TRACE.events if k == "get"]
                meta = sum(k != "get" for k, *_ in TRACE.events)
                out.append(
                    {
                        "file": fname,
                        "workload": wname,
                        "config": cname,
                        "n_get": len(gets),
                        "n_meta": meta,
                        "bytes": sum(gets),
                        "cpu": time.perf_counter() - t0,
                    }
                )
            print(f"done {fname}: {wname}", file=sys.stderr, flush=True)
    json.dump(out, open("results/sweep_other.json", "w"))
