import pytest

from upath import AsyncUPath
from upath.implementations.ftp import FTPPath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base
from ..utils import skip_on_windows


@skip_on_windows
class TestAsyncUPathFTP(AsyncBaseTests, metaclass=OverrideMeta):
    @pytest.fixture(autouse=True)
    def path(self, ftp_server):
        self.path = AsyncUPath("", protocol="ftp", **ftp_server)
        self.prepare_file_system()

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, FTPPath)
