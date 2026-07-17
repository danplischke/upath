import pytest

from upath import AsyncUPath
from upath import UnsupportedOperation
from upath.implementations.cloud import HfPath

from ..async_cases import AsyncNonWritablePathTests
from ..async_cases import AsyncReadablePathTests
from ..async_cases import JoinablePathTests
from ..utils import OverrideMeta
from ..utils import overrides_base

try:
    import huggingface_hub  # noqa: F401
except ImportError:
    pytestmark = pytest.mark.skip


class TestAsyncUPathHf(
    JoinablePathTests,
    AsyncReadablePathTests,
    AsyncNonWritablePathTests,
    metaclass=OverrideMeta,
):
    @pytest.fixture(autouse=True, scope="function")
    def path(self, hf_fixture_with_readonly_mocked_hf_api):
        self.path = AsyncUPath(hf_fixture_with_readonly_mocked_hf_api)

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, HfPath)

    @overrides_base
    async def test_iterdir_parent_iteration(self):
        # HfPath does not support listing all available repositories
        with pytest.raises(UnsupportedOperation):
            _ = [p async for p in self.path.parent.iterdir()]
