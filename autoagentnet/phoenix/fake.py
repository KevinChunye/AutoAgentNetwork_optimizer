"""Deterministic offline protocol fixture; its scores are never scientific evidence."""
from __future__ import annotations

import json

from ..providers.base import LLMResponse, Usage
from .types import PipelineSpec, canonical


class FakePhoenixClient:
    provider = "fake"

    def __init__(self, scripted=None):
        self.scripted = list(scripted or [])
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        payload = json.loads(request.blocks[0].text.split("PHOENIX_JSON\n", 1)[1])
        purpose, state = payload["purpose"], payload["state"]
        if self.scripted:
            reply = self.scripted.pop(0)
        elif purpose == "select":
            candidates = state.get("candidates", [])
            reply = canonical({"plan_id": candidates[0]["id"]}) if candidates else '{"stop":true}'
        elif purpose in ("design", "calibrate"):
            reply = canonical({"pipeline": PipelineSpec(classifier="logistic", c=10.0).model_dump()})
        elif purpose == "recover" and state.get("pending_targets"):
            reply = canonical({"action": "VERIFY", "target": state["pending_targets"][0]})
        else:
            specs = [PipelineSpec(classifier="forest", trees=50, depth="5"),
                     PipelineSpec(classifier="knn", neighbors=3),
                     PipelineSpec(classifier="logistic", c=10.0, pca="0.95")]
            proposals = [{"action": "REROUTE", "pipelines": [s.model_dump()]} for s in specs]
            reply = canonical({"proposals": proposals}) if purpose == "propose" else canonical(proposals[0])
        return LLMResponse(text=reply, usage=Usage(input_tokens=10, output_tokens=10),
                           model=request.model, provider="fake", latency_s=0)
