from pathlib import Path

import pytest

from upath import AsyncUPath
from upath.implementations.local import LocalPath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base
from ..utils import xfail_if_version


class TestAsyncFSSpecLocal(AsyncBaseTests, metaclass=OverrideMeta):
    @pytest.fixture(autouse=True)
    def path(self, local_testdir):
        self.path = AsyncUPath(f"file://{local_testdir}")

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, LocalPath)

    @overrides_base
    def test_cwd(self):
        cwd = type(self.path).cwd()
        assert isinstance(cwd, LocalPath)
        assert cwd.path == Path.cwd().as_posix()

    @overrides_base
    def test_home(self):
        home = type(self.path).home()
        assert isinstance(home, LocalPath)
        assert home.path == Path.home().as_posix()

    @overrides_base
    def test_chmod(self):
        self.path.joinpath("file1.txt").chmod(777)


@xfail_if_version("fsspec", lt="2023.10.0", reason="requires fsspec>=2023.10.0")
class TestAsyncRayIOFSSpecLocal(TestAsyncFSSpecLocal):
    @pytest.fixture(autouse=True)
    def path(self, local_testdir):
        self.path = AsyncUPath(f"local://{local_testdir}")
