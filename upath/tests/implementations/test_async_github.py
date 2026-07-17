import functools
import os
import platform
import sys

import pytest

from upath import AsyncUPath
from upath.implementations.github import GitHubPath

from ..async_cases import AsyncNonWritablePathTests
from ..async_cases import AsyncReadablePathTests
from ..async_cases import JoinablePathTests
from ..utils import OverrideMeta
from ..utils import overrides_base

pytestmark = [
    pytest.mark.skipif(
        os.environ.get("CI", False)
        and not (
            platform.system() == "Linux" and sys.version_info[:2] in {(3, 9), (3, 13)}
        ),
        reason="Skipping GitHubPath tests to prevent rate limiting on GitHub API.",
    ),
    pytest.mark.network,
]


def xfail_on_github_connection_error(func):
    @functools.wraps(func)
    async def async_wrapper(self, *args, **kwargs):
        try:
            return await func(self, *args, **kwargs)
        except Exception as e:
            _reraise_or_xfail(e)

    @functools.wraps(func)
    def sync_wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception as e:
            _reraise_or_xfail(e)

    import inspect

    return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper


def _reraise_or_xfail(e):
    str_e = str(e)
    if "rate limit exceeded" in str_e or "too many requests for url" in str_e:
        pytest.xfail("GitHub API rate limit exceeded")
    elif (
        "nodename nor servname provided, or not known" in str_e
        or "Network is unreachable" in str_e
        or "NameResolutionError" in str_e
    ):
        pytest.xfail("No internet connection")
    else:
        raise e


def wrap_all_tests(decorator):
    def class_decorator(cls):
        for attr_name in dir(cls):
            if attr_name.startswith("test_"):
                setattr(cls, attr_name, decorator(getattr(cls, attr_name)))
        return cls

    return class_decorator


@wrap_all_tests(xfail_on_github_connection_error)
class TestAsyncUPathGitHubPath(
    JoinablePathTests,
    AsyncReadablePathTests,
    AsyncNonWritablePathTests,
    metaclass=OverrideMeta,
):
    @pytest.fixture(autouse=True)
    def path(self):
        self.path = AsyncUPath("github://ap--:universal_pathlib@test_data/data")

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, GitHubPath)
