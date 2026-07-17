import pytest

from upath import AsyncUPath
from upath.implementations.zip import ZipPath

from ..async_cases import AsyncNonWritablePathTests
from ..async_cases import AsyncReadablePathTests
from ..async_cases import JoinablePathTests
from ..utils import OverrideMeta
from ..utils import overrides_base
from .test_zip import zipped_testdir_file  # noqa: F401 (pytest fixture)
from .test_zip import zipped_testdir_file_in_memory  # noqa: F401 (pytest fixture)


class TestAsyncZipPath(
    JoinablePathTests,
    AsyncReadablePathTests,
    AsyncNonWritablePathTests,
    metaclass=OverrideMeta,
):
    @pytest.fixture(autouse=True)
    def path(self, zipped_testdir_file):
        self.path = AsyncUPath("zip://", fo=zipped_testdir_file, mode="r")
        try:
            yield
        finally:
            self.path.fs.clear_instance_cache()

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, ZipPath)


class TestAsyncChainedZipPath(TestAsyncZipPath):
    @pytest.fixture(autouse=True)
    def path(self, zipped_testdir_file_in_memory):
        self.path = AsyncUPath(
            "zip://", fo="/myzipfile.zip", mode="r", target_protocol="memory"
        )
        try:
            yield
        finally:
            self.path.fs.clear_instance_cache()
