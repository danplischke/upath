import stat

import pytest

from upath import AsyncUPath
from upath import UnsupportedOperation
from upath import UPath
from upath.implementations.data import DataPath

from ..async_cases import AsyncNonWritablePathTests
from ..async_cases import AsyncReadablePathTests
from ..async_cases import JoinablePathTests
from ..utils import OverrideMeta
from ..utils import overrides_base


class TestAsyncUPathDataPath(
    JoinablePathTests,
    AsyncReadablePathTests,
    AsyncNonWritablePathTests,
    metaclass=OverrideMeta,
):
    """Async parity tests for the read-only DataPath implementation."""

    @pytest.fixture(autouse=True)
    def path(self):
        self.path = AsyncUPath("data:text/plain;base64,aGVsbG8gd29ybGQ=")

    @pytest.fixture(autouse=True)
    def path_file(self, path):
        self.path_file = self.path

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, DataPath)

    # -- JoinablePath overrides (pure path algebra, synchronous) ----------

    @overrides_base
    def test_with_segments(self):
        with pytest.raises(UnsupportedOperation):
            self.path.with_segments("data:text/plain;base64,", "aGVsbG8K")
        self.path.with_segments("data:text/plain;base64,aGVsbG8K")

    @overrides_base
    def test_parents(self):
        assert self.path.parents == []

    @overrides_base
    def test_with_name(self):
        with pytest.raises(UnsupportedOperation):
            self.path.with_name("newname")

    @overrides_base
    def test_with_suffix(self):
        with pytest.raises(UnsupportedOperation):
            self.path.with_suffix(".new")

    @overrides_base
    def test_with_stem(self):
        with pytest.raises(UnsupportedOperation):
            self.path.with_stem("newname")

    @overrides_base
    def test_suffix(self):
        assert self.path.suffix == ""

    @overrides_base
    def test_suffixes(self):
        assert self.path.suffixes == []

    @overrides_base
    def test_repr_after_with_name(self):
        with pytest.raises(UnsupportedOperation):
            repr(self.path.with_name("data:,ABC"))

    @overrides_base
    def test_repr_after_with_suffix(self):
        with pytest.raises(UnsupportedOperation):
            repr(self.path.with_suffix(""))

    @overrides_base
    def test_child_path(self):
        with pytest.raises(UnsupportedOperation):
            super().test_child_path()

    @overrides_base
    def test_pickling_child_path(self):
        with pytest.raises(UnsupportedOperation):
            super().test_pickling_child_path()

    @overrides_base
    def test_relative_to(self):
        with pytest.raises(ValueError):
            self.path.relative_to("data:,ABC")
        self.path.relative_to(self.path)

    @overrides_base
    def test_is_relative_to(self):
        assert not self.path.is_relative_to("data:,ABC")
        assert self.path.is_relative_to(self.path)

    @overrides_base
    def test_full_match(self):
        assert self.path.full_match("*")
        assert not self.path.full_match("xxx")

    @overrides_base
    def test_trailing_slash_joinpath_is_identical(self):
        with pytest.raises(UnsupportedOperation):
            super().test_trailing_slash_joinpath_is_identical()

    @overrides_base
    def test_trailing_slash_is_stripped(self):
        with pytest.raises(UnsupportedOperation):
            super().test_trailing_slash_is_stripped()

    @overrides_base
    def test_parents_end_at_anchor(self):
        with pytest.raises(UnsupportedOperation):
            super().test_parents_end_at_anchor()

    @overrides_base
    def test_anchor_is_its_own_parent(self):
        assert self.path.path == self.path.parent.path

    @overrides_base
    def test_private_url_attr_in_sync(self):
        assert self.path._url

    # -- ReadablePath overrides (async) -----------------------------------

    @overrides_base
    async def test_stat_dir_st_mode(self):
        st = await self.path.stat()
        assert not stat.S_ISDIR(st.st_mode)

    @overrides_base
    async def test_exists(self):
        assert await self.path.exists()

    @overrides_base
    async def test_glob(self):
        assert [p async for p in self.path.glob("*")] == []

    @overrides_base
    async def test_rglob(self):
        assert [p async for p in self.path.rglob("*")] == []

    @overrides_base
    async def test_is_dir(self):
        assert not await self.path.is_dir()

    @overrides_base
    async def test_is_file(self):
        assert await self.path.is_file()

    @overrides_base
    async def test_iterdir(self):
        with pytest.raises(NotADirectoryError):
            _ = [p async for p in self.path.iterdir()]

    @overrides_base
    async def test_iterdir_parent_iteration(self):
        with pytest.raises(NotADirectoryError):
            _ = [p async for p in self.path.parent.iterdir()]

    @overrides_base
    async def test_iterdir2(self):
        with pytest.raises(NotADirectoryError):
            _ = [p async for p in self.path_file.iterdir()]

    @overrides_base
    async def test_iterdir_trailing_slash(self):
        with pytest.raises(UnsupportedOperation):
            self.path.joinpath("folder1/")

    @overrides_base
    async def test_read_bytes(self):
        assert await self.path.read_bytes() == b"hello world"

    @overrides_base
    async def test_read_text(self):
        assert await self.path.read_text() == "hello world"

    @overrides_base
    async def test_walk(self):
        assert [x async for x in self.path.walk()] == []

    @overrides_base
    async def test_walk_top_down_false(self):
        assert [x async for x in self.path.walk(top_down=False)] == []

    @overrides_base
    async def test_info(self):
        p0 = self.path
        assert await p0.info.exists() is True
        assert await p0.info.is_file() is True
        assert await p0.info.is_dir() is False
        assert await p0.info.is_symlink() is False

    # -- NonWritablePath overrides (data has nuanced write semantics) ------

    @overrides_base
    async def test_mkdir_raises(self):
        # DataPaths always exist and are files
        with pytest.raises(FileExistsError):
            await self.path_file.mkdir()

    @overrides_base
    async def test_touch_raises(self):
        # DataPaths always exist, so touch is a noop (no error)
        await self.path_file.touch()

    @overrides_base
    async def test_unlink(self):
        with pytest.raises(UnsupportedOperation):
            await self.path_file.unlink()

    @overrides_base
    async def test_copy_into__dir_to_str_tempdir(self):
        # There are no directories in DataPath
        assert not await self.path.is_dir()

    @overrides_base
    async def test_samefile(self):
        f1 = AsyncUPath("data:text/plain;base64,aGVsbG8gd29ybGQ=")
        f2 = AsyncUPath("data:text/plain;base64,SGVsbG8gd29ybGQ=")
        assert await f1.samefile(f2) is False
        assert await f1.samefile(f2.path) is False
        assert await f1.samefile(f1) is True
        assert await f1.samefile(f1.path) is True
