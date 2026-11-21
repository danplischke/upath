from __future__ import annotations

import io
import random
import string

import pytest
from fsspec.caching import BaseCache
from fsspec.caching import BytesCache
from fsspec.caching import ReadAheadCache
from fsspec.caching import caches
from fsspec.registry import _registry as fsspec_registry_private
from fsspec.registry import register_implementation
from fsspec.spec import AbstractBufferedFile
from fsspec.spec import AbstractFileSystem

from upath import UPath
from upath.extensions import ProxyUPath
from upath.tuning import DEFAULT_NETWORK
from upath.tuning import HybridBlockCache
from upath.tuning import NetworkProfile
from upath.tuning import fetch_options
from upath.tuning import guess_access

pytestmark = pytest.mark.filterwarnings(
    "ignore:UPath .* filesystem not explicitly implemented:UserWarning"
)

MiB = 2**20


# --- fetch_options -----------------------------------------------------------


def test_fetch_options_scattered_uses_hybrid_cache():
    opts = fetch_options("scattered")
    assert opts == {"cache_type": HybridBlockCache.name, "block_size": 4 * MiB}
    assert caches[HybridBlockCache.name] is HybridBlockCache


@pytest.mark.parametrize(
    "rtt,bandwidth,block_size",
    [
        (0.0005, 400e6, 1 * MiB),  # LAN: 2*BDP = 400 kB, clamped up
        (0.020, 100e6, 4 * MiB),  # same-region cloud: 2*BDP = 4 MB
        (0.040, 12e6, 1 * MiB),  # laptop: 2*BDP = 960 kB
        (0.150, 25e6, 8 * MiB),  # cross-continent: 2*BDP = 7.5 MB
        (0.300, 1e9, 16 * MiB),  # huge BDP, clamped down
        (0.0, 1e9, 1 * MiB),  # zero latency
    ],
)
def test_fetch_options_block_size_follows_bdp(rtt, bandwidth, block_size):
    network = NetworkProfile(rtt=rtt, bandwidth=bandwidth)
    opts = fetch_options("scattered", network=network)
    assert opts["block_size"] == block_size


def test_fetch_options_planned_and_whole():
    assert fetch_options("planned") == {"cache_type": "none"}
    assert fetch_options("whole") == {"cache_type": "all"}


@pytest.mark.parametrize(
    "path,expected",
    [
        ("s3://bucket/atlas.h5ad", "scattered"),
        ("gs://bucket/dir/data.nc", "scattered"),
        ("data/table.PARQUET", "planned"),
        (UPath("memory:///dir/x.h5"), "scattered"),
        ("s3://bucket/notes.txt", None),
        ("s3://bucket/noext", None),
        ("s3://bucket/.h5", None),  # hidden file, no suffix (as in pathlib)
    ],
)
def test_guess_access(path, expected):
    assert guess_access(path) == expected
    auto = fetch_options("auto", path=path)
    assert auto == (fetch_options(expected) if expected else {})


def test_fetch_options_auto_without_path():
    assert fetch_options("auto") == {}


def test_fetch_options_invalid():
    with pytest.raises(ValueError, match="access must be one of"):
        fetch_options("sequential")  # type: ignore[arg-type]


def test_network_profile():
    assert DEFAULT_NETWORK.bdp == pytest.approx(2e6)
    with pytest.raises(ValueError):
        NetworkProfile(rtt=-1, bandwidth=1e6)
    with pytest.raises(ValueError):
        NetworkProfile(rtt=0.01, bandwidth=0)


# --- HybridBlockCache --------------------------------------------------------

DATA = bytes(range(256)) * 1000  # 256_000 bytes


@pytest.fixture
def hybrid():
    calls = []

    def fetcher(start, end):
        calls.append((start, end))
        return DATA[start:end]

    return HybridBlockCache(blocksize=1024, fetcher=fetcher, size=len(DATA)), calls


def test_hybrid_small_reads_are_block_cached(hybrid):
    cache, calls = hybrid
    assert cache._fetch(10, 20) == DATA[10:20]
    assert cache._fetch(500, 900) == DATA[500:900]
    assert calls == [(0, 1024)]
    # spans two blocks, one of them cached
    assert cache._fetch(1000, 1100) == DATA[1000:1100]
    assert calls == [(0, 1024), (1024, 2048)]


def test_hybrid_large_reads_are_single_requests(hybrid):
    cache, calls = hybrid
    assert cache._fetch(5000, 9000) == DATA[5000:9000]
    assert calls == [(5000, 9000)]
    assert cache._fetch(3000, 3000 + 1024) == DATA[3000:4024]  # exactly one block
    assert calls[-1] == (3000, 4024)


def test_hybrid_bounds(hybrid):
    cache, calls = hybrid
    n = len(DATA)
    assert cache._fetch(n - 10, n + 100) == DATA[-10:]
    assert cache._fetch(n - 5000, n + 5000) == DATA[-5000:]
    assert calls[-1] == (n - 5000, n)
    assert cache._fetch(n, n + 10) == b""
    assert cache._fetch(20, 10) == b""
    assert cache._fetch(None, None) == DATA


# --- UPath.open(access=...) --------------------------------------------------


class _BufferedFile(AbstractBufferedFile):
    def _fetch_range(self, start, end):
        return self.fs.store[self.path][start:end]


class _BufferedMemFS(AbstractFileSystem):
    """Minimal remote-like filesystem whose files use fsspec's caches."""

    store: dict[str, bytes] = {}

    def info(self, path, **kwargs):
        path = self._strip_protocol(path)
        if path not in self.store:
            raise FileNotFoundError(path)
        return {"name": path, "size": len(self.store[path]), "type": "file"}

    def _open(self, path, mode="rb", block_size=None, **kwargs):
        return _BufferedFile(
            self,
            path,
            mode,
            block_size=block_size or 5 * MiB,
            cache_type=kwargs.get("cache_type", "readahead"),
            cache_options=kwargs.get("cache_options"),
        )


@pytest.fixture
def buffered_proto():
    proto = "".join(random.choices(string.ascii_lowercase, k=10))
    fs_cls = type("BufferedMemFS", (_BufferedMemFS,), {"protocol": proto})
    register_implementation(proto, fs_cls)
    fs_cls.store = {
        "bucket/atlas.h5ad": DATA,
        "bucket/table.parquet": DATA,
        "bucket/notes.txt": b"hello\nworld\n",
    }
    try:
        yield proto
    finally:
        fsspec_registry_private.pop(proto, None)


def test_open_without_access_keeps_fs_defaults(buffered_proto):
    with UPath(f"{buffered_proto}://bucket/atlas.h5ad").open("rb") as f:
        assert isinstance(f.cache, ReadAheadCache)
        assert f.blocksize == 5 * MiB


def test_open_access_scattered(buffered_proto):
    with UPath(f"{buffered_proto}://bucket/atlas.h5ad").open(
        "rb", access="scattered"
    ) as f:
        assert isinstance(f.cache, HybridBlockCache)
        assert f.blocksize == 4 * MiB
        f.seek(1000)
        assert f.read(100) == DATA[1000:1100]


def test_open_access_auto(buffered_proto):
    base = UPath(f"{buffered_proto}://bucket")
    with (base / "atlas.h5ad").open("rb", access="auto") as f:
        assert isinstance(f.cache, HybridBlockCache)
    with (base / "table.parquet").open("rb", access="auto") as f:
        assert type(f.cache) is BaseCache  # cache_type="none"
        assert f.read() == DATA
    with (base / "notes.txt").open("rb", access="auto") as f:
        assert isinstance(f.cache, ReadAheadCache)  # unknown suffix: defaults


def test_open_explicit_kwargs_take_precedence(buffered_proto):
    p = UPath(f"{buffered_proto}://bucket/atlas.h5ad")
    with p.open("rb", access="scattered", cache_type="bytes") as f:
        assert isinstance(f.cache, BytesCache)
    with p.open("rb", access="scattered", block_size=12345) as f:
        assert isinstance(f.cache, HybridBlockCache)
        assert f.blocksize == 12345
    with p.open("rb", buffering=4096, access="scattered") as f:
        assert f.blocksize == 4096


def test_open_access_text_mode(buffered_proto):
    p = UPath(f"{buffered_proto}://bucket/notes.txt")
    with p.open("r", access="scattered") as f:
        assert isinstance(f.buffer.cache, HybridBlockCache)
        assert f.read() == "hello\nworld\n"


def test_open_access_via_proxy(buffered_proto):
    p = ProxyUPath(f"{buffered_proto}://bucket/atlas.h5ad")
    with p.open("rb", access="scattered") as f:
        assert isinstance(f.cache, HybridBlockCache)


def test_open_access_ignored_for_write_modes():
    p = UPath("memory:///tuning/out.h5ad")
    with p.open("wb", access="scattered") as f:
        f.write(b"abc")
    assert p.read_bytes() == b"abc"


def test_open_access_local_keeps_builtin_open(tmp_path):
    (tmp_path / "x.h5ad").write_bytes(b"xyz")
    with UPath(tmp_path / "x.h5ad").open("rb", access="scattered") as f:
        assert isinstance(f, io.BufferedReader)
        assert f.read() == b"xyz"


def test_open_access_invalid(buffered_proto):
    with pytest.raises(ValueError, match="access must be one of"):
        UPath(f"{buffered_proto}://bucket/atlas.h5ad").open(
            "rb", access="sequential"  # type: ignore[call-overload]
        )
