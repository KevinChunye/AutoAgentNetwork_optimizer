"""Key hygiene (session E5, patch 2.1): keys come only from AAN_* variables, and every SDK client gets its key and
endpoint explicitly, so a stray ANTHROPIC_API_KEY or OPENAI_API_KEY is never used. Offline: clients are built but
never called."""

import pytest
from pydantic import ValidationError

from autoagentnet.providers.registry import KEY_PREFIX, ModelConfig, ProviderRegistry

PROVIDERS = "configs/providers.yaml"


@pytest.fixture
def stray_keys_only(monkeypatch):
    """Dummy vendor-default keys set, every AAN_* key unset."""
    import os

    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-claude-code-key")
    monkeypatch.setenv("OPENAI_API_KEY", "dummy-other-account-key")
    for name in [n for n in os.environ if n.startswith(KEY_PREFIX) and n.endswith(("_KEY", "_API_KEY"))]:
        monkeypatch.delenv(name)


def test_every_configured_key_variable_is_aan():
    registry = ProviderRegistry.from_yaml(PROVIDERS)
    names = [cfg.api_key_env for cfg in registry.models.values() if cfg.api_key_env]
    assert names and all(n.startswith(KEY_PREFIX) for n in names)


def test_clients_refuse_instead_of_borrowing_stray_keys(stray_keys_only):
    registry = ProviderRegistry.from_yaml(PROVIDERS)
    keyed = [ref for ref, cfg in registry.models.items() if cfg.api_key_env]
    assert keyed
    for ref in keyed:
        with pytest.raises(RuntimeError, match=registry.config(ref).api_key_env):
            registry.client(ref)


def test_sdk_clients_need_an_explicit_key(stray_keys_only):
    from autoagentnet.providers.anthropic_provider import AnthropicClient
    from autoagentnet.providers.openai_compat import OpenAICompatClient

    for cls in (AnthropicClient, OpenAICompatClient):
        with pytest.raises(ValueError, match="explicit api_key"):
            cls(api_key=None)


@pytest.mark.parametrize("cfg", [
    {"provider": "anthropic", "model": "m", "api_key_env": "ANTHROPIC_API_KEY"},
    {"provider": "openai_compat", "model": "m", "api_key_env": "OPENAI_API_KEY"},
    {"provider": "anthropic", "model": "m"},  # no key variable at all: the SDK would fall back
])
def test_config_rejects_non_aan_key_variables(cfg):
    with pytest.raises(ValidationError):
        ModelConfig(**cfg)


def test_key_and_endpoint_are_passed_explicitly(monkeypatch):
    monkeypatch.setenv("AAN_ANTHROPIC_API_KEY", "dummy-aan-anthropic")
    monkeypatch.setenv("AAN_OPENAI_API_KEY", "dummy-aan-openai")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "dummy-claude-code-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://wrong.example")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://wrong.example/v1")
    registry = ProviderRegistry.from_yaml(PROVIDERS)
    anth = registry.client("haiku")._client
    assert anth.api_key == "dummy-aan-anthropic" and "api.anthropic.com" in str(anth.base_url)
    oai = registry.client("gpt_small")._client
    assert oai.api_key == "dummy-aan-openai" and "api.openai.com" in str(oai.base_url)
