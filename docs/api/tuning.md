# Fetch tuning :stopwatch:

!!! warning "Experimental"
    This module is experimental. Its names, rules and defaults may change.

fsspec's remote files (s3fs, gcsfs, adlfs, http, ...) put a cache between the
reader and the network. The best cache type and block size depend on how the
reader accesses the file and on the latency and bandwidth of the link, neither
of which the filesystem knows. `upath.tuning` maps an access hint plus a
network profile to `open()` keyword arguments.

## Automatic detection

`UPath.open()` in a read mode detects the access pattern from the file suffix
on filesystems whose files use fsspec's caches (`s3`, `gcs`, `az`/`abfs`, `hf`,
`http`/`https`):

```python
import h5py
from upath import UPath

# .h5ad -> "scattered": hybrid block cache sized from the network profile
with UPath("s3://bucket/atlas.h5ad").open("rb") as f, h5py.File(f) as h5:
    ...

# .parquet -> "planned": no fsspec cache, pyarrow coalesces its own reads
with UPath("s3://bucket/table.parquet").open("rb") as f:
    ...
```

Files with other suffixes, other filesystems, write modes and local paths keep
their previous behavior. Detection never overrides cache settings you choose:

- `cache_type`, `block_size` or `buffering` passed to `open()`, and
- cache options in the path's storage options (`default_cache_type`,
  `default_block_size`, `block_size`, `blocksize`, `cache_type`,
  `cache_options`).

### Opting out

```python
# per call
path.open("rb", access=None)

# per process
import upath.tuning
upath.tuning.set_default_access(None)
```

or set the environment variable `UPATH_FETCH_TUNING=0` (also `false`, `off`,
`no`, `none`) before importing `upath`.

## Explicit hints and network profiles

Pass `access=` to apply a hint on any filesystem, or to override the suffix:

```python
with UPath("s3://bucket/data.bin").open("rb", access="scattered") as f:
    ...
```

`"scattered"` sizes blocks from the bandwidth-delay product of
[`DEFAULT_NETWORK`](#upath.tuning.DEFAULT_NETWORK) (same-region cloud). For
other links, build the options yourself:

```python
from upath.tuning import NetworkProfile, fetch_options

laptop = NetworkProfile(rtt=0.040, bandwidth=12e6)  # 40 ms, 100 Mbit/s
opts = fetch_options("scattered", network=laptop)
with UPath("s3://bucket/atlas.h5ad").open("rb", **opts) as f:
    ...
```

## Access hints

| hint | typical reader | fsspec options |
|---|---|---|
| `"scattered"` | h5py on HDF5 (h5ad, h5, netCDF4, loom) | `upath-hybrid` cache, block = 2 × RTT × bandwidth, clamped to 1–16 MiB |
| `"planned"` | pyarrow on parquet | `cache_type="none"` |
| `"whole"` | reading the entire file | `cache_type="all"` |
| `"auto"` (default) | any | one of the above from the suffix, else filesystem defaults |
| `None` | any | filesystem defaults |

The rules come from benchmarks of GB-scale h5ad and parquet files over simulated
networks; see `dev/access_patterns/` in the repository for the harness and results.

## API

::: upath.tuning.fetch_options
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.get_default_access
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.set_default_access
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
