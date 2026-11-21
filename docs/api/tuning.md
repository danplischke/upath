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

| suffixes | detected access |
|---|---|
| `.h5ad` `.h5mu` `.h5` `.hdf5` `.hdf` `.he5` `.loom` `.nwb` `.nxs` `.nc` `.nc4` | `"scattered"` (HDF5 and netCDF) |
| `.tif` `.tiff` `.fits` `.fit` `.fts` | `"scattered"` (tiled images) |
| `.orc` | `"scattered"` (the ORC reader issues many small reads) |
| `.parquet` `.pq` `.feather` | `"planned"` |

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

## Network detection

The block size for `"scattered"` files depends on the link's bandwidth-delay
product. upath measures it per endpoint (filesystem, storage options and bucket
or host) from the requests its own caches make: small requests are dominated by
the round trip, large ones by the transfer. While an endpoint has no latency
measurement yet, the first large request of a file is split into a 64 KiB
request and the rest (one extra round trip). Until an endpoint is measured,
[`DEFAULT_NETWORK`](#upath.tuning.DEFAULT_NETWORK) (same-region cloud) applies.

```python
from upath.tuning import estimate_network

path = UPath("s3://bucket/atlas.h5ad")
with path.open("rb") as f:  # first open: 4 MiB blocks, measures the link
    ...
print(estimate_network(path))  # e.g. NetworkProfile(rtt=0.041, bandwidth=12.3e6)
with path.open("rb") as f:  # later opens: block size from the estimate
    ...
```

Pin a profile to disable detection:

```python
from upath.tuning import NetworkProfile, set_default_network

set_default_network(NetworkProfile(rtt=0.040, bandwidth=12e6))
```

## Explicit hints and network profiles

Pass `access=` to apply a hint on any filesystem, or to override the suffix:

```python
with UPath("s3://bucket/data.bin").open("rb", access="scattered") as f:
    ...
```

To choose the options for a specific link yourself:

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
| `"scattered"` | h5py on HDF5 (h5ad, NWB, netCDF4), tifffile, astropy, pyarrow ORC | `upath-hybrid` cache, block = 2 × RTT × bandwidth, clamped to 1–4 MiB |
| `"planned"` | pyarrow on parquet and feather | `cache_type="none"` (`upath-none` when detecting the network) |
| `"whole"` | reading the entire file | `cache_type="all"` |
| `"auto"` (default) | any | one of the above from the suffix, else filesystem defaults |
| `None` | any | filesystem defaults |

The rules come from benchmarks of GB-scale h5ad and parquet files and ~300 MB
TIFF, FITS, ORC, feather and netCDF files over simulated networks; see
`dev/access_patterns/` in the repository for the harness and results.

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

::: upath.tuning.estimate_network
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.get_default_network
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false

::: upath.tuning.set_default_network
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

::: upath.tuning.PassthroughCache
    options:
        heading_level: 3
        show_root_heading: true
        show_root_full_path: false
        members: false
        show_bases: true
