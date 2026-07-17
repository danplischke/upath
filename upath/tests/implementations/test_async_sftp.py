import pytest

from upath import AsyncUPath
from upath.implementations.sftp import SFTPPath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base
from ..utils import skip_on_windows


@skip_on_windows
class TestAsyncUPathSFTP(AsyncBaseTests, metaclass=OverrideMeta):
    @pytest.fixture(autouse=True)
    def path(self, ssh_fixture):
        self.path = AsyncUPath(ssh_fixture)
        self.prepare_file_system()

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, SFTPPath)
