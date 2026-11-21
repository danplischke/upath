"""Realistic read workloads, all driven through UPath."""

from __future__ import annotations

import warnings

import anndata as ad
import h5py
import numpy as np
import pyarrow.parquet as pq
import simfs  # noqa: F401  (registers simremote://)
import zarr

from upath import UPath

warnings.filterwarnings("ignore")

IDX = np.sort(np.random.default_rng(1).choice(50_000, 1000, replace=False))


def root(data_dir):
    return UPath(f"simremote://{data_dir}")


# ---------------- h5ad via h5py on an fsspec file object -------------------
def _h5(fn):
    def run(p: UPath, okw: dict):
        with p.open("rb", **okw) as f, h5py.File(f, "r") as h:
            fn(h)

    return run


H5AD = {
    # "what's in this file?" -- obs/var dataframes only (cell-type picker, QC UIs)
    "obs+var": _h5(lambda h: (ad.io.read_elem(h["obs"]), ad.io.read_elem(h["var"]))),
    # 1000 random cells from sparse X (indptr then scattered row slices)
    "X rows (random 1k)": _h5(lambda h: ad.io.sparse_dataset(h["X"])[IDX]),
    # contiguous block of 2000 cells
    "X rows (slice 2k)": _h5(lambda h: ad.io.sparse_dataset(h["X"])[20_000:22_000]),
    # full load (ad.read_h5ad equivalent)
    "full load": _h5(lambda h: ad.io.read_elem(h)),
}


# ---------------- parquet via pyarrow on an fsspec file object -------------
def _pq(fn):
    def run(p: UPath, okw: dict):
        with p.open("rb", **okw) as f:
            fn(f)

    return run


PARQUET = {
    "footer only": _pq(lambda f: pq.ParquetFile(f).metadata),
    "2 of 20 cols": _pq(lambda f: pq.read_table(f, columns=["f3", "i1"])),
    "1 rowgroup, 2 cols": _pq(
        lambda f: pq.ParquetFile(f).read_row_group(3, columns=["f3", "i1"])
    ),
    "full read": _pq(lambda f: pq.read_table(f)),
}


# ---------------- zarr via FsspecStore.from_upath ---------------------------
ZARR = {
    "anndata obs+var": lambda r: (
        g := zarr.open_group(r / "adata.zarr", mode="r"),
        ad.io.read_elem(g["obs"]),
        ad.io.read_elem(g["var"]),
    ),
    "anndata X rows (random 1k)": lambda r: ad.io.sparse_dataset(
        zarr.open_group(r / "adata.zarr", mode="r")["X"]
    )[IDX],
    "chunked: 512x512 region": lambda r: zarr.open_array(r / "chunked.zarr", mode="r")[
        1000:1512, 1000:1512
    ],
    "chunked: full array": lambda r: zarr.open_array(r / "chunked.zarr", mode="r")[:],
    "sharded: 512x512 region": lambda r: zarr.open_array(r / "sharded.zarr", mode="r")[
        1000:1512, 1000:1512
    ],
    "sharded: full array": lambda r: zarr.open_array(r / "sharded.zarr", mode="r")[:],
}
