import pytest

from upath import AsyncUPath
from upath.implementations.cloud import AzurePath

from ..async_cases import AsyncBaseTests
from ..utils import OverrideMeta
from ..utils import overrides_base
from ..utils import skip_on_windows


@skip_on_windows
class TestAsyncAzurePath(AsyncBaseTests, metaclass=OverrideMeta):
    SUPPORTS_EMPTY_DIRS = False

    @pytest.fixture(autouse=True, scope="function")
    def path(self, azurite_credentials, azure_fixture):
        account_name = "devstoreaccount1"
        account_key = (
            "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/"
            "K1SZFPTOtr/KBHBeksoGMGw=="
        )
        self.storage_options = {
            "account_name": account_name,
            "account_key": account_key,
            "connection_string": (
                "DefaultEndpointsProtocol=http;"
                f"AccountName={account_name};AccountKey={account_key};"
                "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
            ),
        }
        self.path = AsyncUPath(azure_fixture, **self.storage_options)
        self.prepare_file_system()

    @overrides_base
    def test_is_correct_class(self):
        assert isinstance(self.path, AsyncUPath)
        assert isinstance(self.path, AzurePath)
