"""Isolated, single-threaded tool worker. Invoked by the runner, never by an LLM."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .data import context, load_search
from .store import ArtifactStore
from .types import Graph, Status
from .workflow import calculate, check_payload, check_types


def execute(request: dict) -> dict:
    data = load_search(request["data"])
    graph = Graph.model_validate(request["graph"])
    if graph.context != context(data):
        raise ValueError("worker code/data context differs from graph")
    check_types(graph)
    store = ArtifactStore(request["store"])
    op = graph.operations[request["operation"]]
    start, cpu = time.monotonic(), time.process_time()
    if request.get("verify"):
        check_payload(op, store.load(op, graph, allow_unverified=True), data)
        receipt = store.verify(op, graph)
        return {"receipt": receipt.model_dump(), "cpu_s": time.process_time()-cpu,
                "elapsed_s": time.monotonic()-start, "verified": True}
    parents = [store.load(graph.operations[p], graph) for p in op.parents]
    if op.kind == "predict":
        fit = graph.operations[op.parents[0]]
        parents.append(store.load(graph.operations[fit.parents[0]], graph))
    result = calculate(op, parents, data)
    check_payload(op, result, data)
    receipt = store.put(op, graph, result, time.process_time()-cpu, time.monotonic()-start,
                        Status.UNVERIFIED if request.get("stage_only") else Status.VALID)
    return {"receipt": receipt.model_dump(), "cpu_s": receipt.cpu_s,
            "elapsed_s": receipt.elapsed_s, "verified": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request")
    args = parser.parse_args()
    request = json.loads(Path(args.request).read_text())
    import resource
    limit = int(request.get("cpu_limit_s", 30))
    resource.setrlimit(resource.RLIMIT_CPU, (limit, limit+1))
    print(json.dumps(execute(request)))


if __name__ == "__main__":
    main()
