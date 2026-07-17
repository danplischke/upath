import pytest
from fsspec import get_filesystem_class

from upath import AsyncUPath
from upath.implementations.http import HTTPPath

from ..async_cases import AsyncNonWritablePathTests
from ..async_cases import AsyncReadablePathTests
from ..async_cases import JoinablePathTests
from ..utils import OverrideMeta
from ..utils import extends_base
from ..utils import overrides_base
from ..utils import skip_on_windows

pytestmark = pytest.mark.network

try:
    get_filesystem_class("http")
except ImportError:
    pytestmark = pytest.mark.skip


@skip_on_windows
class TestAsyncUPathHttp(
    JoinablePathTests,
    AsyncReadablePathTests,
    AsyncNonWritablePathTests,
    metaclass=OverrideMeta,
):
    @pytest.fixture(autouse=True, scope="function")
    def path(self, http_fixture):
        self.path = AsyncUPath(http_fixture)

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, HTTPPath)

    @extends_base
    async def test_work_at_root(self):
        names = [f.name async for f in self.path.parent.iterdir()]
        assert "folder" in names

    @overrides_base
    async def test_info(self):
        # HTTPPath folders are files too
        p0 = self.path.joinpath("file1.txt")
        p1 = self.path.joinpath("folder1")
        assert await p0.info.exists() is True
        assert await p0.info.is_file() is True
        assert await p0.info.is_dir() is False
        assert await p0.info.is_symlink() is False
        assert await p1.info.exists() is True
        # weird quirk of how directories work in http fsspec
        assert await p1.info.is_file() is True
        assert await p1.info.is_dir() is True
        assert await p1.info.is_symlink() is False
