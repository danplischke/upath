# Access patterns and fetch tuning benchmarks

Benchmarks behind `upath.tuning` (used by `UPath.open()` on cloud and HTTP
paths): how common scientific formats (h5ad/HDF5, parquet, zarr) access remote
files, and which fsspec fetch settings work best for a given network.

All reads go through `UPath` against `SimRemoteFS` (`simfs.py`), a fake remote
filesystem whose files subclass `fsspec.spec.AbstractBufferedFile` exactly like
s3fs, gcsfs, adlfs and http do, so fsspec's real cache classes sit between the
reader and every logged request. `AsyncSimFS` is the async (s3fs-like) variant
used for zarr. `netsim.py` adds a real-time network: each request sleeps for
the round trip time, then transfers at the per-stream bandwidth while reserving
time on a shared link of fixed aggregate capacity.

## Files

| file | what it does |
|---|---|
| `simfs.py`, `netsim.py` | tracing fake remote filesystems and the network simulator |
| `make_data.py` / `make_big.py` | generate ~50 MB / ~1 GB test files (h5ad, paged h5ad, AnnData zarr, zarr arrays, parquet) |
| `workloads.py`, `characterize.py` | small-file workloads; print the raw access pattern of each (`cache_type="none"`) |
| `sweep.py`, `analyze.py` | small files: every cache type x block size, cost model only |
| `zarr_concurrency.py` | small zarr arrays: read time vs `async.concurrency` |
| `bench_big.py` | GB files, real-time simulated network: shipped defaults vs alternatives, per network profile |
| `zarr_big.py` | GB zarr arrays and AnnData-on-zarr, real-time: concurrency 10 vs formula vs 64 |
| `analyze_big.py` | summary tables from `results/*.jsonl` |
| `make_other.py`, `sweep_other.py`, `analyze_other.py` | ~300 MB TIFF, FITS, ORC, feather, npz, netCDF3, CSV.gz files: cost-model sweep |
| `detect_network.py` | real-time check of `upath.tuning`'s network detection vs a pinned 4 MiB default |
| `results/` | raw results (`*.jsonl`, `sweep_small.json`) and summaries (`summary_*.md`) |

## Running

Requires `anndata h5py zarr>=3 pyarrow pandas scipy` (used: anndata 0.13.4,
h5py 3.16.0, zarr 3.4.2, pyarrow 26.0.1, fsspec 2025.10.0). Run from this
directory; generated data goes into `data/` and `bigdata/` (git-ignored,
~0.5 GB and ~6.6 GB).

```bash
python make_data.py data && python characterize.py data && python sweep.py data && python analyze.py best
python make_big.py bigdata
python bench_big.py bigdata "cloud same-region" results/files_cloud_same_region.jsonl
BUDGET=60 python bench_big.py bigdata "laptop->cloud" results/files_laptop__cloud_h5ad.jsonl h5ad
BUDGET=60 python bench_big.py bigdata "cloud same-region" results/hybrid_cloud_same_region.jsonl hybrid
python zarr_big.py bigdata results/zarr.jsonl
python analyze_big.py files bytes model zarr
```

`bench_big.py` takes a profile name from `netsim.PROFILES`, an output file and an
optional part (`h5ad`, `rest`, `hybrid`); `BUDGET` caps each run in seconds.
Real-time runs are slow on the laptop and cross-continent profiles (20-40 min).

## Network profiles

| profile | RTT | per-stream | link |
|---|---|---|---|
| LAN/HPC | 0.5 ms | 400 MB/s | 1.25 GB/s |
| cloud same-region | 20 ms | 100 MB/s | 1.25 GB/s |
| laptop->cloud | 40 ms | 12 MB/s | 12 MB/s |
| cross-continent | 150 ms | 25 MB/s | 100 MB/s |

## Results (GB files, real-time simulated network)

Seconds; shipped s3fs default (`readahead`, 50 MiB) and gcsfs default
(`readahead`, 5 MiB) vs the rule in `upath.tuning` (h5ad: `upath-hybrid` with
block = 2 x RTT x bandwidth clamped to 1-16 MiB; parquet: `cache_type="none"`),
with the best of all tested configs in brackets. Runs were capped at 150 s
(LAN, cloud) or 60 s (laptop, cross-continent).

| workload | cloud | laptop | cross-continent |
|---|---|---|---|
| h5ad obs+var (78 MB needed) | s3fs 11.8, gcsfs 14.2 -> **2.68** (1.94) | >60, >60 -> **11.0** (9.5) | 45.3, >60 -> **6.3** (6.0) |
| h5ad obsm X_pca, 200 MB contiguous | 7.19, 3.17 -> **2.76** (2.65) | 53.2, 21.4 -> **17.8** (17.7) | 27.3, 11.9 -> **10.8** (9.5) |
| h5ad 2k-row slice | 7.44, 1.40 -> **0.86** (0.59) | 58.2, 8.67 -> **2.29** (2.29) | 30.3, 6.93 -> **5.1** (3.6) |
| h5ad 256 random rows | 17.6, 14.7 -> 12.5 (10.4) | >60, >60 -> >60 (36.8) | >60, >60 -> 50.3 (42.6) |
| h5ad full load, 1.09 GB | 38.3, 32.4 -> **20.4** (15.1) | - | - |
| parquet 2 of 20 cols | 5.42, 2.45 -> **1.51** (best) | 40.8, 17.0 -> **9.85** (best) | 21.1, 10.8 -> **7.11** (best) |
| parquet 1 row group, 2 cols | 1.40, 0.35 -> **0.23** (best) | 10.2, 2.20 -> **1.33** (best) | 5.56, 1.60 -> **1.17** (best) |

Full tables: `results/summary_rule.md`, `results/summary_files.md`,
`results/summary_zarr.md`.

Observations:

- HDF5 seeks backwards (about a third of its metadata reads), which makes a
  single-window `readahead` cache refetch its whole window. With the shipped
  defaults, reading 78 MB of obs/var from a 1 GB h5ad downloads 0.94-1.07 GB;
  a full load with the s3fs default downloads 3.3 GB.
- `blockcache` handles scattered small reads well but splits large contiguous
  reads into sequential block-sized requests (X_pca: 12.3 s vs 2.65 s on
  cloud). `upath-hybrid` sends reads of at least one block as one request.
- pyarrow plans and coalesces its own reads; any fsspec cache only over-fetches.
- Random rows from a remote h5ad cannot be fixed by fetch settings: h5py reads
  through a file object one request at a time. AnnData stored as zarr reads the
  same 256 rows in 0.83 s (cloud) / 3.2 s (cross-continent) / 15.8 s (laptop).
- HDF5 paged aggregation (`fs_strategy="page"`) helps metadata reads on small
  files but is neutral to harmful at 1 GB (2k-row slice on laptop: 28 s vs 2.3 s).
- The serial cost model `requests x RTT + bytes / bandwidth + CPU` predicts the
  measured wall time with median ratio 1.00 (p10 0.93, p90 1.01, 187 runs).

Zarr never uses fsspec file objects (`FsspecStore` calls `cat_file` per chunk),
so `cache_type`/`block_size` have no effect; `zarr.config["async.concurrency"]`
does. Full 1 GiB read of 256 KiB chunks: cloud 11.2 s at the default of 10 vs
1.30 s at 108; cross-continent 72.7 s vs 11.5 s at 64; laptop unchanged
(link-bound). In-flight requests needed to fill a link are roughly
`link_bw x (rtt + chunk / stream_bw) / chunk`; never set it below 10 (LAN got
slower at 6). Sharded arrays coalesce inner-chunk reads (81 chunks -> 11 GETs)
and are insensitive to concurrency.

## Other formats

`sweep_other.py` traces readers that take file objects on ~300 MB files and
prices each config with the cost model above. Speedup of what `UPath.open()`
applies by default (4 MiB hybrid blocks, or `none` for feather) over the s3fs
and gcsfs defaults, geometric mean over workloads, range over the four
profiles:

| format (reader) | vs s3fs default | vs gcsfs default | mapped |
|---|---|---|---|
| ORC (pyarrow) | 3.2-5.5x | 6.6-7.5x | `scattered` |
| tiled TIFF / COG (tifffile) | 2.9-4.6x | 1.1x | `scattered` |
| FITS (astropy) | 3.3-5.0x | 1.0-1.1x | `scattered` |
| netCDF3 (scipy) | 3.3-3.5x | 1.3x | `scattered` (`.nc`) |
| feather (pyarrow) | 1.4-3.6x | 1.0-1.8x | `planned` |
| npz (numpy) | 1.0-1.6x | 0.9x | not mapped |
| CSV.gz (pandas, streaming) | 0.6-1.0x | 0.9-1.0x | not mapped |

Sequential streams are served best by fsspec's defaults, so unknown suffixes
keep them.

Block-size rule, priced on all traces (gap to the best tested config,
geometric mean / worst, over workloads x four profiles):

| rule | h5ad | TIFF, FITS, ORC, netCDF |
|---|---|---|
| fixed 4 MiB | 1.41 / 4.01 | 1.39 / 11.05 |
| 2 x BDP, 1-16 MiB | 1.24 / 2.84 | 1.20 / 3.26 |
| 2 x BDP, 1-4 MiB (used) | 1.28 / 2.84 | 1.15 / 3.26 |

The 4 MiB cap also bounds hybrid cache memory to 32 x 4 MiB per open file.

## Network detection

`detect_network.py` opens a sequence of files (h5ad obs+var, two 2k-row slices,
a parquet row group, obs+var again) through the real-time simulated network,
once with detection and once with `DEFAULT_NETWORK` pinned (4 MiB blocks):

| profile | true RTT / bandwidth | estimate after first file | blocks | 2k-row slices | obs+var again |
|---|---|---|---|---|---|
| LAN/HPC | 0.5 ms / 400 MB/s | 0.64-0.73 ms / 324-375 MB/s | 1 MiB | 0.07 s vs 0.17 s | 0.99 s vs 0.94 s |
| cloud same-region | 20 ms / 100 MB/s | 20.2 ms / 93-95 MB/s | 4 MiB | same | same |
| laptop->cloud | 40 ms / 12 MB/s | 40.3 ms / 11.9-12.0 MB/s | 1 MiB | 2.3 / 2.0 s vs 5.1 / 4.3 s | 10.4 s vs 9.3 s |
| cross-continent | 150 ms / 25 MB/s | 150.2 ms / 24.6-24.9 MB/s | 4 MiB (cap) | same | same |

The first open of an endpoint costs one or two extra round trips (latency
probe). Results: `results/detect_*.jsonl`.

## Caveats

Synthetic data (random sparse counts; parquet columns are random floats and
barely compress). The simulated network has no latency jitter, throttling or
TCP slow start. Benchmark processes for different profiles ran concurrently;
they mostly sleep (load ~0.3), but CPU-heavy steps may be slightly inflated.
h5ad and parquet were benchmarked in real time; TIFF, FITS, ORC, feather and
netCDF3 with the cost model only; `.nwb`, `.nxs` and the other HDF5 suffixes
in `upath.tuning._SUFFIX_HINTS` are mapped by format family.
