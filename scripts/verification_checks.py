"""Audit 94 post-run checks (a)-(d), form only, read-only (prereg "Audit 94"). For every verification config:
(a) rebuild its requests (panel.requests_for) and look up each cache key (a hit = the run sent this exact prompt);
(b) judges: the read's candidates (anchor_read.judge_shown) equal the rebuilt prompt's CANDIDATES lines;
(c) judges: the read's pick (parse_answer over judge_reply with judge_shown) equals the stored answer;
(d) judges: every parsed raw pick matches a shown candidate (answers_match or whitespace-normalized equality);
plus a census of picks taken without an ANSWER line. Never loads `correct`; prints no gold.

    python scripts/verification_checks.py   (from the repo root; reads the call cache, writes nothing)"""
import json, re, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from autoagentnet.cache import CallCache, make_key
from autoagentnet.evidence import panel as PN, prompts as P
from autoagentnet.providers.registry import ProviderRegistry
from autoagentnet.tasks import answers_match, extract_answer
from analysis import anchor_read as R

ROOT = str(Path(__file__).resolve().parents[1])
CONFIGS = ["e51_verify_anth_bbeh", "e51_verify_anth_math", "e51_verify_open_bbeh", "e51_judge_open_bbeh",
           "e51_verify_open_math", "e51_judge_open_math"]
JUDGE_OF = {src: pools for _, (src, pools, _) in R.JUDGES.items()}
ws = lambda s: " ".join(str(s).split())

def main() -> None:
    cache = CallCache(ROOT + "/state/cache")
    with R.counting_timeouts() as counter:
        calls = R.tier1_calls()
        for name in CONFIGS:
            cfg = PN.PanelConfig.from_yaml(f"{ROOT}/configs/experiments/v4/{name}.yaml")
            reg = ProviderRegistry.from_yaml(cfg.providers)
            reqs = PN.requests_for(cfg, PN.select_items(cfg), {s.ref: s.ref for s in cfg.sources})
            misses, shown_bad, rebuilt = [], [], {}
            for item, source, c, r in reqs:
                key = make_key(r.spec.model_dump(), reg.model_id(r.spec.model), reg.options_of(r.spec.model), r.input.model_dump(), c)
                if cache.get(key) is None:
                    misses.append((item.id, source.label, c))
                if source.prompt == "judge":
                    text = json.dumps(r.input.model_dump())
                    text = json.loads(text)["task"]
                    block = text.split("CANDIDATES:\n", 1)[1] if "CANDIDATES:\n" in text else ""
                    rebuilt[(source.label, item.id)] = re.findall(r"^Candidate \d+: (.*)$", block, re.M)
            out = {"requests": len(reqs), "key_hits": len(reqs) - len(misses), "misses": misses[:10]}
            d = pd.read_csv(f"{ROOT}/results/{name}/calls.csv", dtype={"answer": str})
            jd = d[d["prompt"] == "judge"]
            if not jd.empty:
                kind = jd["task_kind"].iloc[0]
                grader = "math" if kind == "math" else "bbeh"
                src = jd["source"].iloc[0]
                units = [u for a in JUDGE_OF[src] for u in R.ARMS[a]]
                shown = R.judge_shown(calls[kind], units, grader)
                b_bad = [i for (s, i), lines in rebuilt.items() if s == src and [ws(x) for x in shown.get(i, [])] != [ws(x) for x in lines]]
                c_bad, d_bad, labelless = [], [], {"answer_line": 0, "candidate_line": 0, "usual_parse": 0}
                for item, reply, stored in zip(jd["item"], jd["reply"], jd["answer"]):
                    t = reply if isinstance(reply, str) else ""
                    unboxed = "\n".join(P.unbox_label(x) for x in t.splitlines())
                    if extract_answer(unboxed) is not None:
                        labelless["answer_line"] += 1
                    elif P.judge_reply(kind, t, shown.get(item, [])) != "\n".join(x for x in unboxed.splitlines() if not P.CONFIDENCE_LINE.match(x)):
                        labelless["candidate_line"] += 1
                    else:
                        labelless["usual_parse"] += 1
                    pick = P.parse_answer(kind, P.judge_reply(kind, t, shown.get(item, [])))
                    if not ((pick is None and pd.isna(stored)) or (pick is not None and not pd.isna(stored) and ws(pick) == ws(stored))):
                        c_bad.append(item)
                    if pick is not None and not any(answers_match(cand, pick, grader) or ws(cand) == ws(pick) for cand in shown.get(item, [])):
                        form = "names a candidate number" if re.search(r"(?i)candidate", pick) else "boxed" if "\\boxed" in pick else "other"
                        d_bad.append((item, form, len(pick)))
                out.update({"judge_rows": len(jd), "shown_mismatch": b_bad[:10], "n_shown_mismatch": len(b_bad),
                            "pick_differs_from_stored": len(c_bad), "pick_not_a_candidate": d_bad, "pick_source": labelless})
            print(name, out)
        print("math-verify timeouts during the checks:", counter.n)


if __name__ == "__main__":
    main()
