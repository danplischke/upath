import pytest

from upath import AsyncUPath
from upath.implementations.webdav import WebdavPath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base


class TestAsyncUPathWebdav(AsyncBaseTests, metaclass=OverrideMeta):
    @pytest.fixture(autouse=True, scope="function")
    def path(self, webdav_fixture):
        self.path = AsyncUPath(webdav_fixture, auth=("USER", "PASSWORD"))

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, WebdavPath)
