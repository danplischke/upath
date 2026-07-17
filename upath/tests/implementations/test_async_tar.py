import pytest

from upath import AsyncUPath
from upath.implementations.tar import TarPath

from ..async_cases import AsyncNonWritablePathTests
from ..async_cases import AsyncReadablePathTests
from ..async_cases import JoinablePathTests
from ..utils import OverrideMeta
from ..utils import overrides_base
from .test_tar import tarred_testdir_file  # noqa: F401 (pytest fixture)
from .test_tar import tarred_testdir_file_in_memory  # noqa: F401 (pytest fixture)


class TestAsyncTarPath(
    JoinablePathTests,
    AsyncReadablePathTests,
    AsyncNonWritablePathTests,
    metaclass=OverrideMeta,
):
    @pytest.fixture(autouse=True)
    def path(self, tarred_testdir_file):
        self.path = AsyncUPath("tar://", fo=tarred_testdir_file)

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, TarPath)


class TestAsyncChainedTarPath(TestAsyncTarPath):
    @pytest.fixture(autouse=True)
    def path(self, tarred_testdir_file_in_memory):
        self.path = AsyncUPath("tar://::memory:///mytarfile.tar")
