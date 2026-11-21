"""Generate GB-scale test files."""

import os
import sys
import time
import warnings

import anndata as ad
import h5py
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import scipy.sparse as sp
import zarr

warnings.filterwarnings("ignore")
OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(0)
t0 = time.time()


def log(msg):
    print(f"[{time.time() - t0:6.1f}s] {msg}", flush=True)


# --- AnnData: 1M cells x 2k genes, ~100 nnz/cell, integer counts ----------
n_obs, n_vars = 1_000_000, 2_000
counts = rng.poisson(100, n_obs)
indptr = np.zeros(n_obs + 1, np.int64)
np.cumsum(counts, out=indptr[1:])
nnz = int(indptr[-1])
indices = rng.integers(0, n_vars, nnz, dtype=np.int32)
data = rng.geometric(0.3, nnz).astype(np.float32)
X = sp.csr_matrix((data, indices, indptr), shape=(n_obs, n_vars))
obs = pd.DataFrame(
    {
        "cell_type": pd.Categorical(rng.choice([f"ct{i}" for i in range(40)], n_obs)),
        "batch": pd.Categorical(rng.choice([f"b{i}" for i in range(8)], n_obs)),
        "donor": pd.Categorical(rng.choice([f"d{i}" for i in range(120)], n_obs)),
        "n_counts": rng.random(n_obs).astype(np.float32),
        "n_genes": rng.integers(0, 5000, n_obs),
        "pct_mito": rng.random(n_obs).astype(np.float32),
        "leiden": pd.Categorical(rng.integers(0, 30, n_obs).astype(str)),
        "doublet_score": rng.random(n_obs),
    },
    index=[f"cell_{i}" for i in range(n_obs)],
)
var = pd.DataFrame(
    {
        "gene_symbol": [f"G{i}" for i in range(n_vars)],
        "highly_variable": rng.random(n_vars) > 0.8,
        "means": rng.random(n_vars),
    },
    index=[f"ENSG{i:08d}" for i in range(n_vars)],
)
adata = ad.AnnData(
    X=X,
    obs=obs,
    var=var,
    obsm={
        "X_pca": rng.standard_normal((n_obs, 50)).astype(np.float32),
        "X_umap": rng.standard_normal((n_obs, 2)).astype(np.float32),
    },
    uns={"leiden": {"params": {"resolution": 1.0}}},
)
log(f"built AnnData nnz={nnz:,}")
adata.write_h5ad(f"{OUT}/big.h5ad")
log("big.h5ad")
with h5py.File(
    f"{OUT}/big_paged.h5ad", "w", fs_strategy="page", fs_page_size=4 * 2**20
) as f:
    ad.io.write_elem(f, "/", adata)
log("big_paged.h5ad")
adata.write_zarr(f"{OUT}/big_adata.zarr")
log("big_adata.zarr")
del adata, X, data, indices

# --- parquet: 8M rows x 20 cols, 1M-row row groups --------------------------
n = 8_000_000
cols = {f"f{i}": rng.random(n) for i in range(16)}
cols |= {f"i{i}": rng.integers(0, 1_000_000, n) for i in range(3)}
cols["s"] = pa.array(rng.choice(["alpha", "beta", "gamma", "delta"], n))
pq.write_table(pa.table(cols), f"{OUT}/big.parquet", row_group_size=1_000_000)
del cols
log("big.parquet")

# --- zarr arrays: 16384^2 float32 = 1 GiB -----------------------------------
N = 16384
for name, kw in [
    ("z_c256k.zarr", {"chunks": (256, 256)}),
    ("z_c4m.zarr", {"chunks": (1024, 1024)}),
    ("z_shard64m.zarr", {"chunks": (256, 256), "shards": (4096, 4096)}),
]:
    z = zarr.create_array(
        f"{OUT}/{name}", shape=(N, N), dtype="f4", compressors=None, **kw
    )
    for i in range(0, N, 4096):
        z[i : i + 4096, :] = rng.standard_normal((4096, N), dtype=np.float32)
    log(name)

for name in sorted(os.listdir(OUT)):
    p = f"{OUT}/{name}"
    if os.path.isdir(p):
        size = sum(
            os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs
        )
        nf = sum(len(fs) for _, _, fs in os.walk(p))
        print(f"{name:20s} {size / 2**30:6.2f} GiB ({nf} objects)")
    else:
        print(f"{name:20s} {os.path.getsize(p) / 2**30:6.2f} GiB")
