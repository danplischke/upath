"""Access-pattern based fetch tuning for remote file reads (experimental).

fsspec's buffered remote files (s3fs, gcsfs, adlfs, http, ...) put a cache
between the reader and the network.  Which cache type and block size work
well depends on two things the filesystem cannot know on its own:

1. how the reader accesses the file (its *access pattern*), and
2. the latency and bandwidth of the link (its *bandwidth-delay product*).

A block should be large enough that the round trip it saves is worth the
extra bytes it may over-fetch: roughly ``rtt * bandwidth``. Smaller blocks
pay too many round trips; larger blocks download bytes nobody asked for.

This module maps an access hint plus a :class:`NetworkProfile` to keyword
arguments for ``UPath.open()`` / ``fs.open()``.

By default, ``UPath.open()`` in a read mode detects the access pattern from
the file suffix (``.h5ad``, ``.h5``, ``.nc``, ... -> ``"scattered"``;
``.parquet`` -> ``"planned"``) on filesystems whose files use fsspec's
caches (s3, gcs, azure, hf, http). Explicit ``cache_type``, ``block_size`` or
``buffering`` arguments and cache settings in the path's storage options are
left untouched. To opt out:

- per call: ``path.open("rb", access=None)``
- per process: ``upath.tuning.set_default_access(None)``
- per environment: ``UPATH_FETCH_TUNING=0``

The rules come from benchmarks on GB-scale h5ad and parquet files over
simulated networks (see ``dev/access_patterns/`` in the repository).
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import Literal
from typing import get_args

from fsspec.caching import BlockCache
from fsspec.caching import caches
from fsspec.caching import register_cache

from upath.types import UNSET_DEFAULT

__all__ = [
    "AccessHint",
    "NetworkProfile",
    "DEFAULT_NETWORK",
    "HybridBlockCache",
    "fetch_options",
    "guess_access",
    "get_default_access",
    "set_default_access",
]

# How a reader accesses a file, see fetch_options() for the meaning of each hint.
AccessHint = Literal["auto", "scattered", "planned", "whole"]

_MiB = 2**20
_MIN_BLOCK = 1 * _MiB
_MAX_BLOCK = 16 * _MiB

# storage options with which a user configures fsspec's file caching on the
# filesystem itself; automatic tuning never overrides them
_FS_CACHE_OPTIONS = frozenset(
    {
        "cache_type",
        "cache_options",
        "block_size",
        "blocksize",
        "default_cache_type",
        "default_block_size",
    }
)

_SUFFIX_HINTS: dict[str, AccessHint] = {
    # HDF5 containers: metadata B-tree walks + chunk-sized reads
    ".h5ad": "scattered",
    ".h5mu": "scattered",
    ".h5": "scattered",
    ".hdf5": "scattered",
    ".hdf": "scattered",
    ".he5": "scattered",
    ".loom": "scattered",
    ".nc": "scattered",
    ".nc4": "scattered",
    # columnar formats whose readers plan their own ranges
    ".parquet": "planned",
    ".pq": "planned",
}


@dataclass(frozen=True)
class NetworkProfile:
    """Latency and bandwidth of the link to a filesystem.

    Parameters
    ----------
    rtt:
        Time to first byte of a request, in seconds (object stores: ~10-30 ms
        in-region, 50-200 ms across regions or continents).
    bandwidth:
        Throughput of a single request stream, in bytes per second.
    """

    rtt: float
    bandwidth: float

    def __post_init__(self) -> None:
        if not self.rtt >= 0:
            raise ValueError(f"rtt must be >= 0, got {self.rtt!r}")
        if not self.bandwidth > 0:
            raise ValueError(f"bandwidth must be > 0, got {self.bandwidth!r}")

    @property
    def bdp(self) -> float:
        """Bandwidth-delay product in bytes: data transferable during one RTT."""
        return self.rtt * self.bandwidth


# Same-region cloud VM to object store: 20 ms time to first byte, 100 MB/s.
DEFAULT_NETWORK = NetworkProfile(rtt=0.020, bandwidth=100e6)


class HybridBlockCache(BlockCache):
    """Block cache for small reads; a single direct request for large ones.

    :class:`fsspec.caching.BlockCache` amortizes round trips for scattered
    small reads, but splits a large contiguous read into many sequential
    block-sized requests. This cache passes any read of at least one block
    straight to the backend in one request, and block-caches the rest.
    """

    name = "upath-hybrid"

    def _fetch(self, start: int | None, end: int | None) -> bytes:
        if start is None:
            start = 0
        if end is None:
            end = self.size
        if start >= self.size or start >= end:
            return b""
        if end - start >= self.blocksize:
            end = min(end, self.size)
            self.miss_count += 1
            self.total_requested_bytes += end - start
            return self.fetcher(start, end)
        return super()._fetch(start, end)


def _ensure_hybrid_cache_registered() -> None:
    if caches.get(HybridBlockCache.name) is not HybridBlockCache:
        register_cache(HybridBlockCache)


def _block_size(network: NetworkProfile) -> int:
    """Twice the bandwidth-delay product, as a power of two in [1, 16] MiB."""
    target = max(2 * network.bdp, 1.0)
    size = 1 << math.ceil(math.log2(target))
    return min(max(size, _MIN_BLOCK), _MAX_BLOCK)


def guess_access(path: Any) -> AccessHint | None:
    """Guess the access hint for a path from its suffix, or None if unknown."""
    suffix = getattr(path, "suffix", None)
    if suffix is None:
        name = str(path).rstrip("/").rsplit("/", 1)[-1]
        dot = name.rfind(".")
        suffix = name[dot:] if dot > 0 else ""
    return _SUFFIX_HINTS.get(suffix.lower())


def fetch_options(
    access: AccessHint,
    *,
    path: Any = None,
    network: NetworkProfile | None = None,
) -> dict[str, Any]:
    """Return ``open()`` keyword arguments for an access hint and network.

    Parameters
    ----------
    access:
        How the reader accesses the file:

        - ``"scattered"``: many small reads at scattered offsets, mixed with
          some large contiguous reads. Typical for HDF5-based formats (h5ad,
          netCDF4, loom) read through h5py.
        - ``"planned"``: the reader plans and coalesces its own byte ranges,
          so any fsspec cache only adds over-fetch. Typical for parquet read
          with pyarrow.
        - ``"whole"``: the file is read entirely; fetch it in one request.
        - ``"auto"``: pick one of the above from the path's suffix, or leave
          the filesystem defaults untouched if the suffix is not recognized.
    path:
        The path being opened. Only used to resolve ``access="auto"``.
    network:
        The network profile. Defaults to ``DEFAULT_NETWORK``, a same-region
        cloud VM reading from an object store (20 ms, 100 MB/s).

    Returns
    -------
    dict
        ``cache_type`` and possibly ``block_size`` for fsspec's ``open()``.
        Empty if ``access="auto"`` and the suffix is not recognized.

    Examples
    --------
    >>> fetch_options("scattered")
    {'cache_type': 'upath-hybrid', 'block_size': 4194304}
    >>> fetch_options("planned")
    {'cache_type': 'none'}
    """
    if access is None or access not in get_args(AccessHint):
        raise ValueError(
            f"access must be one of {get_args(AccessHint)!r}, got {access!r}"
        )
    if access == "auto":
        guessed = guess_access(path) if path is not None else None
        if guessed is None:
            return {}
        access = guessed
    if access == "planned":
        return {"cache_type": "none"}
    if access == "whole":
        return {"cache_type": "all"}
    # scattered
    _ensure_hybrid_cache_registered()
    return {
        "cache_type": HybridBlockCache.name,
        "block_size": _block_size(network or DEFAULT_NETWORK),
    }


def _validate(access: AccessHint | None) -> None:
    if access is not None and access not in get_args(AccessHint):
        raise ValueError(
            f"access must be one of {get_args(AccessHint)!r} or None, got {access!r}"
        )


def _default_access_from_env() -> AccessHint | None:
    value = os.environ.get("UPATH_FETCH_TUNING", "").strip().lower()
    if value in {"0", "false", "off", "no", "none"}:
        return None
    return "auto"


_default_access: AccessHint | None = _default_access_from_env()


def get_default_access() -> AccessHint | None:
    """Return the access hint ``UPath.open()`` uses when none is passed."""
    return _default_access


def set_default_access(access: AccessHint | None) -> None:
    """Set the access hint ``UPath.open()`` uses when none is passed.

    ``"auto"`` (the default) detects the access pattern from the suffix;
    ``None`` disables automatic tuning, so files are opened with the
    filesystem's own defaults unless ``access`` is passed explicitly.
    The initial value is ``None`` if the environment variable
    ``UPATH_FETCH_TUNING`` is ``0``, ``false``, ``off``, ``no`` or ``none``.
    """
    global _default_access
    _validate(access)
    _default_access = access


def _open_options(path: Any, access: Any = UNSET_DEFAULT) -> dict[str, Any]:
    """Fetch options ``UPath.open()`` adds for ``access`` (unset: the default).

    An explicit ``access`` always applies. The default only applies to path
    classes marked with ``_supports_fetch_tuning`` (filesystems whose files
    use fsspec's caches) and never overrides cache settings configured in the
    path's storage options.
    """
    if access is UNSET_DEFAULT:
        access = _default_access
        if access is None or not getattr(path, "_supports_fetch_tuning", False):
            return {}
        storage_options = getattr(path, "storage_options", {})
        if isinstance(storage_options, Mapping) and not _FS_CACHE_OPTIONS.isdisjoint(
            storage_options
        ):
            return {}
    if access is None:
        return {}
    return fetch_options(access, path=path)
