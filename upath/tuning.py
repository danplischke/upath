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
the file suffix (``.h5ad``, ``.h5``, ``.nc``, ``.tif``, ``.fits``, ``.orc``,
... -> ``"scattered"``; ``.parquet``, ``.feather`` -> ``"planned"``) on
filesystems whose files use fsspec's caches (s3, gcs, azure, hf, http).
Explicit ``cache_type``, ``block_size`` or ``buffering`` arguments and cache
settings in the path's storage options are left untouched. To opt out:

- per call: ``path.open("rb", access=None)``
- per process: ``upath.tuning.set_default_access(None)``
- per environment: ``UPATH_FETCH_TUNING=0``

The network profile is detected per endpoint (filesystem and bucket or host)
from the requests upath's caches make: their duration as a function of size
gives the round trip time and the bandwidth. Until an endpoint has been
measured, :data:`DEFAULT_NETWORK` applies. Pin a profile with
:func:`set_default_network` to disable detection.

The rules come from benchmarks on GB-scale h5ad and parquet files over
simulated networks (see ``dev/access_patterns/`` in the repository).
"""

from __future__ import annotations

import math
import os
import statistics
import threading
import time
from collections import deque
from collections.abc import Hashable
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Literal
from typing import get_args
from urllib.parse import urlsplit

from fsspec.caching import BaseCache
from fsspec.caching import BlockCache
from fsspec.caching import caches
from fsspec.caching import register_cache
from fsspec.utils import tokenize

from upath.types import UNSET_DEFAULT

__all__ = [
    "AccessHint",
    "NetworkProfile",
    "DEFAULT_NETWORK",
    "HybridBlockCache",
    "PassthroughCache",
    "fetch_options",
    "guess_access",
    "get_default_access",
    "set_default_access",
    "get_default_network",
    "set_default_network",
    "estimate_network",
]

# How a reader accesses a file, see fetch_options() for the meaning of each hint.
AccessHint = Literal["auto", "scattered", "planned", "whole"]

_KiB = 2**10
_MiB = 2**20
_MIN_BLOCK = 1 * _MiB
_MAX_BLOCK = 4 * _MiB

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
    ".nwb": "scattered",
    ".nxs": "scattered",
    # netCDF: netCDF4 is HDF5; netCDF3 readers also benefit (header + variables)
    ".nc": "scattered",
    ".nc4": "scattered",
    # tiled images: IFD/header walks + tile reads (tifffile, astropy)
    ".tif": "scattered",
    ".tiff": "scattered",
    ".fits": "scattered",
    ".fit": "scattered",
    ".fts": "scattered",
    # ORC: the reader issues many small stream reads
    ".orc": "scattered",
    # columnar formats whose readers plan their own ranges
    ".parquet": "planned",
    ".pq": "planned",
    ".feather": "planned",
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


# --- network detection -------------------------------------------------------

_SMALL_SAMPLE = 256 * _KiB  # requests up to this size measure latency
_LARGE_SAMPLE = 1 * _MiB  # requests from this size on measure bandwidth
_PROBE = 64 * _KiB  # size of the latency probe split off a large request
_MIN_SAMPLES = 2  # per group, before an estimate is made
_MAX_SAMPLES = 16  # per group, most recent kept


class _NetworkEstimator:
    """Per-endpoint RTT and bandwidth estimates from timed requests.

    Requests take ``rtt + nbytes / bandwidth``. Small requests are dominated
    by the round trip, large ones by the transfer; the medians of both groups
    give both parameters robustly against latency spikes.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._small: dict[Hashable, deque[tuple[int, float]]] = {}
        self._large: dict[Hashable, deque[tuple[int, float]]] = {}

    def add(self, key: Hashable, nbytes: int, seconds: float) -> None:
        if nbytes <= _SMALL_SAMPLE:
            group = self._small
        elif nbytes >= _LARGE_SAMPLE:
            group = self._large
        else:
            return
        with self._lock:
            group.setdefault(key, deque(maxlen=_MAX_SAMPLES)).append((nbytes, seconds))

    def needs_latency_sample(self, key: Hashable) -> bool:
        with self._lock:
            return len(self._small.get(key, ())) < _MIN_SAMPLES

    def estimate(self, key: Hashable) -> NetworkProfile | None:
        with self._lock:
            small = list(self._small.get(key, ()))
            large = list(self._large.get(key, ()))
        if len(small) < _MIN_SAMPLES or len(large) < _MIN_SAMPLES:
            return None
        n_s = statistics.median(n for n, _ in small)
        t_s = statistics.median(t for _, t in small)
        rates = [(n - n_s) / (t - t_s) for n, t in large if t > t_s]
        bandwidth = statistics.median(rates) if rates else 1e11
        bandwidth = min(max(bandwidth, 1e5), 1e11)
        rtt = statistics.median(t - n / bandwidth for n, t in small)
        return NetworkProfile(rtt=min(max(rtt, 0.0), 5.0), bandwidth=bandwidth)

    def clear(self) -> None:
        with self._lock:
            self._small.clear()
            self._large.clear()


_ESTIMATOR = _NetworkEstimator()
_default_network: NetworkProfile | None = None


def _timed_fetcher(
    fetcher: Callable[[int, int], bytes], key: Hashable | None
) -> Callable[[int, int], bytes]:
    """Wrap a cache fetcher to feed request timings to the estimator."""
    if key is None:
        return fetcher

    def timed(start: int, end: int) -> bytes:
        t0 = time.perf_counter()
        data = fetcher(start, end)
        _ESTIMATOR.add(key, len(data), time.perf_counter() - t0)
        return data

    def fetch(start: int, end: int) -> bytes:
        if end - start >= 2 * _PROBE and _ESTIMATOR.needs_latency_sample(key):
            # split off a small request: one extra round trip, until measured
            return timed(start, start + _PROBE) + timed(start + _PROBE, end)
        return timed(start, end)

    return fetch


def _endpoint_key(path: Any) -> Hashable | None:
    """Identify the link a path is read over: filesystem + options + netloc.

    Unlike fsspec's instance token, this is shared across threads.
    """
    try:
        fs = path.fs
        options = tokenize(getattr(fs, "storage_options", {}))
    except Exception:
        return None
    return type(fs).__qualname__, options, urlsplit(str(path)).netloc


def estimate_network(path: Any) -> NetworkProfile | None:
    """Return the network profile measured for the endpoint of ``path``.

    None until enough requests to that endpoint went through upath's caches.
    """
    key = _endpoint_key(path)
    return None if key is None else _ESTIMATOR.estimate(key)


def get_default_network() -> NetworkProfile | None:
    """Return the pinned network profile, or None if it is detected."""
    return _default_network


def set_default_network(network: NetworkProfile | None) -> None:
    """Pin the network profile for ``UPath.open()``, or None to detect it.

    With None (the default), the profile is estimated per endpoint from
    observed requests, falling back to :data:`DEFAULT_NETWORK`.
    """
    global _default_network
    if network is not None and not isinstance(network, NetworkProfile):
        raise TypeError(f"expected NetworkProfile or None, got {network!r}")
    _default_network = network


# --- caches ------------------------------------------------------------------


class HybridBlockCache(BlockCache):
    """Block cache for small reads; a single direct request for large ones.

    :class:`fsspec.caching.BlockCache` amortizes round trips for scattered
    small reads, but splits a large contiguous read into many sequential
    block-sized requests. This cache passes any read of at least one block
    straight to the backend in one request, and block-caches the rest.
    """

    name = "upath-hybrid"

    def __init__(
        self,
        blocksize: int,
        fetcher: Callable[[int, int], bytes],
        size: int,
        maxblocks: int = 32,
        network_key: Hashable | None = None,
    ) -> None:
        super().__init__(
            blocksize, _timed_fetcher(fetcher, network_key), size, maxblocks
        )

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


class PassthroughCache(BaseCache):
    """No caching, like fsspec's ``"none"``, but feeding network detection."""

    name = "upath-none"

    def __init__(
        self,
        blocksize: int,
        fetcher: Callable[[int, int], bytes],
        size: int,
        network_key: Hashable | None = None,
    ) -> None:
        super().__init__(blocksize, _timed_fetcher(fetcher, network_key), size)


def _ensure_caches_registered() -> None:
    for cls in (HybridBlockCache, PassthroughCache):
        if caches.get(cls.name) is not cls:
            register_cache(cls)


# --- rules -------------------------------------------------------------------


def _block_size(network: NetworkProfile) -> int:
    """Twice the bandwidth-delay product, as a power of two in [1, 4] MiB."""
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
          netCDF4, NWB) read through h5py, tiled TIFF and FITS images, and
          ORC tables.
        - ``"planned"``: the reader plans and coalesces its own byte ranges,
          so any fsspec cache only adds over-fetch. Typical for parquet and
          feather read with pyarrow.
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
    >>> fetch_options("scattered", network=NetworkProfile(0.04, 12e6))
    {'cache_type': 'upath-hybrid', 'block_size': 1048576}
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
    _ensure_caches_registered()
    return {
        "cache_type": HybridBlockCache.name,
        "block_size": _block_size(network or DEFAULT_NETWORK),
    }


# --- defaults for UPath.open() -------------------------------------------------


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
    path's storage options. The network profile is the pinned one, else the
    estimate for the path's endpoint, else ``DEFAULT_NETWORK``.
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
    key = None if _default_network is not None else _endpoint_key(path)
    network = _default_network
    if network is None and key is not None:
        network = _ESTIMATOR.estimate(key)
    options = fetch_options(access, path=path, network=network)
    if key is not None and options.get("cache_type") in ("none", HybridBlockCache.name):
        _ensure_caches_registered()
        if options["cache_type"] == "none":
            options["cache_type"] = PassthroughCache.name
        options["cache_options"] = {"network_key": key}
    return options


def _apply_open_options(path: Any, access: Any, fsspec_kwargs: dict[str, Any]) -> None:
    """Add fetch options to ``UPath.open()``'s fsspec kwargs, in place.

    Explicitly passed kwargs win. The network detection hook is only attached
    when the resulting cache type is one of upath's caches.
    """
    options = _open_options(path, access)
    cache_options = options.pop("cache_options", None)
    for key, value in options.items():
        fsspec_kwargs.setdefault(key, value)
    if cache_options and fsspec_kwargs.get("cache_type") in (
        HybridBlockCache.name,
        PassthroughCache.name,
    ):
        fsspec_kwargs["cache_options"] = {
            **cache_options,
            **(fsspec_kwargs.get("cache_options") or {}),
        }
