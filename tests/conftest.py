from pathlib import Path

import pytest

from autoagentnet.network.executor import NetworkExecutor
from autoagentnet.network.spec import NetworkSpec
from autoagentnet.pricing import PriceBook
from autoagentnet.providers.fake import FakeClient
from autoagentnet.providers.registry import ProviderRegistry
from autoagentnet.runtime.local import LocalRuntime
from autoagentnet.tasks import load_tasks

ROOT = Path(__file__).resolve().parents[1]
EXTERNAL = ROOT / "data/external"


def pytest_configure(config):
    config.addinivalue_line("markers", "needs_external(*paths): the test reads git-ignored benchmark files under "
                            "data/external/ (python scripts/fetch_external.py rebuilds them); it is skipped when one "
                            "is absent")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Session E6, fix 2.1: a test marked needs_external("evidence/math.jsonl", ...) is skipped, with the fetch command,
    on a clone without those files (benchmark text is never committed), instead of failing."""
    marker = item.get_closest_marker("needs_external")
    if marker is not None:
        missing = [p for p in marker.args if not (EXTERNAL / p).exists()]
        if missing:
            pytest.skip(f"needs data/external/{missing[0]} (git-ignored benchmark data): run "
                        "python scripts/fetch_external.py")


@pytest.fixture
def registry() -> ProviderRegistry:
    return ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")


@pytest.fixture
def fake(registry) -> FakeClient:
    client = FakeClient()
    registry.set_client("fake", client)
    return client


@pytest.fixture
def network() -> NetworkSpec:
    return NetworkSpec.from_yaml(ROOT / "configs/networks/dense_3x6.yaml")


@pytest.fixture
def tasks():
    return load_tasks(ROOT / "data/tasks/sample.jsonl")


@pytest.fixture
def pricebook() -> PriceBook:
    return PriceBook.from_yaml(ROOT / "configs/pricing.yaml")


def make_executor(network, registry, pricebook=None, runtime=None, **kwargs) -> NetworkExecutor:
    return NetworkExecutor(
        network,
        runtime or LocalRuntime(registry),
        registry,
        pricebook=pricebook,
        model_override=kwargs.pop("model_override", "fake"),
        **kwargs,
    )
