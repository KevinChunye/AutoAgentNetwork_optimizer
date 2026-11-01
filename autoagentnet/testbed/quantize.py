"""Fake-quantized checkpoints (run on the GPU node): quantize the weights, store them again in BF16.

Why fake quantization: every precision then runs on the same vLLM code path (BF16 kernels), so accuracy differences
come from the weights alone, never from kernel numerics; one checkpoint format serves every precision. Speed and
memory of real quantized kernels are measured separately (kernel.py, 300 calls per size).

Terms (plain words first):
  bits b        bits per weight on the quantized layers.
  group         weights that share one scale: a whole output channel ("per channel") or g consecutive input weights
                of one output channel ("group g", here 128).
  RTN           round-to-nearest, symmetric: scale = max|w| / (2^(b-1) - 1) per group, q = clip(round(w / scale),
                -2^(b-1), 2^(b-1) - 1), w' = q x scale. W8 is RTN per channel.
  AWQ, GPTQ     calibration-based methods (llm-compressor): AWQ rescales input channels by activation size before
                rounding; GPTQ rounds one column at a time and corrects the rest for the error. W4 = AWQ group 128
                (GPTQ group 128 if llm-compressor has no AWQ mapping for Qwen3.5's layers; logged as a deviation),
                W3 = GPTQ group 128, stage-2 contrast W4 GPTQ group 128.
  quantized layers  the language model's full-attention and MLP projections. Kept in BF16 (as in Red Hat's
                published Qwen3.5 W4A16 recipe): embeddings, lm_head, the Gated DeltaNet linear-attention blocks
                (`linear_attn`), norms and the vision tower. So "W4" means 4 bits on the quantized layers only, and
                the checkpoint's real weight memory is measured, not size x bits / 8 (prereg, T2).
  calibration   256 sequences of 2048 tokens from HuggingFaceH4/ultrachat_200k (train_sft), shuffled with seed 0;
                recorded with the library versions in <out>/quantization.json.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Callable

import numpy as np

QUANTIZED = re.compile(r"(^|\.)(language_model|model)\.layers\.\d+\.(self_attn\.(q|k|v|o)_proj|mlp\.(gate|up|down)_proj)\.weight$")
IGNORE = ["lm_head", "re:.*embed_tokens.*", "re:.*linear_attn.*", "re:.*visual.*", "re:.*vision.*", "re:.*norm.*"]
CALIBRATION = {"dataset": "HuggingFaceH4/ultrachat_200k", "split": "train_sft", "samples": 256, "seq_len": 2048,
               "seed": 0}
METHODS = {"w8": ("rtn", 8, None), "w4": ("awq", 4, 128), "w3": ("gptq", 3, 128), "w4gptq": ("gptq", 4, 128),
           "w4rtn": ("rtn", 4, 128)}


def rtn(W: np.ndarray, bits: int, group: int | None = None) -> np.ndarray:
    """Symmetric round-to-nearest fake quantization of a 2-D weight (out x in), per channel or per group of `group`
    input weights; returns the dequantized weights in the input's dtype."""
    out_dim, in_dim = W.shape
    g = in_dim if group is None else group
    if in_dim % g:
        raise ValueError(f"input dimension {in_dim} is not a multiple of the group size {g}")
    x = W.astype(np.float32).reshape(out_dim, in_dim // g, g)
    qmax = 2 ** (bits - 1) - 1
    scale = np.abs(x).max(axis=2, keepdims=True) / qmax
    scale = np.where(scale == 0, 1.0, scale)
    q = np.clip(np.round(x / scale), -qmax - 1, qmax)
    return (q * scale).reshape(out_dim, in_dim).astype(W.dtype)


def is_quantized(name: str, shape) -> bool:
    return len(shape) == 2 and bool(QUANTIZED.search(name))


def fake_quant_tensors(tensors: dict[str, np.ndarray], bits: int, group: int | None) -> tuple[dict, list[str]]:
    """RTN on the quantized layers of a {name: array} dict; (new dict, names changed)."""
    out, changed = {}, []
    for name, w in tensors.items():
        if is_quantized(name, w.shape):
            out[name] = rtn(w, bits, group)
            changed.append(name)
        else:
            out[name] = w
    return out, changed


def export_rtn(src: Path, dst: Path, bits: int, group: int | None,
               load: Callable | None = None, save: Callable | None = None) -> dict:
    """RTN fake quantization file by file over a checkpoint's *.safetensors (no model class needed); every other
    file (config, tokenizer, chat template) is copied unchanged. load/save default to safetensors' torch API (BF16)."""
    if load is None or save is None:
        from safetensors.torch import load_file, save_file
        import torch

        def load(path):
            return {k: v.float().numpy() for k, v in load_file(str(path)).items()}

        def save(arrays, path):
            save_file({k: torch.from_numpy(np.ascontiguousarray(v)).to(torch.bfloat16) for k, v in arrays.items()},
                      str(path), metadata={"format": "pt"})
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    changed: list[str] = []
    for path in sorted(src.iterdir()):
        if path.suffix == ".safetensors":
            arrays, names = fake_quant_tensors(load(path), bits, group)
            save(arrays, dst / path.name)
            changed += names
        elif path.is_file():
            shutil.copy2(path, dst / path.name)
    meta = {"method": "rtn", "bits": bits, "group": group, "quantized_tensors": len(changed),
            "kept_bf16": "everything else (embeddings, lm_head, linear_attn, norms, vision)"}
    (dst / "quantization.json").write_text(json.dumps(meta, indent=2))
    return meta


def export_llmcompressor(src: Path, dst: Path, method: str, bits: int, group: int, real_dst: Path | None = None) -> dict:
    """AWQ or GPTQ with llm-compressor (GPU node only), then fake-quantized BF16 weights written over a copy of the
    source checkpoint. With real_dst, the compressed checkpoint (for real kernels) is saved there too."""
    import torch
    import transformers
    from compressed_tensors.quantization.lifecycle.forward import fake_quantize
    from datasets import load_dataset
    from llmcompressor import oneshot
    from llmcompressor.modifiers.awq import AWQModifier
    from llmcompressor.modifiers.quantization import GPTQModifier
    from safetensors.torch import load_file, save_file

    config = transformers.AutoConfig.from_pretrained(src)
    model_cls = getattr(transformers, config.architectures[0])
    model = model_cls.from_pretrained(src, torch_dtype=torch.bfloat16, device_map="auto")
    tok = transformers.AutoTokenizer.from_pretrained(src)
    ds = load_dataset(CALIBRATION["dataset"], split=CALIBRATION["split"]).shuffle(seed=CALIBRATION["seed"])
    ds = ds.select(range(CALIBRATION["samples"])).map(
        lambda r: {"text": tok.apply_chat_template(r["messages"], tokenize=False)})
    scheme = {"group_0": {"targets": ["Linear"], "weights": {"num_bits": bits, "type": "int", "symmetric": True,
                                                              "strategy": "group", "group_size": group},
                          "input_activations": None, "output_activations": None}}
    recipe = (AWQModifier(config_groups=scheme, ignore=IGNORE) if method == "awq"
              else GPTQModifier(config_groups=scheme, ignore=IGNORE))
    oneshot(model=model, dataset=ds, recipe=recipe, max_seq_length=CALIBRATION["seq_len"],
            num_calibration_samples=CALIBRATION["samples"])
    # Every parameter is taken from the model after calibration, not only the quantized weights: AWQ folds its
    # channel scales into the preceding norms, so those change too.
    state = {k: v.detach().to(torch.bfloat16).cpu() for k, v in model.state_dict().items()}
    fake = 0
    for name, module in model.named_modules():
        scheme_ = getattr(module, "quantization_scheme", None)
        if scheme_ is not None and getattr(module, "weight_scale", None) is not None:
            zp = getattr(module, "weight_zero_point", None)
            state[f"{name}.weight"] = fake_quantize(module.weight.data, module.weight_scale.data,
                                                    None if zp is None else zp.data, scheme_.weights).to(torch.bfloat16).cpu()
            fake += 1
    if real_dst is not None:
        model.save_pretrained(real_dst, save_compressed=True)
        tok.save_pretrained(real_dst)
    src, dst = Path(src), Path(dst)
    dst.mkdir(parents=True, exist_ok=True)
    matched, missing = 0, []
    for path in sorted(src.iterdir()):
        if path.suffix == ".safetensors":
            tensors = load_file(str(path))
            for key in tensors:
                if key in state:
                    tensors[key] = state[key]
                    matched += 1
                elif "visual" not in key and "vision" not in key:
                    missing.append(key)
            save_file(tensors, str(dst / path.name), metadata={"format": "pt"})
        elif path.is_file():
            shutil.copy2(path, dst / path.name)
    if missing:
        raise RuntimeError(f"{len(missing)} language-model tensors of the checkpoint have no counterpart in the "
                           f"calibrated model (e.g. {missing[:3]}): map the parameter names before using this export")
    written = fake
    import llmcompressor
    meta = {"method": method, "bits": bits, "group": group, "ignore": IGNORE, "calibration": CALIBRATION,
            "quantized_tensors": written, "llmcompressor": llmcompressor.__version__,
            "transformers": transformers.__version__, "torch": torch.__version__}
    (dst / "quantization.json").write_text(json.dumps(meta, indent=2))
    return meta


def export_real_rtn(src: Path, real_dst: Path, bits: int, group: int | None) -> None:
    """The compressed RTN checkpoint for real kernels (W8A16 per channel): llm-compressor with no calibration data."""
    import torch
    import transformers
    from llmcompressor import oneshot
    from llmcompressor.modifiers.quantization import QuantizationModifier

    config = transformers.AutoConfig.from_pretrained(src)
    model = getattr(transformers, config.architectures[0]).from_pretrained(src, torch_dtype=torch.bfloat16,
                                                                           device_map="auto")
    strategy = {"strategy": "channel"} if group is None else {"strategy": "group", "group_size": group}
    scheme = {"group_0": {"targets": ["Linear"], "weights": {"num_bits": bits, "type": "int", "symmetric": True,
                                                              **strategy}}}
    oneshot(model=model, recipe=QuantizationModifier(config_groups=scheme, ignore=IGNORE))
    model.save_pretrained(real_dst, save_compressed=True)
    transformers.AutoTokenizer.from_pretrained(src).save_pretrained(real_dst)


def export(src: Path, dst: Path, precision: str, real_dst: Path | None = None) -> dict:
    method, bits, group = METHODS[precision]
    if method == "rtn":
        meta = export_rtn(src, dst, bits, group)
        if real_dst is not None:
            export_real_rtn(src, real_dst, bits, group)
        return meta
    return export_llmcompressor(src, dst, method, bits, group, real_dst)


def compare(src_tensors: dict[str, np.ndarray], dst_tensors: dict[str, np.ndarray]) -> dict:
    """Which tensors changed and by how much (relative Frobenius error): the post-export sanity check."""
    changed, rel = [], []
    for name, w in src_tensors.items():
        d = dst_tensors[name]
        if not np.array_equal(w, d):
            changed.append(name)
            rel.append(float(np.linalg.norm(w.astype(np.float32) - d.astype(np.float32)) / max(np.linalg.norm(w), 1e-12)))
    return {"changed": len(changed), "unexpected": [n for n in changed if not is_quantized(n, src_tensors[n].shape)],
            "median_relative_error": float(np.median(rel)) if rel else 0.0}
