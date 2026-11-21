"""Generate representative test files for access-pattern tracing."""

import os
import sys
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

# --- AnnData: 50k cells x 2k genes, 5% dense, typical obs/var/obsm ----------
n_obs, n_vars = 50_000, 2_000
X = sp.random(n_obs, n_vars, density=0.05, format="csr", dtype=np.float32, rng=rng)
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

# 1) default anndata write (no compression)
adata.write_h5ad(f"{OUT}/default.h5ad")
# 2) gzip-compressed (common in public atlases, e.g. CELLxGENE / GEO uploads)
adata.write_h5ad(f"{OUT}/gzip.h5ad", compression="gzip")
# 3) writer-side fix: HDF5 paged aggregation -> metadata consolidated in pages
with h5py.File(
    f"{OUT}/paged.h5ad", "w", fs_strategy="page", fs_page_size=4 * 2**20
) as f:
    ad.io.write_elem(f, "/", adata)

# 4) anndata as zarr (v3, consolidated by default)
adata.write_zarr(f"{OUT}/adata.zarr")

# --- plain zarr arrays: 4096^2 float32 = 64 MiB -----------------------------
data = rng.standard_normal((4096, 4096)).astype(np.float32)
z = zarr.create_array(
    f"{OUT}/chunked.zarr",
    shape=data.shape,
    chunks=(256, 256),
    dtype="f4",
    compressors=None,
)
z[:] = data
z = zarr.create_array(
    f"{OUT}/sharded.zarr",
    shape=data.shape,
    chunks=(256, 256),
    shards=(2048, 2048),
    dtype="f4",
    compressors=None,
)
z[:] = data

# --- parquet: 1M rows x 20 cols, 8 row groups --------------------------------
n = 1_000_000
cols = {f"f{i}": rng.random(n) for i in range(16)}
cols |= {f"i{i}": rng.integers(0, 1_000_000, n) for i in range(3)}
cols["s"] = pa.array(rng.choice(["alpha", "beta", "gamma", "delta"], n))
pq.write_table(pa.table(cols), f"{OUT}/table.parquet", row_group_size=125_000)

for name in sorted(os.listdir(OUT)):
    p = f"{OUT}/{name}"
    if os.path.isdir(p):
        size = sum(
            os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(p) for f in fs
        )
        nfiles = sum(len(fs) for _, _, fs in os.walk(p))
        print(f"{name:20s} {size / 2**20:8.1f} MiB  ({nfiles} objects)")
    else:
        print(f"{name:20s} {os.path.getsize(p) / 2**20:8.1f} MiB")
