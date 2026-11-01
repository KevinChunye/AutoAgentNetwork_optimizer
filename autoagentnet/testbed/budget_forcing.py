"""Budget forcing: cap a model's thinking at B tokens, then make it answer.

Terms (plain words first):
  thinking       the text a reasoning model writes between its start-of-thinking marker ("<think>") and its
                 end-of-thinking marker ("</think>") before the visible answer.
  budget B       the most thinking tokens a call may use. B = 0 means thinking off: the chat template's
                 non-thinking mode (Qwen: enable_thinking = False), no thinking text at all.
  budget forcing (Muennighoff et al. 2025, "s1", arXiv 2501.19393) generate thinking with max_tokens = B and the end
                 marker as a stop string. If the model stops by itself, the thinking is complete; if it hits the cap,
                 it is cut there. Either way, the end marker is appended and the model continues from
                 prompt + thinking + end marker, which forces it to answer. The answer phase has its own token cap.
  forced         True when the thinking hit the cap B (the model was still thinking when it was cut).

The functions here are pure text manipulation, so they are tested offline and shared by the vLLM provider and the
fake vLLM server used in tests.
"""

from __future__ import annotations

from dataclasses import dataclass

THINK_START = "<think>"
THINK_END = "</think>"


@dataclass(frozen=True)
class Markers:
    """A model family's thinking delimiters (Qwen3 / Qwen3.5 and DeepSeek-R1 style by default)."""

    start: str = THINK_START
    end: str = THINK_END


def strip_start(thinking: str, markers: Markers = Markers()) -> str:
    """The thinking text without a leading start marker (some templates put it in the prompt, some let the model
    write it)."""
    text = thinking.lstrip()
    return text[len(markers.start):].lstrip("\n") if text.startswith(markers.start) else thinking


def answer_prompt(prompt: str, thinking: str, markers: Markers = Markers()) -> str:
    """The prompt of the answer phase: the rendered chat prompt, the (possibly cut) thinking and the end marker.
    If the rendered prompt already ends with the start marker, it is not repeated."""
    body = strip_start(thinking, markers).rstrip()
    opener = "" if prompt.rstrip().endswith(markers.start) else markers.start + "\n"
    return f"{prompt}{opener}{body}\n{markers.end}\n\n"


def split_reply(text: str, markers: Markers = Markers()) -> tuple[str, str]:
    """(thinking, answer) of a reply that contains both, split at the last end marker; ("", text) if it has none."""
    if markers.end not in text:
        return "", text
    head, tail = text.rsplit(markers.end, 1)
    return strip_start(head, markers).strip(), tail.strip()
