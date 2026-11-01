"""Model refs: short names ("haiku", "gpt_small") that map to a provider + model ID.

Agents and network configs only ever name a model ref, so pointing an agent at a
different provider means editing ``configs/providers.yaml``, not code.

To add a provider that does not speak the OpenAI API: write a class with
``provider: str`` and ``async def complete(self, request) -> LLMResponse``, then
add a factory to ``FACTORIES`` below.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Literal

import yaml
from pydantic import BaseModel, model_validator

from .base import LLMClient


DEFAULT_ACCOUNTS = {"anthropic": "anthropic", "openai_compat": "openai", "fake": "fake", "vllm_local": "gpu"}
# Key hygiene (session E5, patch 2.1): a key is read only from a variable named AAN_*, and every SDK client gets
# the key and the endpoint explicitly. Left to themselves, the SDKs fall back to ANTHROPIC_API_KEY / OPENAI_API_KEY
# (which may belong to Claude Code or another account) and to ANTHROPIC_BASE_URL / OPENAI_BASE_URL.
KEY_PREFIX = "AAN_"
DEFAULT_BASE_URLS = {"anthropic": "https://api.anthropic.com", "openai_compat": "https://api.openai.com/v1"}


class ModelConfig(BaseModel):
    provider: Literal["anthropic", "openai_compat", "fake", "vllm_local"]
    model: str  # model ID sent to the API
    account: str | None = None  # who is billed; must match a key in configs/budget.yaml
    model_env: str | None = None  # if this env var is set, its value replaces `model`
    api_key_env: str | None = None  # env var that holds the API key
    workspace_id_env: str | None = None  # anthropic only: env var with the workspace ID, sent as the
    # anthropic-workspace-id header; needed when the key is not scoped to a workspace, ignored when unset
    base_url: str | None = None
    base_url_env: str | None = None  # env var that holds the base URL (wins over base_url)
    token_param: str = "max_completion_tokens"  # openai_compat only
    send_temperature: bool = True  # openai_compat only
    long_requests: Literal["stream", "background"] = "stream"  # openai_compat only: transport above 8,192 output
    # tokens (D5: "background" uses the Responses API's background mode; OpenAI's own API only). Not in any cache key
    request_options: dict = {}  # extra API fields, e.g. {"reasoning_effort": "low"}

    @model_validator(mode="after")
    def _key_from_aan_only(self) -> "ModelConfig":
        if self.api_key_env and not self.api_key_env.startswith(KEY_PREFIX):
            raise ValueError(f"api_key_env must name an {KEY_PREFIX}* variable, not {self.api_key_env!r} (key hygiene: "
                             "ANTHROPIC_API_KEY and OPENAI_API_KEY are never read)")
        if self.provider == "anthropic" and not self.api_key_env:
            raise ValueError("an anthropic ref needs api_key_env (an AAN_* variable); without it the SDK would read "
                             "ANTHROPIC_API_KEY")
        return self

    def resolved_account(self) -> str:
        return self.account or DEFAULT_ACCOUNTS[self.provider]

    def resolved_model(self) -> str:
        if self.model_env and os.getenv(self.model_env):
            return os.environ[self.model_env]
        return self.model

    def resolved_base_url(self) -> str | None:
        """The endpoint, always explicit for real providers: base_url_env, else base_url, else the vendor default (so
        the SDK never reads ANTHROPIC_BASE_URL or OPENAI_BASE_URL on its own)."""
        if self.base_url_env and os.getenv(self.base_url_env):
            return os.environ[self.base_url_env]
        return self.base_url or DEFAULT_BASE_URLS.get(self.provider)

    def resolved_api_key(self) -> str | None:
        return os.getenv(self.api_key_env) if self.api_key_env else None

    def resolved_workspace_id(self) -> str | None:
        return os.getenv(self.workspace_id_env) if self.workspace_id_env else None


def _require_key(cfg: ModelConfig) -> str | None:
    """The key from cfg.api_key_env. Missing keys fail loudly instead of letting an SDK
    fall back to some other variable (such as Claude Code's own ANTHROPIC_API_KEY)."""
    key = cfg.resolved_api_key()
    if cfg.api_key_env and not key:
        raise RuntimeError(f"environment variable {cfg.api_key_env} is not set (needed for model {cfg.model})")
    return key


def _make_anthropic(cfg: ModelConfig) -> LLMClient:
    from .anthropic_provider import AnthropicClient

    return AnthropicClient(api_key=_require_key(cfg), base_url=cfg.resolved_base_url(),
                           workspace_id=cfg.resolved_workspace_id())


def _make_openai_compat(cfg: ModelConfig) -> LLMClient:
    from .openai_compat import OpenAICompatClient

    return OpenAICompatClient(
        api_key=_require_key(cfg) or "not-needed",  # local servers without api_key_env accept any key
        base_url=cfg.resolved_base_url(),
        token_param=cfg.token_param,
        send_temperature=cfg.send_temperature,
        long_requests=cfg.long_requests,
    )


def _make_fake(cfg: ModelConfig) -> LLMClient:
    from .fake import FakeClient

    return FakeClient()


def _make_vllm_local(cfg: ModelConfig) -> LLMClient:
    from .vllm_local import VLLMLocalClient

    return VLLMLocalClient(base_url=cfg.resolved_base_url() or "http://127.0.0.1:8000")


FACTORIES: dict[str, Callable[[ModelConfig], LLMClient]] = {
    "anthropic": _make_anthropic,
    "openai_compat": _make_openai_compat,
    "fake": _make_fake,
    "vllm_local": _make_vllm_local,
}


class ProviderRegistry:
    """Builds one client per model ref, lazily, and reuses it."""

    def __init__(self, models: dict[str, ModelConfig], timing: bool | None = None):
        """timing (session M1): True streams every API request and records its event times, False keeps one JSON
        reply per request (above the stream thresholds a request streams either way); None leaves each client's own
        default (vllm_local streams, API clients do not). Transport only: no cache key depends on it."""
        self.models = models
        self._clients: dict[str, LLMClient] = {}
        self.timing = timing

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ProviderRegistry":
        raw = yaml.safe_load(Path(path).read_text())
        return cls({name: ModelConfig(**cfg) for name, cfg in raw["models"].items()})

    def config(self, ref: str) -> ModelConfig:
        if ref not in self.models:
            raise KeyError(f"unknown model ref {ref!r}; known: {sorted(self.models)}")
        return self.models[ref]

    def provider_of(self, ref: str) -> str:
        return self.config(ref).provider

    def account_of(self, ref: str) -> str:
        return self.config(ref).resolved_account()

    def options_of(self, ref: str) -> dict:
        return self.config(ref).request_options

    def model_id(self, ref: str) -> str:
        return self.config(ref).resolved_model()

    def client(self, ref: str) -> LLMClient:
        if ref not in self._clients:
            cfg = self.config(ref)
            client = FACTORIES[cfg.provider](cfg)
            if self.timing is not None and hasattr(client, "timing"):
                client.timing = self.timing
            self._clients[ref] = client
        return self._clients[ref]

    def built_refs(self) -> list[str]:
        """The model refs a client has been built for (the refs this run actually called)."""
        return list(self._clients)

    def set_timing(self, timing: bool | None) -> None:
        """Set timing for clients built from now on and for those already built."""
        self.timing = timing
        if timing is None:
            return
        for client in self._clients.values():
            if hasattr(client, "timing"):
                client.timing = timing

    def rate_limits(self) -> dict[str, dict]:
        """The last rate-limit headers each live client saw, by model ref (empty for the fake model)."""
        out = {}
        for ref, client in self._clients.items():
            limits = getattr(client, "rate_limits", None)
            if limits:
                out[ref] = limits
        return out

    def set_client(self, ref: str, client: LLMClient) -> None:
        """Inject a ready-made client (tests, custom wrappers); it takes the registry's timing switch when set."""
        if self.timing is not None and hasattr(client, "timing"):
            client.timing = self.timing
        self._clients[ref] = client
