"""A fake vLLM server for offline tests: an httpx transport that answers /tokenize, /detokenize, /v1/models and
/v1/completions the way `vllm serve` does, with outcomes drawn from a World (world.py).

It lets the real client (providers/vllm_local.py), the executor, the call cache and the sampler run end to end with
no GPU, and their output must match `World.table` call for call (tests/test_testbed_pipeline.py).

How it reads a request (the prompts come from sample.py and checkers.py):
  item         the first "[item:<id>]" tag in the prompt.
  model        the served checkpoint name, e.g. "qwen3.5-4b-w4" (family, size, precision).
  thinking     a request with "</think>" in its stop list and no end marker after the assistant opening is the
               thinking phase: it writes min(need, max_tokens) thinking words ("finish_reason" "length" when cut).
               A seed s + 1 there belongs to the sample whose answer phase has seed s (vllm_local's convention).
  answer       the thinking words between the markers are the tokens used; the answer class follows from
               World.outcome. The reply ends with "ANSWER: <class>".
  self-check   a prompt asking for "VERDICT:" gets "VERDICT: yes" or "VERDICT: no" (World.self_check).
  judge        a prompt asking for "CHOICE:" gets "CHOICE: <n>" (World.judge_pick), candidates read from
               "CANDIDATE <n>:" lines.
  logprobs     every answer token gets the sample's mean log-prob signal; tokens on the ANSWER line carry a
               runner-up whose log-prob is lower by the sample's margin signal, so the client's signals come out
               as the world's mean log-prob and margin.
  streaming    (session M1) a request with "stream": true gets the same reply as server-sent events, one chunk per
               word (logprobs with text_offset relative to the completion's start, as vLLM streams them), then a
               usage chunk carrying `metrics` (per-request timing, as `vllm serve --enable-per-request-metrics`) and
               "[DONE]". Timings are plausible, not measured: queue 0, prefill PREFILL_MS_PER_TOKEN per prompt
               token, decode DECODE_MS_PER_TOKEN per output token; `token_delay_s` > 0 really waits between chunks
               so the client's own stamps are spread out.
  /metrics     Prometheus text with vLLM 0.32.0's names (research/lit/vllm_metrics_qwen35_kv.md): KV-cache usage
               (tokens of requests in flight over KV_CAPACITY_TOKENS), running and waiting requests, token counters,
               and the TTFT, inter-token, prefill, decode and queue histograms (sum and count).
"""

from __future__ import annotations

import asyncio
import json
import re

import httpx
import numpy as np

from .world import World

ITEM_RE = re.compile(r"\[item:([^\]]+)\]")
CANDIDATE_RE = re.compile(r"^CANDIDATE (\d+): ANSWER: (\S+)\n[^\n]*\(draw (\d+)\)", re.MULTILINE)
ASSISTANT = "<|assistant|>"
PREFILL_MS_PER_TOKEN = 0.05
DECODE_MS_PER_TOKEN = 10.0
KV_CAPACITY_TOKENS = 500_000


def render(messages: list[dict], template_kwargs: dict) -> str:
    """The fake chat template: thinking off writes an empty thinking block into the prompt, as Qwen's does."""
    text = "".join(f"<|{m['role']}|>{m['content']}" for m in messages) + ASSISTANT
    return text if template_kwargs.get("enable_thinking", True) else text + "<think>\n\n</think>\n\n"


def _completion(text: str, prompt_tokens: int, completion_tokens: int, finish: str, logprobs=None) -> dict:
    choice = {"index": 0, "text": text, "finish_reason": finish, "logprobs": logprobs}
    return {"choices": [choice], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
                                           "total_tokens": prompt_tokens + completion_tokens}}


def _answer_logprobs(text: str, mean_logprob: float, margin: float) -> dict:
    words = re.findall(r"\S+\s*", text)
    offsets, at = [], 0
    for w in words:
        offsets.append(at)
        at += len(w)
    answer_from = text.rfind("ANSWER:") + len("ANSWER:")
    tops = [{w: mean_logprob, "<alt>": mean_logprob - (margin if o >= answer_from else 5.0)} for w, o in zip(words, offsets)]
    return {"tokens": words, "token_logprobs": [mean_logprob] * len(words), "top_logprobs": tops, "text_offset": offsets}


class FakeVLLM:
    def __init__(self, world: World, judge_seed: int = 0, token_delay_s: float = 0.0, per_request_metrics: bool = True):
        self.world = world
        self.calls = 0
        self.token_delay_s = token_delay_s
        self.per_request_metrics = per_request_metrics
        self.in_flight_tokens = 0  # prompt + output tokens of requests being streamed now (the KV-cache usage)
        self.running = 0
        self.totals = {"prompt": 0, "generation": 0, "requests": 0, "ttft_s": 0.0, "itl_s": 0.0, "itl_n": 0,
                       "prefill_s": 0.0, "decode_s": 0.0}

    def handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        path = request.url.path
        if path == "/tokenize":
            text = render(body["messages"], body.get("chat_template_kwargs") or {})
            return httpx.Response(200, json={"tokens": [ord(c) for c in text], "count": len(text)})
        if path == "/detokenize":
            return httpx.Response(200, json={"prompt": "".join(chr(t) for t in body["tokens"])})
        if path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "fake"}]})
        if path == "/v1/completions":
            self.calls += 1
            reply = self.complete(body)
            self.count(reply)
            if body.get("stream"):
                return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=self.stream(reply))
            return httpx.Response(200, json={**reply, **({"metrics": self.metrics_of(reply)} if self.per_request_metrics else {})})
        if path == "/metrics":
            return httpx.Response(200, text=self.prometheus())
        return httpx.Response(404, json={"error": path})

    def metrics_of(self, reply: dict) -> dict:
        """Per-request timing in vLLM's `metrics` form (milliseconds), plausible, from the token counts."""
        usage = reply["usage"]
        ttft = PREFILL_MS_PER_TOKEN * usage["prompt_tokens"]
        generation = DECODE_MS_PER_TOKEN * max(usage["completion_tokens"] - 1, 0)
        return {"queue_time_ms": 0.0, "time_to_first_token_ms": ttft, "generation_time_ms": generation,
                "mean_itl_ms": DECODE_MS_PER_TOKEN if usage["completion_tokens"] > 1 else None,
                "tokens_per_second": usage["completion_tokens"] / ((ttft + generation) / 1000) if ttft + generation else None}

    def count(self, reply: dict) -> None:
        m, usage = self.metrics_of(reply), reply["usage"]
        t = self.totals
        t["prompt"] += usage["prompt_tokens"]
        t["generation"] += usage["completion_tokens"]
        t["requests"] += 1
        t["ttft_s"] += m["time_to_first_token_ms"] / 1000
        t["prefill_s"] += m["time_to_first_token_ms"] / 1000
        t["decode_s"] += m["generation_time_ms"] / 1000
        t["itl_s"] += m["generation_time_ms"] / 1000
        t["itl_n"] += max(usage["completion_tokens"] - 1, 0)

    async def stream(self, reply: dict):
        """The reply as server-sent events, one word per chunk; the KV usage counts it while it streams."""
        choice, usage = reply["choices"][0], reply["usage"]
        tokens = usage["prompt_tokens"] + usage["completion_tokens"]
        self.in_flight_tokens += tokens
        self.running += 1
        try:
            words = re.findall(r"\S+\s*|\s+", choice["text"]) or [""]
            lp, at = choice.get("logprobs"), 0
            for i, word in enumerate(words):
                await asyncio.sleep(self.token_delay_s)
                piece = {"index": 0, "text": word, "finish_reason": choice["finish_reason"] if i == len(words) - 1 else None,
                         "logprobs": None}
                if lp:
                    idx = [j for j, o in enumerate(lp["text_offset"]) if at <= o < at + len(word)]
                    piece["logprobs"] = {k: [lp[k][j] for j in idx] for k in ("tokens", "token_logprobs", "top_logprobs", "text_offset")}
                at += len(word)
                yield f"data: {json.dumps({'choices': [piece]})}\n\n".encode()
            final = {"choices": [], "usage": usage}
            if self.per_request_metrics:
                final["metrics"] = self.metrics_of(reply)
            yield f"data: {json.dumps(final)}\n\n".encode()
            yield b"data: [DONE]\n\n"
        finally:
            self.in_flight_tokens -= tokens
            self.running -= 1

    def prometheus(self) -> str:
        t, label = self.totals, '{model_name="fake",engine="0"}'
        lines = [f"vllm:kv_cache_usage_perc{label} {min(self.in_flight_tokens / KV_CAPACITY_TOKENS, 1.0)}",
                 f"vllm:num_requests_running{label} {self.running}", f"vllm:num_requests_waiting{label} 0",
                 f"vllm:prompt_tokens_total{label} {t['prompt']}", f"vllm:generation_tokens_total{label} {t['generation']}"]
        for name, total, count in (("time_to_first_token_seconds", t["ttft_s"], t["requests"]),
                                   ("inter_token_latency_seconds", t["itl_s"], t["itl_n"]),
                                   ("request_prefill_time_seconds", t["prefill_s"], t["requests"]),
                                   ("request_decode_time_seconds", t["decode_s"], t["requests"]),
                                   ("request_queue_time_seconds", 0.0, t["requests"])):
            lines += [f"vllm:{name}_sum{label} {total}", f"vllm:{name}_count{label} {count}",
                      f'vllm:{name}_bucket{{model_name="fake",engine="0",le="+Inf"}} {count}']
        return "\n".join(lines) + "\n"

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def complete(self, body: dict) -> dict:
        w = self.world
        prompt = body["prompt"]
        idx = w.index[ITEM_RE.search(prompt).group(1)]
        model = body["model"]
        seed = int(body.get("seed", 0))
        assistant = prompt.rsplit(ASSISTANT, 1)[1]
        prompt_tokens = len(prompt) // 4
        if "</think>" in (body.get("stop") or []) and "</think>" not in assistant:
            need = float(w.need_draw(idx, seed - 1))
            used = int(min(round(need), body["max_tokens"]))
            finish = "length" if need > body["max_tokens"] else "stop"
            return _completion("<think>\n" + "w " * used, prompt_tokens, used, finish)
        thinking = assistant.split("<think>", 1)[1].split("</think>", 1)[0] if "<think>" in assistant else ""
        used = len(thinking.split())
        user = prompt.rsplit(ASSISTANT, 1)[0]
        if "VERDICT:" in user:
            candidate = re.search(r"PROPOSED ANSWER:\s*ANSWER:\s*(\S+)", user).group(1)
            right = candidate == str(w.items["gold"].iloc[idx])
            yes = int(w.self_check(idx, model, used, seed, right))
            text = f"Checked.\nVERDICT: {'yes' if yes else 'no'}"
            return _completion(text, prompt_tokens, 8, "stop")
        if "CHOICE:" in user:
            candidates = CANDIDATE_RE.findall(user)
            gold = str(w.items["gold"].iloc[idx])
            pick = w.judge_pick(idx, model, [a == gold for _, a, _ in candidates], [int(s) for *_, s in candidates])
            return _completion(f"Compared.\nCHOICE: {candidates[pick][0]}", prompt_tokens, 8, "stop")
        out = w.outcome(np.array([idx]), model, np.array([used]), np.array([seed]))
        text = f"Working it out step by step (draw {seed}).\nANSWER: {int(out['answer'][0])}"
        logprobs = _answer_logprobs(text, float(out["signal_logprob_mean"][0]), float(out["signal_margin"][0]))
        return _completion(text, prompt_tokens, w.p.answer_tokens, "stop", logprobs if body.get("logprobs") else None)
