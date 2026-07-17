import pytest

from upath import AsyncUPath
from upath.implementations.smb import SMBPath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base
from ..utils import skip_on_windows


@skip_on_windows
class TestAsyncUPathSMB(AsyncBaseTests, metaclass=OverrideMeta):
    @pytest.fixture(autouse=True)
    def path(self, smb_fixture):
        self.path = AsyncUPath(smb_fixture)
        self.prepare_file_system()

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, SMBPath)

    @overrides_base
    @pytest.mark.parametrize(
        "pattern",
        (
            "*.txt",
            pytest.param(
                "*",
                marks=pytest.mark.xfail(
                    reason="SMBFileSystem.info appends '/' to dirs"
                ),
            ),
            "**/*.txt",
        ),
    )
    async def test_glob(self, pathlib_base, pattern):
        await super().test_glob(pathlib_base, pattern)
