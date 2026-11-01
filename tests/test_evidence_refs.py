"""Model refs of the evidence plan (step 0.4): each resolves to the right model, account and setting,
builds the payload its vendor expects, and runs offline when its client is swapped for the fake model."""

import asyncio

import pytest

from autoagentnet.agents.agent import run_agent
from autoagentnet.agents.spec import AgentInput, AgentSpec
from autoagentnet.pricing import PriceBook
from autoagentnet.providers.anthropic_provider import AnthropicClient
from autoagentnet.providers.base import Block, LLMRequest
from autoagentnet.providers.fake import FakeClient
from autoagentnet.providers.openai_compat import OpenAICompatClient
from autoagentnet.providers.registry import ProviderRegistry
from conftest import ROOT

REFS = {  # ref: (model ID, account, request options)
    "haiku_nothink": ("claude-haiku-5-5", "anthropic", {"thinking": {"type": "disabled"}}),
    "haiku": ("claude-haiku-5-5", "anthropic", {}),
    "sonnet_nothink": ("claude-sonnet-5-5", "anthropic", {"thinking": {"type": "between_tools"}}),
    "opus_nothink": ("claude-opus-5-5", "anthropic", {"output_config": {"effort": "low"}}),
    "luna_none": ("gpt-6-luna", "openai", {"reasoning_effort": "none"}),
    "luna_med": ("gpt-6-luna", "openai", {"reasoning_effort": "medium"}),
    "sol61_low": ("gpt-6.1-sol", "openai", {"reasoning_effort": "low"}),
    "astra_low": ("gpt-6-astra", "openai", {"reasoning_effort": "low"}),
}
REQUEST = LLMRequest(model="m", system="sys", blocks=[Block(text="TASK", cache=True), Block(text="go")], max_tokens=50)


@pytest.fixture
def evidence_registry(monkeypatch):
    monkeypatch.setenv("AAN_OPENAI_MODEL", "gpt-should-not-apply")  # the evidence refs ignore this override
    return ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")


@pytest.mark.parametrize("ref", sorted(REFS))
def test_ref_resolves_model_account_and_setting(evidence_registry, ref):
    model, account, options = REFS[ref]
    assert evidence_registry.model_id(ref) == model
    assert evidence_registry.account_of(ref) == account
    assert evidence_registry.options_of(ref) == options


@pytest.mark.parametrize("ref", sorted(REFS))
def test_ref_builds_its_vendor_payload_without_a_temperature(evidence_registry, ref):
    cfg = evidence_registry.config(ref)
    request = REQUEST.model_copy(update={"model": cfg.resolved_model(), "options": cfg.request_options, "temperature": None})
    if cfg.provider == "anthropic":
        payload = AnthropicClient.build_payload(request)
    else:
        payload = OpenAICompatClient(api_key="x", send_temperature=cfg.send_temperature).build_payload(request)
        assert payload["reasoning_effort"] == cfg.request_options["reasoning_effort"]
        assert "max_completion_tokens" in payload  # reasoning tokens count against it
    assert "temperature" not in payload
    assert payload["model"] == REFS[ref][0]


@pytest.mark.parametrize("ref", sorted(REFS))
def test_ref_runs_offline_on_the_fake_client(evidence_registry, ref):
    evidence_registry.set_client(ref, FakeClient())
    spec = AgentSpec(agent_id="solve.0", stage="solve", index=0, model=ref, system="s", instruction="Solve.",
                     max_tokens=100, temperature=None)
    out = asyncio.run(run_agent(spec, AgentInput(task_id="t", task="2+2"), evidence_registry))
    assert out.content and out.provider == "fake"


def test_every_evidence_model_is_priced():
    book = PriceBook.from_yaml(ROOT / "configs/pricing.yaml")
    missing = sorted({model for model, _, _ in REFS.values()} - set(book.prices))
    # gpt-6.1-sol and gpt-6-astra arrive with Kevin's pricing edit (plan, "Kevin's two edits"); until
    # then a paid call to them fails closed with UnknownPrice, which is the safe direction.
    assert set(missing) <= {"gpt-6.1-sol", "gpt-6-astra"}
