"""OpenAI's 400 "invalid_prompt" becomes a refused, unbilled empty reply instead of failing the run; offline."""

import asyncio

import pytest

openai = pytest.importorskip("openai")
httpx2 = pytest.importorskip("httpx2")

from autoagentnet.evidence.panel import REFUSAL_STOP_REASONS, grade  # noqa: E402
from autoagentnet.providers.base import Block, LLMRequest  # noqa: E402
from autoagentnet.providers.openai_compat import OpenAICompatClient, blocked_prompt  # noqa: E402
from autoagentnet.tasks import Task  # noqa: E402


def error(code: str):
    request = httpx2.Request("POST", "https://api.openai.com/v1/chat/completions")
    body = {"message": "flagged", "type": "invalid_request_error", "param": None, "code": code}
    return openai.BadRequestError("flagged", response=httpx2.Response(400, request=request), body=body)


class Raising:
    """Raises the given errors in turn, then answers with `then` (when given)."""

    def __init__(self, *excs, then=None):
        self.excs, self.then, self.calls = list(excs), then, 0

    async def create(self, **kwargs):
        self.calls += 1
        if self.excs:
            raise self.excs.pop(0)
        return self.then


def client_raising(*excs, then=None) -> OpenAICompatClient:
    client = OpenAICompatClient(api_key="not-a-key", send_temperature=False)
    client._client.chat.completions.with_raw_response = Raising(*excs, then=then)  # no network
    return client


def request() -> LLMRequest:
    return LLMRequest(model="gpt-6-luna", system="s", blocks=[Block(text="task")], max_tokens=10)


def test_a_prompt_blocked_on_every_attempt_is_an_empty_refused_reply():
    client = client_raising(*[error("invalid_prompt")] * 3)
    out = asyncio.run(client.complete(request()))
    assert client._client.chat.completions.with_raw_response.calls == 3
    assert out.text == "" and out.stop_reason == "invalid_prompt" and out.usage.output_tokens == 0
    assert out.stop_reason in REFUSAL_STOP_REASONS
    item = Task(id="bbeh-x-1", prompt="?", answer="(B)", grader="bbeh")
    assert grade("bbeh", "base", item, out.text, out.stop_reason) == {"answer": None, "parsed": False, "correct": 0.0, "prob": None}


def test_other_bad_requests_still_fail():
    assert blocked_prompt(error("invalid_prompt")) and not blocked_prompt(error("context_length_exceeded"))
    with pytest.raises(openai.BadRequestError):
        asyncio.run(client_raising(error("context_length_exceeded")).complete(request()))


class Raw:
    """A stand-in for the SDK's raw response: headers and parse()."""

    def __init__(self):
        from types import SimpleNamespace as NS

        self.headers = {}
        self.completion = NS(model="gpt-6-luna", usage=NS(prompt_tokens=10, completion_tokens=3, prompt_tokens_details=None),
                             choices=[NS(message=NS(content="ANSWER: (B)"), finish_reason="stop")])

    def parse(self):
        return self.completion


def test_a_block_that_clears_on_retry_gives_the_real_answer():
    """Audit 54: the filter is intermittent, so one block must not become a permanent wrong answer."""
    client = client_raising(error("invalid_prompt"), then=Raw())
    out = asyncio.run(client.complete(request()))
    assert out.text == "ANSWER: (B)" and out.stop_reason == "stop" and out.usage.output_tokens == 3
    assert client._client.chat.completions.with_raw_response.calls == 2
