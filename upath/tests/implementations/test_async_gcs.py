import pytest

from upath import AsyncUPath
from upath.implementations.cloud import GCSPath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import extends_base
from ..utils import overrides_base
from ..utils import skip_on_windows


@skip_on_windows
class TestAsyncGCSPath(AsyncBaseTests, metaclass=OverrideMeta):
    SUPPORTS_EMPTY_DIRS = False

    @pytest.fixture(autouse=True, scope="function")
    def path(self, gcs_fixture):
        path, endpoint_url = gcs_fixture
        self.path = AsyncUPath(path, endpoint_url=endpoint_url, token="anon")

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, GCSPath)

    @extends_base
    async def test_rmdir(self):
        mock_dir = self.path.joinpath("rmdir_test")
        await mock_dir.joinpath("test.txt").write_text("hello")
        mock_dir.fs.invalidate_cache()
        await mock_dir.rmdir()
        assert not await mock_dir.exists()
        with pytest.raises(NotADirectoryError):
            await self.path.joinpath("file1.txt").rmdir()
