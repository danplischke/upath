import pytest

from upath import AsyncUPath
from upath.implementations.hdfs import HDFSPath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base


@pytest.mark.hdfs
class TestAsyncUPathHDFS(AsyncBaseTests, metaclass=OverrideMeta):
    @pytest.fixture(autouse=True)
    def path(self, local_testdir, hdfs):
        host, user, port = hdfs
        path = f"hdfs:{local_testdir}"
        self.path = AsyncUPath(path, host=host, user=user, port=port)
        self.prepare_file_system()

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, HDFSPath)
