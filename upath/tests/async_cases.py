"""Async mirror of :mod:`upath.tests.cases`.

These tiered test mixins parallel the synchronous suite but exercise
:class:`upath.AsyncUPath` via ``await`` / async iteration. The pure path-algebra
tier (:class:`upath.tests.cases.JoinablePathTests`) is reused unchanged because
path manipulation is synchronous on ``AsyncUPath`` too.

Only the methods called on the async path-under-test (``self.path`` /
``self.path_file`` / ``source``) are awaited. Independent targets and
verification helpers (stdlib ``Path``, synchronous ``UPath``) are kept exactly
as in the synchronous suite -- they read/write their own filesystem
synchronously.
"""

from __future__ import annotations

import os
import stat
import warnings
from pathlib import Path

import pytest
from fsspec import __version__ as fsspec_version
from fsspec import filesystem
from packaging.version import Version

from upath import AsyncUPath
from upath import UnsupportedOperation
from upath import UPath
from upath._stat import UPathStatResult
from upath.tests.cases import JoinablePathTests
from upath.types import StatResultType

__all__ = [
    "JoinablePathTests",
    "AsyncReadablePathTests",
    "AsyncWritablePathTests",
    "AsyncNonWritablePathTests",
    "AsyncReadWritePathTests",
    "AsyncBaseTests",
]


class AsyncReadablePathTests:
    """Async mirror of :class:`upath.tests.cases.ReadablePathTests`."""

    path: AsyncUPath

    @pytest.fixture(autouse=True)
    def path_file(self, path):
        self.path_file = self.path.joinpath("file1.txt")

    def test_storage_options_match_fsspec(self):
        storage_options = self.path.storage_options
        assert storage_options == self.path.fs.storage_options

    async def test_stat(self):
        stat_ = await self.path.stat()
        assert isinstance(stat_, StatResultType)
        assert len(tuple(stat_)) == os.stat_result.n_sequence_fields
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            for idx in range(os.stat_result.n_sequence_fields):
                assert isinstance(stat_[idx], int)
            for attr in UPathStatResult._fields + UPathStatResult._fields_extra:
                assert hasattr(stat_, attr)

    async def test_stat_dir_st_mode(self):
        base = await self.path.stat()
        assert stat.S_ISDIR(base.st_mode)

    async def test_stat_file_st_mode(self):
        file1 = await self.path_file.stat()
        assert stat.S_ISREG(file1.st_mode)

    async def test_stat_st_size(self):
        file1 = await self.path_file.stat()
        assert file1.st_size == 11

    @pytest.mark.parametrize(
        "url, expected", [("file1.txt", True), ("fakefile.txt", False)]
    )
    async def test_exists(self, url, expected):
        path = self.path.joinpath(url)
        assert await path.exists() == expected

    def test_expanduser(self):
        assert self.path.expanduser() == self.path

    @pytest.mark.parametrize(
        "pattern",
        (
            "*.txt",
            "*",
            pytest.param(
                "**/*.txt",
                marks=(
                    pytest.mark.xfail(reason="requires fsspec>=2023.9.0")
                    if Version(fsspec_version) < Version("2023.9.0")
                    else ()
                ),
            ),
        ),
    )
    async def test_glob(self, pathlib_base, pattern):
        mock_glob = [p async for p in self.path.glob(pattern)]
        path_glob = list(pathlib_base.glob(pattern))

        _mock_start = len(self.path.parts)
        mock_glob_normalized = sorted(
            [tuple(filter(None, a.parts[_mock_start:])) for a in mock_glob]
        )
        _path_start = len(pathlib_base.parts)
        path_glob_normalized = sorted([a.parts[_path_start:] for a in path_glob])
        assert mock_glob_normalized == path_glob_normalized

    async def test_is_dir(self):
        assert await self.path.is_dir()
        path = self.path / "file1.txt"
        assert not await path.is_dir()
        assert not await (self.path / "not-existing-dir").is_dir()

    async def test_is_file(self):
        path_exists = self.path / "file1.txt"
        assert await path_exists.is_file()
        assert not await (self.path / "not-existing-file.txt").is_file()

    def test_is_symlink(self):
        assert self.path.is_symlink() is False

    def test_is_socket(self):
        assert self.path.is_socket() is False

    def test_is_fifo(self):
        assert self.path.is_fifo() is False

    def test_is_block_device(self):
        assert self.path.is_block_device() is False

    def test_is_char_device(self):
        assert self.path.is_char_device() is False

    def test_is_mount(self):
        try:
            self.path.is_mount()
        except UnsupportedOperation:
            pytest.skip(f"is_mount() not supported for {type(self.path).__name__}")
        else:
            assert self.path.is_mount() is False

    async def test_iterdir(self, local_testdir):
        pl_path = Path(local_testdir)
        up_iter = [p async for p in self.path.iterdir()]
        pl_iter = list(pl_path.iterdir())
        for x in up_iter:
            assert x.name != ""
            assert await x.exists()
        assert len(up_iter) == len(pl_iter)
        assert {p.name for p in pl_iter} == {u.name for u in up_iter}

    async def test_iterdir_parent_iteration(self):
        async for child in self.path.parent.iterdir():
            assert await child.exists()
            break

    async def test_iterdir2(self, local_testdir):
        pl_path = Path(local_testdir) / "folder1"
        up_iter = [p async for p in (self.path / "folder1").iterdir()]
        pl_iter = list(pl_path.iterdir())
        for x in up_iter:
            assert await x.exists()
        assert len(up_iter) == len(pl_iter)
        assert {p.name for p in pl_iter} == {u.name for u in up_iter}

    async def test_iterdir_trailing_slash(self):
        files_noslash = [p async for p in self.path.joinpath("folder1").iterdir()]
        files_slash = [p async for p in self.path.joinpath("folder1/").iterdir()]
        assert files_noslash == files_slash

    async def test_lstat(self):
        with pytest.warns(UserWarning, match=r"[A-Za-z]+.stat"):
            st = await self.path.lstat()
            assert st is not None

    def test_cwd(self):
        with pytest.raises(UnsupportedOperation):
            self.path.cwd()

    def test_home(self):
        with pytest.raises(UnsupportedOperation):
            self.path.home()

    async def test_open(self):
        p = self.path_file
        async with await p.open(mode="r") as f:
            assert await f.read() == "hello world"
        async with await p.open(mode="rb") as f:
            assert await f.read() == b"hello world"

    async def test_open_buffering(self):
        p = self.path_file
        async with await p.open(buffering=-1):
            pass

    async def test_open_block_size(self):
        p = self.path_file
        async with await p.open(mode="r", block_size=8192) as f:
            assert await f.read() == "hello world"

    async def test_open_errors(self):
        p = self.path_file
        async with await p.open(mode="r", encoding="ascii", errors="strict") as f:
            assert await f.read() == "hello world"

    async def test_read_bytes(self):
        mock = self.path.joinpath("file2.txt")
        assert await mock.read_bytes() == b"hello world"

    async def test_read_text(self):
        upath = self.path.joinpath("file1.txt")
        assert await upath.read_text() == "hello world"

    async def test_read_text_encoding(self):
        content = await self.path_file.read_text(encoding="utf-8")
        assert content == "hello world"

    async def test_read_text_errors(self):
        content = await self.path_file.read_text(encoding="ascii", errors="strict")
        assert content == "hello world"

    async def test_rglob(self, pathlib_base):
        pattern = "*.txt"
        result = [p async for p in self.path.rglob(pattern)]
        expected = list(pathlib_base.rglob(pattern))
        assert len(result) == len(expected)

    async def test_walk(self, local_testdir):
        def _raise(x):
            raise x

        upath_walk = []
        async for dirpath, dirnames, filenames in self.path.walk(on_error=_raise):
            rel = dirpath.relative_to(self.path)
            upath_walk.append((str(rel), sorted(dirnames), sorted(filenames)))
        upath_walk.sort()

        os_walk = []
        for dirpath, dirnames, filenames in os.walk(local_testdir):
            rel = os.path.relpath(dirpath, local_testdir)
            os_walk.append((rel, sorted(dirnames), sorted(filenames)))
        os_walk.sort()
        assert upath_walk == os_walk

    async def test_walk_top_down_false(self):
        def _raise(x):
            raise x

        paths_seen = []
        async for dirpath, _, _ in self.path.walk(top_down=False, on_error=_raise):
            paths_seen.append(dirpath)
        for i, path in enumerate(paths_seen):
            for other in paths_seen[i + 1 :]:
                if other.is_relative_to(path) and other != path:
                    pytest.fail(f"In bottom-up walk, {path} should come after {other}")

    async def test_samefile(self):
        f1 = self.path.joinpath("file1.txt")
        f2 = self.path.joinpath("file2.txt")
        assert await f1.samefile(f2) is False
        assert await f1.samefile(f2.path) is False
        assert await f1.samefile(f1) is True
        assert await f1.samefile(f1.path) is True

    async def test_info(self):
        p0 = self.path.joinpath("file1.txt")
        p1 = self.path.joinpath("folder1")
        assert await p0.info.exists() is True
        assert await p0.info.is_file() is True
        assert await p0.info.is_dir() is False
        assert await p0.info.is_symlink() is False
        assert await p1.info.exists() is True
        assert await p1.info.is_file() is False
        assert await p1.info.is_dir() is True
        assert await p1.info.is_symlink() is False

    async def test_copy_local(self, tmp_path: Path):
        target = UPath(tmp_path) / "target-file1.txt"
        source = self.path_file
        content = await source.read_text()
        await source.copy(target)
        assert target.exists()
        assert target.read_text() == content

    @pytest.mark.parametrize("target_type", [str, Path, UPath])
    async def test_copy_into__file_to_str_tempdir(self, tmp_path: Path, target_type):
        tmp_path = tmp_path.joinpath("somewhere")
        tmp_path.mkdir()
        target_dir = target_type(tmp_path)
        source = self.path_file
        await source.copy_into(target_dir)
        target = tmp_path.joinpath(source.name)
        assert target.exists()
        assert target.read_text() == await source.read_text()

    @pytest.mark.parametrize("target_type", [str, Path, UPath])
    async def test_copy_into__dir_to_str_tempdir(self, tmp_path: Path, target_type):
        tmp_path = tmp_path.joinpath("somewhere")
        tmp_path.mkdir()
        target_dir = target_type(tmp_path)
        source_dir = self.path.joinpath("folder1")
        assert await source_dir.is_dir()
        await source_dir.copy_into(target_dir)
        target = tmp_path.joinpath(source_dir.name)
        assert target.exists()
        assert target.is_dir()
        async for item in source_dir.iterdir():
            target_item = target.joinpath(item.name)
            assert target_item.exists()
            if await item.is_file():
                assert target_item.read_text() == await item.read_text()

    async def test_copy_into_local(self, tmp_path: Path):
        target_dir = UPath(tmp_path) / "target-dir"
        target_dir.mkdir()
        source = self.path_file
        content = await source.read_text()
        await source.copy_into(target_dir)
        target = target_dir / source.name
        assert target.exists()
        assert target.read_text() == content

    async def test_copy_memory(self, clear_fsspec_memory_cache):
        target = UPath("memory:///target-file1.txt")
        source = self.path_file
        content = await source.read_text()
        await source.copy(target)
        assert target.exists()
        assert target.read_text() == content

    async def test_copy_into_memory(self, clear_fsspec_memory_cache):
        target_dir = UPath("memory:///target-dir")
        target_dir.mkdir()
        source = self.path_file
        content = await source.read_text()
        await source.copy_into(target_dir)
        target = target_dir / source.name
        assert target.exists()
        assert target.read_text() == content

    async def test_copy_exceptions(self, tmp_path: Path):
        source = self.path_file
        target = UPath(tmp_path) / "target-folder"
        target.mkdir()
        with pytest.raises(OSError):
            await source.copy(target)
        target = UPath(tmp_path) / "nonexistent-dir" / "target-file1.txt"
        with pytest.raises(FileNotFoundError):
            await source.copy(target)

    async def test_copy_into_exceptions(self, tmp_path: Path):
        source = self.path_file
        target_file = UPath(tmp_path) / "target-file.txt"
        target_file.write_text("content")
        with pytest.raises(OSError):
            await source.copy_into(target_file)
        target_dir = UPath(tmp_path) / "nonexistent-dir"
        with pytest.raises(FileNotFoundError):
            await source.copy_into(target_dir)

    def test_read_with_fsspec(self):
        p = self.path_file
        fs = filesystem(p.protocol, **p.storage_options)
        with fs.open(p.path) as f:
            assert f.read() == b"hello world"

    def test_readlink(self):
        with pytest.raises(UnsupportedOperation):
            self.path.readlink()

    def test_group(self):
        with pytest.raises(UnsupportedOperation):
            self.path.group()

    def test_owner(self):
        with pytest.raises(UnsupportedOperation):
            self.path.owner()


class _AsyncCommonWritablePathTests:

    SUPPORTS_EMPTY_DIRS = True
    path: AsyncUPath

    def test_chmod(self):
        with pytest.raises(NotImplementedError):
            self.path_file.chmod(777)

    def test_lchmod(self):
        with pytest.raises(UnsupportedOperation):
            self.path.lchmod(mode=0o777)

    def test_symlink_to(self):
        with pytest.raises(UnsupportedOperation):
            self.path_file.symlink_to("target")
        with pytest.raises(UnsupportedOperation):
            self.path.joinpath("link").symlink_to("target")

    def test_hardlink_to(self):
        with pytest.raises(UnsupportedOperation):
            self.path_file.symlink_to("target")
        with pytest.raises(UnsupportedOperation):
            self.path.joinpath("link").hardlink_to("target")


class AsyncNonWritablePathTests(_AsyncCommonWritablePathTests):
    """Async mirror of :class:`upath.tests.cases.NonWritablePathTests`."""

    async def test_mkdir_raises(self):
        with pytest.raises(UnsupportedOperation):
            await self.path.mkdir()

    async def test_touch_raises(self):
        with pytest.raises(UnsupportedOperation):
            await self.path.touch()

    async def test_unlink(self):
        with pytest.raises(UnsupportedOperation):
            await self.path.unlink()

    async def test_write_bytes(self):
        with pytest.raises(UnsupportedOperation):
            await self.path_file.write_bytes(b"abc")

    async def test_write_text(self):
        with pytest.raises(UnsupportedOperation):
            await self.path_file.write_text("abc")


class AsyncWritablePathTests(_AsyncCommonWritablePathTests):
    """Async mirror of :class:`upath.tests.cases.WritablePathTests`."""

    async def test_mkdir(self):
        new_dir = self.path.joinpath("new_dir")
        await new_dir.mkdir()
        if not self.SUPPORTS_EMPTY_DIRS:
            await new_dir.joinpath(".file").touch()
        assert await new_dir.exists()

    async def test_mkdir_exists_ok_true(self):
        new_dir = self.path.joinpath("new_dir_may_exists")
        await new_dir.mkdir()
        if not self.SUPPORTS_EMPTY_DIRS:
            await new_dir.joinpath(".file").touch()
        await new_dir.mkdir(exist_ok=True)

    async def test_mkdir_exists_ok_false(self):
        new_dir = self.path.joinpath("new_dir_may_not_exists")
        await new_dir.mkdir()
        if not self.SUPPORTS_EMPTY_DIRS:
            await new_dir.joinpath(".file").touch()
        with pytest.raises(FileExistsError):
            await new_dir.mkdir(exist_ok=False)

    async def test_mkdir_parents_true_exists_ok_true(self):
        new_dir = self.path.joinpath("parent", "new_dir_may_not_exist")
        await new_dir.mkdir(parents=True)
        if not self.SUPPORTS_EMPTY_DIRS:
            await new_dir.joinpath(".file").touch()
        await new_dir.mkdir(parents=True, exist_ok=True)

    async def test_mkdir_parents_true_exists_ok_false(self):
        new_dir = self.path.joinpath("parent", "new_dir_may_exist")
        await new_dir.mkdir(parents=True)
        if not self.SUPPORTS_EMPTY_DIRS:
            await new_dir.joinpath(".file").touch()
        with pytest.raises(FileExistsError):
            await new_dir.mkdir(parents=True, exist_ok=False)

    async def test_touch_exists_ok_false(self):
        f = self.path.joinpath("file1.txt")
        assert await f.exists()
        with pytest.raises(FileExistsError):
            await f.touch(exist_ok=False)

    async def test_touch_exists_ok_true(self):
        f = self.path.joinpath("file1.txt")
        assert await f.exists()
        data = await f.read_text()
        await f.touch(exist_ok=True)
        assert await f.read_text() == data

    async def test_touch(self):
        path = self.path.joinpath("test_touch.txt")
        assert not await path.exists()
        await path.touch()
        assert await path.exists()

    async def test_touch_unlink(self):
        path = self.path.joinpath("test_touch.txt")
        await path.touch()
        assert await path.exists()
        await path.unlink()
        assert not await path.exists()
        with pytest.raises(FileNotFoundError):
            await path.unlink()
        await path.unlink(missing_ok=True)

    async def test_write_bytes(self, pathlib_base):
        s = b"hello_world"
        path = self.path.joinpath("test_write_bytes.txt")
        await path.write_bytes(s)
        assert await path.read_bytes() == s

    async def test_write_text(self, pathlib_base):
        s = "hello_world"
        path = self.path.joinpath("test_write_text.txt")
        await path.write_text(s)
        assert await path.read_text() == s

    async def test_write_text_encoding(self):
        s = "hello_world"
        path = self.path.joinpath("test_write_text_enc.txt")
        await path.write_text(s, encoding="utf-8")
        assert await path.read_text(encoding="utf-8") == s

    async def test_write_text_errors(self):
        s = "hello_world"
        path = self.path.joinpath("test_write_text_errors.txt")
        await path.write_text(s, encoding="ascii", errors="strict")
        assert await path.read_text(encoding="ascii") == s


class AsyncReadWritePathTests:
    """Async mirror of :class:`upath.tests.cases.ReadWritePathTests`."""

    SUPPORTS_EMPTY_DIRS = True
    path: AsyncUPath

    async def test_rename(self):
        p_source = self.path.joinpath("file1.txt")
        p_target = self.path.joinpath("file1_renamed.txt")
        p_moved = await p_source.rename(p_target)
        assert p_target == p_moved
        assert not await p_source.exists()
        assert await p_moved.exists()
        p_revert = await p_moved.rename(p_source)
        assert p_revert == p_source
        assert not await p_moved.exists()
        assert await p_revert.exists()

    @pytest.fixture
    def supports_cwd(self):
        try:
            self.path.cwd()
        except UnsupportedOperation:
            return False
        else:
            return True

    @pytest.mark.parametrize(
        "target_factory",
        [
            lambda obj, name: name,
            lambda obj, name: UPath(name),
            lambda obj, name: Path(name),
            lambda obj, name: obj.joinpath(name).relative_to(obj),
        ],
        ids=[
            "str_relative",
            "plain_upath_relative",
            "plain_path_relative",
            "self_upath_relative",
        ],
    )
    async def test_rename_with_target_relative(
        self, request, monkeypatch, supports_cwd, target_factory, tmp_path
    ):
        source = self.path.joinpath("folder1/file2.txt")
        target = target_factory(self.path, "file2_renamed.txt")
        source_text = await source.read_text()
        if supports_cwd:
            cid = request.node.callspec.id
            cwd = tmp_path.joinpath(cid)
            cwd.mkdir(parents=True, exist_ok=True)
            monkeypatch.chdir(cwd)
            t = await source.rename(target)
            assert (t.protocol == UPath(target).protocol) or UPath(
                target
            ).protocol == ""
            assert (t.path == UPath(target).path) or (
                t.path == UPath(target).absolute().path
            )
            assert await t.exists()
            assert await t.read_text() == source_text
        else:
            with pytest.raises(UnsupportedOperation):
                await source.rename(target)

    @pytest.mark.parametrize(
        "target_factory",
        [
            lambda obj, name: obj.joinpath(name).absolute().as_posix(),
            lambda obj, name: UPath(obj.absolute().joinpath(name).path),
            lambda obj, name: Path(obj.absolute().joinpath(name).path),
            lambda obj, name: obj.absolute().joinpath(name),
        ],
        ids=[
            "str_absolute",
            "plain_upath_absolute",
            "plain_path_absolute",
            "self_upath_absolute",
        ],
    )
    async def test_rename_with_target_absolute(self, target_factory):
        from upath._chain import Chain
        from upath._chain import FSSpecChainParser
        from upath._protocol import get_upath_protocol

        source = self.path.joinpath("folder1/file2.txt")
        target = target_factory(self.path, "file2_renamed.txt")
        source_text = await source.read_text()
        t = await source.rename(target)
        assert get_upath_protocol(target) in {t.protocol, ""}
        assert t.path == Chain.from_list(
            FSSpecChainParser().unchain(str(target))
        ).active_path.replace("\\", "/")
        assert await t.exists()
        assert await t.read_text() == source_text

    def test_replace(self):
        pass

    def test_resolve(self):
        pass

    async def test_rmdir_no_dir(self):
        p = self.path.joinpath("file1.txt")
        with pytest.raises(NotADirectoryError):
            await p.rmdir()

    async def test_iterdir_no_dir(self):
        p = self.path.joinpath("file1.txt")
        assert await p.is_file()
        with pytest.raises(NotADirectoryError):
            _ = [x async for x in p.iterdir()]

    async def test_rmdir_not_empty(self):
        p = self.path.joinpath("folder1")
        with pytest.raises(OSError, match="not empty"):
            await p.rmdir(recursive=False)

    async def test_fsspec_compat(self):
        fs = self.path.fs
        content = b"a,b,c\n1,2,3\n4,5,6"

        upath1 = self.path / "output1.csv"
        p1 = upath1.path
        await upath1.write_bytes(content)
        assert fs._fs_token == upath1.fs._fs_token
        if fs.cachable:  # codespell:ignore cachable
            assert fs is upath1.fs
        with fs.open(p1) as f:
            assert f.read() == content
        await upath1.unlink()

        upath2 = self.path / "output2.csv"
        p2 = upath2.path
        with fs.open(p2, "wb") as f:
            f.write(content)
        assert await upath2.read_bytes() == content
        await upath2.unlink()

    async def test_move_local(self, tmp_path: Path):
        target = UPath(tmp_path) / "target-file1.txt"
        source = self.path / "file1.txt"
        content = await source.read_text()
        await source.move(target)
        assert target.exists()
        assert target.read_text() == content
        assert not await source.exists()

    async def test_move_into_local(self, tmp_path: Path):
        target_dir = UPath(tmp_path) / "target-dir"
        target_dir.mkdir()
        source = self.path / "file1.txt"
        content = await source.read_text()
        await source.move_into(target_dir)
        target = target_dir / "file1.txt"
        assert target.exists()
        assert target.read_text() == content
        assert not await source.exists()

    async def test_move_memory(self, clear_fsspec_memory_cache):
        target = UPath("memory:///target-file1.txt")
        source = self.path / "file1.txt"
        content = await source.read_text()
        await source.move(target)
        assert target.exists()
        assert target.read_text() == content
        assert not await source.exists()

    async def test_move_into_memory(self, clear_fsspec_memory_cache):
        target_dir = UPath("memory:///target-dir")
        target_dir.mkdir()
        source = self.path / "file1.txt"
        content = await source.read_text()
        await source.move_into(target_dir)
        target = target_dir / "file1.txt"
        assert target.exists()
        assert target.read_text() == content
        assert not await source.exists()

    def prepare_file_system(self):
        self.make_top_folder()
        self.make_test_files()

    def _sync_base(self) -> UPath:
        # reconstruct a synchronous UPath (preserving storage options) to build
        # the fixture tree without needing an event loop in the fixture. Reuse
        # self.path's underlying fs instance so the whole async path lineage
        # (self.path and everything derived from it via joinpath/with_segments)
        # shares one filesystem -- important for non-cachable filesystems such
        # as ftp, where independent instances keep independent dir caches. This
        # mirrors the synchronous suite, where self.path.fs is warmed by setup.
        base = UPath(str(self.path), **dict(self.path.storage_options))
        base._fs_cached = self.path.fs
        return base

    def make_top_folder(self):
        self._sync_base().mkdir(parents=True, exist_ok=True)

    def make_test_files(self):
        base = self._sync_base()
        folder1 = base.joinpath("folder1")
        folder1.mkdir(exist_ok=True)
        for f in ["file1.txt", "file2.txt"]:
            p = folder1.joinpath(f)
            p.touch()
            p.write_text(f)
        file1 = base.joinpath("file1.txt")
        file1.touch()
        file1.write_text("hello world")
        file2 = base.joinpath("file2.txt")
        file2.touch()
        file2.write_bytes(b"hello world")


class AsyncBaseTests(
    JoinablePathTests,
    AsyncReadablePathTests,
    AsyncWritablePathTests,
    AsyncReadWritePathTests,
):
    """Comprehensive async test suite for full read/write AsyncUPath backends."""

    SUPPORTS_EMPTY_DIRS = True
    path: AsyncUPath
