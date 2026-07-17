"""Async parity tests for S3 (native-async s3fs backend). See conftest.py."""

import sys

import pytest

from upath import AsyncUPath
from upath import UPath
from upath.implementations.cloud import S3Path

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import extends_base
from ..utils import overrides_base


def silence_botocore_datetime_deprecation(cls):
    if sys.version_info >= (3, 12):
        return pytest.mark.filterwarnings(
            "ignore"
            r":datetime.datetime.utcnow\(\) is deprecated"
            ":DeprecationWarning"
        )(cls)
    return cls


@silence_botocore_datetime_deprecation
class TestAsyncUPathS3(AsyncBaseTests, metaclass=OverrideMeta):
    SUPPORTS_EMPTY_DIRS = False

    @pytest.fixture(autouse=True)
    def path(self, s3_fixture):
        path, anon, s3so = s3_fixture
        self.path = AsyncUPath(path, anon=anon, **s3so)
        self.anon = anon
        self.s3so = s3so

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, S3Path)

    @extends_base
    async def test_rmdir(self):
        mock_dir = self.path.joinpath("rmdir_test")
        await mock_dir.joinpath("test.txt").touch()
        await mock_dir.rmdir()
        assert not await mock_dir.exists()
        with pytest.raises(NotADirectoryError):
            await self.path.joinpath("file1.txt").rmdir()

    @extends_base
    async def test_iterdir_root(self):
        client_kwargs = self.path.storage_options["client_kwargs"]
        bucket_path = AsyncUPath("s3://other_test_bucket", client_kwargs=client_kwargs)
        await bucket_path.mkdir()
        await (bucket_path / "test1.txt").touch()
        await (bucket_path / "test2.txt").touch()
        async for x in bucket_path.iterdir():
            assert x.name != ""
            assert await x.exists()

    @extends_base
    def test_native_async_backend(self):
        # S3 must resolve to a native-async fsspec filesystem, not a wrapper
        assert self.path._async_fs.async_impl is True
        assert self.path._async_fs.asynchronous is True

    @extends_base
    @pytest.mark.parametrize(
        "joiner", [["bucket", "path", "file"], ["bucket/path/file"]]
    )
    def test_no_bucket_joinpath(self, joiner):
        path = AsyncUPath("s3://", anon=self.anon, **self.s3so)
        path = path.joinpath(*joiner)
        assert str(path) == "s3://bucket/path/file"

    @extends_base
    def test_relative_to_extra(self):
        assert "file.txt" == str(
            UPath("s3://test_bucket/file.txt").relative_to(UPath("s3://test_bucket"))
        )
