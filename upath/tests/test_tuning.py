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
from upath.registry import _registry as upath_registry_private
from upath.registry import register_implementation as upath_register
from upath.tuning import DEFAULT_NETWORK
from upath.tuning import HybridBlockCache
from upath.tuning import NetworkProfile
from upath.tuning import _default_access_from_env
from upath.tuning import fetch_options
from upath.tuning import get_default_access
from upath.tuning import guess_access
from upath.tuning import set_default_access

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


# --- UPath.open(): automatic detection and opt-outs -------------------------


class _BufferedFile(AbstractBufferedFile):
    def _fetch_range(self, start, end):
        return self.fs.store[self.path][start:end]


class _BufferedMemFS(AbstractFileSystem):
    """Minimal remote-like filesystem whose files use fsspec's caches."""

    store: dict[str, bytes] = {}

    def __init__(self, **storage_options):
        super().__init__(**storage_options)

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


class _TunedPath(UPath):
    __slots__ = ()
    _supports_fetch_tuning = True


@pytest.fixture
def protos():
    """(protocol with a tuning-enabled UPath class, protocol with generic UPath)"""
    tuned, generic = (
        "".join(random.choices(string.ascii_lowercase, k=10)) for _ in range(2)
    )
    for proto in (tuned, generic):
        fs_cls = type("BufferedMemFS", (_BufferedMemFS,), {"protocol": proto})
        fs_cls.store = {
            "bucket/atlas.h5ad": DATA,
            "bucket/table.parquet": DATA,
            "bucket/notes.txt": b"hello\nworld\n",
        }
        register_implementation(proto, fs_cls)
    upath_register(tuned, _TunedPath)
    try:
        yield tuned, generic
    finally:
        for proto in (tuned, generic):
            fsspec_registry_private.pop(proto, None)
        upath_registry_private._m.maps[0].pop(tuned, None)


@pytest.fixture
def restore_default_access():
    old = get_default_access()
    try:
        yield
    finally:
        set_default_access(old)


def test_default_access_is_auto():
    assert get_default_access() == "auto"


def test_open_detects_access_from_suffix(protos):
    base = UPath(f"{protos[0]}://bucket")
    assert isinstance(base, _TunedPath)
    with (base / "atlas.h5ad").open("rb") as f:
        assert isinstance(f.cache, HybridBlockCache)
        assert f.blocksize == 4 * MiB
        f.seek(1000)
        assert f.read(100) == DATA[1000:1100]
    with (base / "table.parquet").open("rb") as f:
        assert type(f.cache) is BaseCache  # cache_type="none"
        assert f.read() == DATA
    with (base / "notes.txt").open("rb") as f:
        assert isinstance(f.cache, ReadAheadCache)  # unknown suffix: fs defaults


def test_open_opt_out_per_call(protos):
    with UPath(f"{protos[0]}://bucket/atlas.h5ad").open("rb", access=None) as f:
        assert isinstance(f.cache, ReadAheadCache)
        assert f.blocksize == 5 * MiB


def test_open_opt_out_globally(protos, restore_default_access):
    set_default_access(None)
    p = UPath(f"{protos[0]}://bucket/atlas.h5ad")
    with p.open("rb") as f:
        assert isinstance(f.cache, ReadAheadCache)
    with p.open("rb", access="auto") as f:  # explicit hints still apply
        assert isinstance(f.cache, HybridBlockCache)


def test_set_default_access_invalid(restore_default_access):
    with pytest.raises(ValueError, match="access must be one of"):
        set_default_access("sequential")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value,expected",
    [("", "auto"), ("1", "auto"), ("0", None), ("off", None), ("False", None)],
)
def test_default_access_from_env(monkeypatch, value, expected):
    monkeypatch.setenv("UPATH_FETCH_TUNING", value)
    assert _default_access_from_env() == expected


@pytest.mark.parametrize(
    "storage_options",
    [
        {"default_cache_type": "bytes"},
        {"default_block_size": 2 * MiB},
        {"block_size": 2 * MiB},
        {"cache_type": "bytes"},
    ],
)
def test_open_respects_fs_cache_storage_options(protos, storage_options):
    p = UPath(f"{protos[0]}://bucket/atlas.h5ad", **storage_options)
    with p.open("rb") as f:
        assert not isinstance(f.cache, HybridBlockCache)
    with p.open("rb", access="scattered") as f:  # explicit hints still apply
        assert isinstance(f.cache, HybridBlockCache)


def test_open_generic_upath_only_explicit(protos):
    p = UPath(f"{protos[1]}://bucket/atlas.h5ad")
    assert not isinstance(p, _TunedPath)
    with p.open("rb") as f:
        assert isinstance(f.cache, ReadAheadCache)
    with p.open("rb", access="scattered") as f:
        assert isinstance(f.cache, HybridBlockCache)


def test_open_explicit_kwargs_take_precedence(protos):
    p = UPath(f"{protos[0]}://bucket/atlas.h5ad")
    with p.open("rb", cache_type="bytes") as f:
        assert isinstance(f.cache, BytesCache)
    with p.open("rb", block_size=12345) as f:
        assert isinstance(f.cache, HybridBlockCache)
        assert f.blocksize == 12345
    with p.open("rb", buffering=4096) as f:
        assert f.blocksize == 4096


def test_open_text_mode(protos):
    with UPath(f"{protos[0]}://bucket/notes.txt").open("r", access="scattered") as f:
        assert isinstance(f.buffer.cache, HybridBlockCache)
        assert f.read() == "hello\nworld\n"


def test_open_via_proxy(protos):
    with ProxyUPath(f"{protos[0]}://bucket/atlas.h5ad").open("rb") as f:
        assert isinstance(f.cache, HybridBlockCache)


def test_open_ignored_for_write_modes():
    p = UPath("memory:///tuning/out.h5ad")
    with p.open("wb", access="scattered") as f:
        f.write(b"abc")
    assert p.read_bytes() == b"abc"


def test_open_local_keeps_builtin_open(tmp_path):
    (tmp_path / "x.h5ad").write_bytes(b"xyz")
    for kw in ({}, {"access": "scattered"}):
        with UPath(tmp_path / "x.h5ad").open("rb", **kw) as f:
            assert isinstance(f, io.BufferedReader)
            assert f.read() == b"xyz"


def test_open_access_invalid(protos):
    with pytest.raises(ValueError, match="access must be one of"):
        UPath(f"{protos[0]}://bucket/atlas.h5ad").open(
            "rb", access="sequential"  # type: ignore[call-overload]
        )


# --- real backends ------------------------------------------------------------


def test_s3_open_detects_access(s3_fixture):
    path, anon, s3so = s3_fixture
    base = UPath(path, anon=anon, **s3so)
    (base / "atlas.h5ad").write_bytes(DATA)
    (base / "table.parquet").write_bytes(DATA)
    with (base / "atlas.h5ad").open("rb") as f:
        assert isinstance(f.cache, HybridBlockCache)
        f.seek(5000)
        assert f.read(10) == DATA[5000:5010]
        f.seek(0)
        assert f.read() == DATA
    with (base / "table.parquet").open("rb") as f:
        assert type(f.cache) is BaseCache
        assert f.read() == DATA
    with (base / "atlas.h5ad").open("rb", access=None) as f:
        assert isinstance(f.cache, ReadAheadCache)  # s3fs default


def test_http_open_detects_access(http_server):
    http_path, http_url = http_server
    (http_path / "atlas.h5ad").write_bytes(DATA)
    p = UPath(f"{http_url}/atlas.h5ad")
    assert p._supports_fetch_tuning
    # python's http.server ignores Range requests; reads must still work
    with p.open("rb") as f:
        assert f.read() == DATA
