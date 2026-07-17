import pytest

from upath import AsyncUPath
from upath.implementations.cached import SimpleCachePath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base


class TestAsyncSimpleCachePath(AsyncBaseTests, metaclass=OverrideMeta):
    @pytest.fixture(autouse=True)
    def path(self, local_testdir):
        if not local_testdir.startswith("/"):
            local_testdir = "/" + local_testdir
        self.path = AsyncUPath(f"simplecache::memory:{local_testdir}")
        self.prepare_file_system()

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, SimpleCachePath)
