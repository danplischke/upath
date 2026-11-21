# Fetch tuning :stopwatch:

!!! warning "Experimental"
    This module is experimental. Its names, rules and defaults may change.

fsspec's remote files (s3fs, gcsfs, adlfs, http, ...) put a cache between the
reader and the network. The best cache type and block size depend on how the
reader accesses the file and on the latency and bandwidth of the link, neither
of which the filesystem knows. `upath.tuning` maps an access hint plus a
network profile to `open()` keyword arguments.

```python
from upath import UPath

# h5py reads scattered metadata and chunks
with UPath("s3://bucket/atlas.h5ad").open("rb", access="scattered") as f:
    ...

# pyarrow plans and coalesces its own byte ranges
with UPath("s3://bucket/table.parquet").open("rb", access="planned") as f:
    ...

# guess from the suffix (.h5ad, .h5, .nc, ... -> scattered; .parquet -> planned)
with UPath("s3://bucket/atlas.h5ad").open("rb", access="auto") as f:
    ...
```

`access="scattered"` sizes blocks from the bandwidth-delay product of
[`DEFAULT_NETWORK`](#upath.tuning.DEFAULT_NETWORK) (same-region cloud). For
other links, build the options yourself:

```python
from upath.tuning import NetworkProfile, fetch_options

laptop = NetworkProfile(rtt=0.040, bandwidth=12e6)  # 40 ms, 100 Mbit/s
opts = fetch_options("scattered", network=laptop)
with UPath("s3://bucket/atlas.h5ad").open("rb", **opts) as f:
    ...
```

Explicit `cache_type`, `block_size` or `buffering` arguments to `open()` take
precedence over the hint. Hints are ignored for write modes and for local files.

## Access hints

| hint | typical reader | fsspec options |
|---|---|---|
| `"scattered"` | h5py on HDF5 (h5ad, h5, netCDF4, loom) | `upath-hybrid` cache, block = 2 × RTT × bandwidth, clamped to 1–16 MiB |
| `"planned"` | pyarrow on parquet | `cache_type="none"` |
| `"whole"` | reading the entire file | `cache_type="all"` |
| `"auto"` | any | one of the above from the suffix, else filesystem defaults |

The rules come from benchmarks of GB-scale h5ad and parquet files over simulated
networks; see `dev/access_patterns/` in the repository for the harness and results.

## API

::: upath.tuning.fetch_options
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.guess_access
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.NetworkProfile
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.DEFAULT_NETWORK
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.HybridBlockCache
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false
        members: false
        show_bases: true
