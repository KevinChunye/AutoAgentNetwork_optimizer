"""Open-weight models served by vLLM on a GPU the project rents by the hour (price $0 per token).

The client talks to vLLM's OpenAI-compatible server (`vllm serve <checkpoint>`) over HTTP, so the GPU node runs one
server per checkpoint and every generation still goes through autoagentnet's executor and call cache, exactly like
an API model. It uses the plain completions endpoint on a prompt rendered by the server's own chat template
(/tokenize then /detokenize), which is what budget forcing needs: the answer phase continues from
prompt + thinking + end-of-thinking marker (autoagentnet/testbed/budget_forcing.py).

Request options (`request_options` of the model ref; every one optional):
  thinking_budget    B, the most thinking tokens (0 = thinking off, the template's non-thinking mode)
  answer_max_tokens  cap of the answer phase (default: the request's max_tokens)
  seed               sampling seed of the answer phase (the thinking phase uses seed + 1); logged in extra
  top_p, top_k, min_p, presence_penalty   sampling parameters from the model card
  logprobs           how many top alternatives to return per answer token (default 5; 0 = none)
  chat_template_kwargs   extra template switches; enable_thinking is set from the budget unless given here
  think_start, think_end markers (default "<think>", "</think>")

What it measures, per call, in LLMResponse.extra (all free, from the logprobs vLLM returns):
  thinking_tokens    tokens generated in the thinking phase (0 when thinking is off)
  answer_tokens      tokens generated in the answer phase
  forced             True when the thinking hit the budget and was cut (budget forcing fired)
  signal_logprob_mean  mean log-probability of the answer-phase tokens the model sampled (higher = more sure)
  signal_entropy     mean entropy (nats) of the next-token distribution over the answer phase, computed on the top
                     `logprobs` alternatives renormalized to sum to 1 (a lower bound on the true entropy's spread)
  signal_margin      on the final "ANSWER:" line, the smallest gap between the log-probabilities of the best and the
                     second-best next token (a small gap = the answer nearly came out differently); None without
                     an ANSWER line
  busy_s             wall-clock seconds of this call; the sampler turns a shard's measured wall-clock into
                     GPU-seconds per call (autoagentnet/testbed/sample.py)

Timing (session M1; `timing` on by default): every completions request streams (stream_options.include_usage), so
the arrival of each piece of text is timed. A call has one or two phases (thinking, then answer); per call, in extra:
  ttft_s             seconds from the call's start to its first generated token (the thinking phase's when thinking
                     is on), queueing and the chat-template render included
  t_first_thinking_s the thinking phase's first token (None when thinking is off)
  ttfat_s            the answer phase's first token
  prefill_s          per phase, seconds from sending the request to its first token, summed over the phases (this
                     includes the server's queue; vllm_queue_s separates it when the server reports it)
  decode_s           per phase, seconds from its first to its last token, summed
  tpot_s             time per output token after the first: decode_s / (output tokens - phases)
  decode_tok_s       output tokens / decode_s; e2e_tok_s output tokens / busy_s
  vllm_queue_s, vllm_prefill_s, vllm_decode_s   the server's own per-request timing (`metrics` of a server started
                     with --enable-per-request-metrics: queue_time_ms, time_to_first_token_ms from scheduling,
                     generation_time_ms), summed over the phases; None when the server does not report them
The streamed text, finish reason, usage and log-probabilities are joined into exactly what one JSON reply gives
(vLLM streams text_offset relative to the start of the completion), so the signals and the cache are unchanged.
"""

from __future__ import annotations

import json
import math
import time
from typing import Any

import httpx

from ..testbed.budget_forcing import Markers, answer_prompt
from .base import LLMRequest, LLMResponse, Usage

SAMPLING_KEYS = ("top_p", "top_k", "min_p", "presence_penalty")
ANSWER_MARK = "ANSWER:"


def logprob_signals(logprobs: dict | None, text: str) -> dict:
    """Mean log-prob, mean top-k entropy and the answer-line margin from a completions `logprobs` block
    (keys tokens, token_logprobs, top_logprobs, text_offset)."""
    if not logprobs or not logprobs.get("token_logprobs"):
        return {"signal_logprob_mean": None, "signal_entropy": None, "signal_margin": None}
    sampled = [lp for lp in logprobs["token_logprobs"] if lp is not None]
    entropies, gaps = [], []
    tops = logprobs.get("top_logprobs") or []
    offsets = logprobs.get("text_offset") or []
    start = text.rfind(ANSWER_MARK)
    answer_from = start + len(ANSWER_MARK) if start >= 0 else None
    for t, top in enumerate(tops):
        if not top:
            continue
        values = sorted(top.values(), reverse=True)
        weights = [math.exp(v) for v in values]
        total = sum(weights)
        entropies.append(-sum(w / total * math.log(w / total) for w in weights if w > 0))
        on_answer_line = answer_from is not None and t < len(offsets) and offsets[t] >= answer_from
        if on_answer_line and len(values) > 1 and text[offsets[t]:].strip():
            gaps.append(values[0] - values[1])
    return {
        "signal_logprob_mean": sum(sampled) / len(sampled) if sampled else None,
        "signal_entropy": sum(entropies) / len(entropies) if entropies else None,
        "signal_margin": min(gaps) if gaps else None,
    }


class VLLMLocalClient:
    provider = "vllm_local"

    def __init__(self, base_url: str = "http://127.0.0.1:8000", transport: httpx.AsyncBaseTransport | None = None,
                 timeout_s: float = 1800.0, timing: bool = True):
        """transport: an httpx transport to use instead of the network (tests pass a fake vLLM server).
        timing: stream every completions request and time it (module docstring)."""
        self._http = httpx.AsyncClient(base_url=base_url.rstrip("/"), transport=transport, timeout=timeout_s)
        self._rendered: dict[str, str] = {}  # chat-template renders, keyed by the messages and switches
        self.timing = timing

    async def _post(self, path: str, payload: dict) -> dict:
        response = await self._http.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    async def _complete(self, payload: dict, phases: list[dict]) -> dict:
        """One /v1/completions request, as the JSON reply would be; its timing goes into a new entry of `phases`
        (t_send, t_first, t_last on the perf_counter clock, and the server's `metrics` when given)."""
        t_send = time.perf_counter()
        if not self.timing:
            reply = await self._post("/v1/completions", payload)
            phases.append({"t_send": t_send, "t_first": None, "t_last": time.perf_counter(),
                           "metrics": reply.get("metrics")})
            return reply
        body = {**payload, "stream": True, "stream_options": {"include_usage": True}}
        text, finish, usage, metrics, t_first, t_last = [], None, None, None, None, None
        logprobs = {"tokens": [], "token_logprobs": [], "top_logprobs": [], "text_offset": []}
        with_logprobs = False
        async with self._http.stream("POST", "/v1/completions", json=body) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                now = time.perf_counter()
                usage = chunk.get("usage") or usage
                metrics = chunk.get("metrics") or metrics
                for choice in chunk.get("choices") or []:
                    piece = choice.get("text") or ""
                    lp = choice.get("logprobs")
                    if piece or (lp and lp.get("tokens")):
                        t_first = t_first if t_first is not None else now
                        t_last = now
                    text.append(piece)
                    if lp:
                        with_logprobs = True
                        for key in logprobs:
                            logprobs[key] += lp.get(key) or []
                    if choice.get("finish_reason") is not None:
                        finish = choice["finish_reason"]
        if usage is None:
            raise RuntimeError("vLLM stream ended without a usage record (stream_options.include_usage)")
        phases.append({"t_send": t_send, "t_first": t_first, "t_last": t_last or time.perf_counter(),
                       "metrics": metrics})
        choice = {"text": "".join(text), "finish_reason": finish, "logprobs": logprobs if with_logprobs else None}
        return {"choices": [choice], "usage": usage, "metrics": metrics}

    async def render(self, model: str, messages: list[dict], template_kwargs: dict) -> str:
        """The prompt text the server's chat template makes from `messages`, ending with the assistant turn's
        opening (add_generation_prompt)."""
        key = json.dumps([model, messages, template_kwargs], sort_keys=True)
        if key not in self._rendered:
            tokens = await self._post("/tokenize", {"model": model, "messages": messages, "add_generation_prompt": True,
                                                     "chat_template_kwargs": template_kwargs})
            text = await self._post("/detokenize", {"model": model, "tokens": tokens["tokens"]})
            self._rendered[key] = text["prompt"]
        return self._rendered[key]

    async def list_models(self) -> list[str]:
        response = await self._http.get("/v1/models")
        response.raise_for_status()
        return [m["id"] for m in response.json()["data"]]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        opts = dict(request.options)
        budget = int(opts.get("thinking_budget", 0))
        markers = Markers(opts.get("think_start", Markers.start), opts.get("think_end", Markers.end))
        seed = opts.get("seed")
        top_k = int(opts.get("logprobs", 5))
        template_kwargs = {"enable_thinking": budget > 0, **opts.get("chat_template_kwargs", {})}
        messages = ([{"role": "system", "content": request.system}] if request.system else []) + [
            {"role": "user", "content": "\n\n".join(b.text for b in request.blocks)}]
        sampling: dict[str, Any] = {k: opts[k] for k in SAMPLING_KEYS if k in opts}
        if request.temperature is not None:
            sampling["temperature"] = request.temperature

        start = time.perf_counter()
        prompt = await self.render(request.model, messages, template_kwargs)
        usage = Usage()
        thinking, forced = "", False
        phases: list[dict] = []
        if budget > 0:
            think = await self._complete({
                "model": request.model, "prompt": prompt, "max_tokens": budget, "stop": [markers.end],
                **sampling, **({"seed": seed + 1} if seed is not None else {})}, phases)
            choice = think["choices"][0]
            thinking, forced = choice["text"], choice.get("finish_reason") == "length"
            usage = usage + Usage(input_tokens=think["usage"]["prompt_tokens"],
                                  output_tokens=think["usage"]["completion_tokens"])
            prompt = answer_prompt(prompt, thinking, markers)
        reply = await self._complete({
            "model": request.model, "prompt": prompt,
            "max_tokens": int(opts.get("answer_max_tokens", request.max_tokens)),
            **sampling, **({"seed": seed} if seed is not None else {}), **({"logprobs": top_k} if top_k else {})}, phases)
        choice = reply["choices"][0]
        answer_tokens = reply["usage"]["completion_tokens"]
        thinking_tokens = usage.output_tokens
        usage = usage + Usage(input_tokens=reply["usage"]["prompt_tokens"], output_tokens=answer_tokens)
        latency_s = time.perf_counter() - start
        extra = {"thinking_budget": budget, "thinking_tokens": thinking_tokens, "answer_tokens": answer_tokens,
                 "forced": forced, "seed": seed, "busy_s": latency_s, "thinking": thinking,
                 **logprob_signals(choice.get("logprobs"), choice["text"]),
                 **phase_timing(phases, start, latency_s, usage.output_tokens, thinking_phase=budget > 0)}
        return LLMResponse(text=choice["text"], usage=usage, model=request.model, provider=self.provider,
                           latency_s=latency_s, stop_reason=choice.get("finish_reason"), extra=extra)

    async def aclose(self) -> None:
        await self._http.aclose()


def phase_timing(phases: list[dict], start: float, latency_s: float, output_tokens: int, thinking_phase: bool) -> dict:
    """The timing fields of one call from its phases (module docstring); None where a phase was not streamed."""
    streamed = all(p["t_first"] is not None for p in phases) and bool(phases)
    out = {"streamed": streamed, "ttft_s": None, "ttft_kind": "first_token" if streamed else None,
           "t_first_thinking_s": None, "ttfat_s": None, "prefill_s": None, "decode_s": None, "tpot_s": None,
           "decode_tok_s": None, "decode_basis": None, "total_s": latency_s, "retries": 0, "retry_s": 0.0,
           "e2e_tok_s": output_tokens / latency_s if latency_s > 0 else None}
    if streamed:
        decode = sum(p["t_last"] - p["t_first"] for p in phases)
        out.update(ttft_s=phases[0]["t_first"] - start, ttfat_s=phases[-1]["t_first"] - start,
                   t_first_thinking_s=phases[0]["t_first"] - start if thinking_phase else None,
                   prefill_s=sum(p["t_first"] - p["t_send"] for p in phases), decode_s=decode,
                   tpot_s=decode / (output_tokens - len(phases)) if output_tokens > len(phases) else None,
                   decode_tok_s=output_tokens / decode if decode > 0 else None,
                   decode_basis="all_output" if decode > 0 else None)
    server = [p["metrics"] for p in phases if p.get("metrics")]
    for name, key in (("vllm_queue_s", "queue_time_ms"), ("vllm_prefill_s", "time_to_first_token_ms"),
                      ("vllm_decode_s", "generation_time_ms")):
        values = [m.get(key) for m in server]
        out[name] = sum(values) / 1000 if server and len(server) == len(phases) and None not in values else None
    return out
