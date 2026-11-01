"""KV-cache memory of open-weight calls, estimated from the model's config.json (session M1).

Plain words first. While a model writes, it keeps for every token it has read or written a key and a value vector in
each attention layer: the KV cache. Its size per token is fixed by the architecture:

  KV bytes per token = (layers that hold a per-token cache) x 2 (key and value) x KV heads x head dimension
                       x bytes per element

Hybrid models such as Qwen3.5 (3 Gated DeltaNet layers to 1 full-attention layer) keep a per-token cache only in the
full-attention layers; their linear layers hold a fixed state per sequence instead (about 10 MB for 2B and 26 MB for
4B and 9B in BF16; research/lit/vllm_metrics_qwen35_kv.md), which `state_bytes` reports apart. Verified values:
Qwen3.5-2B 12,288 bytes per token; 4B and 9B 32,768.

Per call: estimated KV bytes = (prompt + output tokens) x bytes per token (the cache at the call's last token).

Per configuration (8.1, addendum 2). With automatic prefix caching (vLLM --enable-prefix-caching, on in the
testbed's serve command) requests that share a prompt prefix share its KV blocks, so k samples or agents of one prompt
store the shared prefix once:
  KV of a configuration = shared prefix tokens (once) + sum over its calls of (unshared prompt + output tokens),
                          x bytes per token.
Without prefix caching every call stores its whole prompt: sum over calls of (prompt + output tokens) x bytes per
token. Both are upper bounds on what is resident at one moment (calls that finish free their blocks) and ignore
block rounding (vLLM allocates whole blocks; compare with vllm:cache_config_info on the first boot).
"""

from __future__ import annotations

import json
from pathlib import Path

BYTES_PER_ELEMENT = {"bfloat16": 2, "float16": 2, "float32": 4, "fp8": 1, "float8_e4m3fn": 1, "auto": 2}
FULL_ATTENTION = "full_attention"


def text_config(config: dict) -> dict:
    """The language model's fields (multimodal checkpoints nest them under text_config)."""
    return {**config, **config.get("text_config", {})}


def cached_layers(config: dict) -> int:
    """The number of layers that hold a per-token KV cache: the full-attention entries of `layer_types`, else every
    `full_attention_interval`-th layer, else all layers (a plain transformer)."""
    c = text_config(config)
    layers = int(c["num_hidden_layers"])
    if c.get("layer_types"):
        return sum(t == FULL_ATTENTION for t in c["layer_types"][:layers])
    if c.get("full_attention_interval"):
        return layers // int(c["full_attention_interval"])
    return layers


def kv_bytes_per_token(config: dict, kv_dtype: str | None = None) -> int:
    """Cached layers x 2 x KV heads x head dimension x bytes per element (the model's dtype unless kv_dtype is
    given, e.g. "fp8" for --kv-cache-dtype fp8)."""
    c = text_config(config)
    heads = int(c.get("num_key_value_heads") or c["num_attention_heads"])
    head_dim = int(c.get("head_dim") or int(c["hidden_size"]) // int(c["num_attention_heads"]))
    dtype = kv_dtype or c.get("dtype") or c.get("torch_dtype") or "bfloat16"
    return cached_layers(config) * 2 * heads * head_dim * BYTES_PER_ELEMENT[str(dtype)]


def state_bytes(config: dict) -> int:
    """Fixed per-sequence state of the linear-attention (Gated DeltaNet) layers, in the model's dtype: per layer a
    temporal state of value heads x value dim x key dim and a convolution state of (key dim x key heads x 2 +
    value dim x value heads) channels x (kernel - 1). 0 for a plain transformer."""
    c = text_config(config)
    layers = int(c["num_hidden_layers"]) - cached_layers(config)
    if layers <= 0 or "linear_num_value_heads" not in c:
        return 0
    k_dim, v_dim = int(c["linear_key_head_dim"]), int(c["linear_value_head_dim"])
    k_heads, v_heads = int(c["linear_num_key_heads"]), int(c["linear_num_value_heads"])
    conv = (k_dim * k_heads * 2 + v_dim * v_heads) * (int(c.get("linear_conv_kernel_dim", 4)) - 1)
    element = BYTES_PER_ELEMENT[str(c.get("dtype") or c.get("torch_dtype") or "bfloat16")]
    return layers * (v_heads * v_dim * k_dim + conv) * element


def load_config(path: str | Path) -> dict:
    """config.json of a checkpoint directory (or the file itself)."""
    path = Path(path)
    return json.loads((path / "config.json" if path.is_dir() else path).read_text())


def call_kv_bytes(prompt_tokens: int, output_tokens: int, per_token: int) -> int:
    """Estimated KV bytes of one call at its last token."""
    return (prompt_tokens + output_tokens) * per_token


def configuration_kv_bytes(prompt_tokens: list[int], output_tokens: list[int], shared_prefix_tokens: int,
                           per_token: int, prefix_caching: bool = True) -> int:
    """KV bytes of a configuration's calls (k samples, or a stage's agents) that share a prompt prefix of
    `shared_prefix_tokens` (module docstring): the prefix once plus each call's unshared prompt and output with
    prefix caching; every call's whole prompt and output without it."""
    if not prefix_caching:
        return sum(p + o for p, o in zip(prompt_tokens, output_tokens)) * per_token
    unshared = sum(max(p - shared_prefix_tokens, 0) + o for p, o in zip(prompt_tokens, output_tokens))
    return (shared_prefix_tokens + unshared) * per_token
