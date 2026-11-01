"""The anchor's block-2 read (analysis/anchor_read.py: judges, self-checks, AH4), block 1's exploratory reads and the
read.md writer, on fake results built from real sealed items with their golds. Offline."""

import pytest
import json

import numpy as np
import pandas as pd

from analysis import anchor_read as R

BBEH = R.BBEH_TASKS.parents[2] / "research/v4/anchor/sealed/bbeh_anchor_order.txt"
N_BBEH, N_MATH = 24, 8


def golds():
    out = {}
    for f in (R.BBEH_TASKS, R.MATH_TASKS):
        for line in f.read_text().splitlines():
            if line:
                t = json.loads(line)
                out[t["id"]] = t["answer"]
    return out


def row(item, kind, source, call, right, gold, prompt="base"):
    answer = (gold if right else "987654.321") if kind == "math" else (gold if right else "qqq zzz")
    reply = f"\\boxed{{{answer}}}" if kind == "math" else f"x\nANSWER: {answer}"
    return {"item": item, "task_kind": kind, "source": source, "prompt": prompt, "call": call, "reply": reply,
            "stop_reason": "end_turn", "answer": answer, "parsed": True, "correct": float(right), "prob": None,
            "cost_usd": 0.001, "seconds": 1.0, "truncated": False,
            "meta_task": item.split("-")[1].replace("_", " ") if kind == "bbeh" else None}


def fake_results(tmp_path):
    """Tier-1 runs where arm skill rises with its name's position and item difficulty with the item's position; the Sol
    judge picks right whenever any candidate is right; the self-checks give the true verdict."""
    g = golds()
    items = {"bbeh": BBEH.read_text().split()[:N_BBEH],
             "math": [i for i in g if i.startswith("arxivmath-0826")][:N_MATH]}
    rng = np.random.default_rng(0)
    arms = {a: u for a, u in R.ARMS.items()}
    skill = {a: k / len(arms) for k, a in enumerate(arms)}
    gen = {"bbeh": [], "math": []}
    for kind, ids in items.items():
        for r, item in enumerate(ids):
            hard = r / len(ids)
            for arm, units in arms.items():
                if arm == "haiku_high" and kind == "math":
                    continue  # its math cells are dropped (audit 74)
                for u in units:
                    source, _, call = u.rpartition(":")
                    right = rng.random() < 0.15 + 0.7 * skill[arm] * (1 - hard) + 0.1
                    if kind == "bbeh" and r == 0 and arm in ("haiku_off", "luna_low"):
                        gen[kind].append({**row(item, kind, source, int(call), False, g[item]), "reply": "",
                                          "answer": None, "parsed": False})  # item 0: the Sol judge's pools are unparsed
                    else:
                        gen[kind].append(row(item, kind, source, int(call), right, g[item]))
                if arm in ("sonnet_off", "sonnet_low") and r < (5 if kind == "bbeh" else 2):  # second calls
                    gen[kind].append(row(item, kind, units[0].rpartition(":")[0], 1, rng.random() < 0.5, g[item]))
    # tier1_calls takes every source of e51_haiku_bbeh and e51_sonnet_math_t30; Sol's math rows go where the real runs
    # put them (audit 87): Sol low in e51_sol_math_low, Sol medium in the closed e51_sol_math, which the read skips
    run_of = {"bbeh": lambda src: "e51_haiku_bbeh",
              "math": lambda src: {"sol61_low:base": "e51_sol_math_low", "sol61_med:base": "e51_sol_math"}.get(src, "e51_sonnet_math_t30")}
    for kind, rows in gen.items():
        frame = pd.DataFrame(rows)
        for run, part in frame.groupby(frame["source"].map(run_of[kind])):
            d = tmp_path / run
            d.mkdir(parents=True, exist_ok=True)
            part.to_csv(d / "calls.csv", index=False)
    from autoagentnet.evidence.panel import shown_candidates

    graded = {k: R.regrade(pd.DataFrame(v)) for k, v in gen.items()}
    ver = {"bbeh": [], "math": []}
    for kind, calls in graded.items():
        for item, c in calls.groupby("item"):
            pools = c[c["source"].isin(["haiku_nothink:base", "luna_low_ev:base"]) & (c["call"] < 3)]
            stored = pd.DataFrame(gen[kind])
            stored = stored[(stored["item"] == item) & stored["source"].isin(["haiku_nothink:base", "luna_low_ev:base"])]
            stored = stored[stored["call"] < 3].sort_values(["source", "call"], kind="stable")
            shown = shown_candidates([a if isinstance(a, str) else None for a in stored["answer"]], kind, item)
            if shown and not (kind == "bbeh" and item == items["bbeh"][1]):
                right = [k for k, a in enumerate(shown, 1) if a == g[item]]
                pick = f"x\nANSWER: Candidate {right[0] if right else 1}\nCONFIDENCE: 0.7"  # the right one if any
                ver[kind].append({**row(item, kind, "sol61_low:judge", 0, bool(pools["correct"].max()), g[item],
                                        "judge"), "reply": pick, "prob": 0.7})  # BBEH item 1: none, despite candidates
            for source, checked in (("haiku_low:self_check", "haiku_low:base"), ("sol61_low:self_check", "sol61_low:base")):
                truth = bool(c[(c["source"] == checked) & (c["call"] == 0)]["correct"].iloc[0])
                ver[kind].append({"item": item, "task_kind": kind, "source": source, "prompt": "self_check", "call": 0,
                                  "answer": "correct" if truth else "incorrect", "parsed": True,
                                  "prob": 0.9 if truth else 0.2, "correct": 1.0, "cost_usd": 0.001, "seconds": 1.0,
                                  "reply": f"VERDICT: {'correct' if truth else 'incorrect'}\nCONFIDENCE: {0.9 if truth else 0.2}",
                                  "stop_reason": "end_turn"})  # the read parses the verdict from the reply (audit 93)
    for kind, rows in ver.items():
        d = tmp_path / f"e51_judge_open_{kind}"
        d.mkdir(parents=True)
        pd.DataFrame(rows).to_csv(d / "calls.csv", index=False)
    d = tmp_path / "e51_tier2_anth_bbeh"  # tier 2: Opus on the first 6 BBEH items
    d.mkdir(parents=True)
    pd.DataFrame([row(i, "bbeh", "opus_nothink:base", 0, True, g[i]) for i in items["bbeh"][:6]]).to_csv(
        d / "calls.csv", index=False)
    return items


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_block2_reads_judges_checks_and_ah4(tmp_path):
    items = fake_results(tmp_path)
    out = R.read_block2(tmp_path)
    j = out["judges"].set_index(["judge", "items"])
    sol = j.loc[("sol_low_judge", "all")]
    assert sol["n"] == N_BBEH + N_MATH - 1  # the item without a judge row is dropped, and counted
    assert out["judge_missing"]["sol_low_judge:bbeh"] == {"no_judge_row": [items["bbeh"][1]], "left_out": [items["bbeh"][1]]}
    assert abs(sol["judge_accuracy"] - sol["coverage"]) < 1e-12 and abs(sol["eta"] - 1.0) < 1e-12  # a perfect selector
    assert ("haiku_high_judge", "bbeh") not in j.index and "haiku_high_judge:bbeh" not in out["judge_missing"]  # not run
    assert out["judge_missing"]["haiku_low_check:bbeh"] == {"left_out": [], "no_judge_row": []}  # every call 0 checked
    c = out["self_checks"].set_index(["check", "items"])
    for name in ("haiku_low_check", "sol_low_check"):
        assert c.loc[(name, "all"), "verdict_accuracy"] == 1.0 and c.loc[(name, "all"), "n"] == N_BBEH + N_MATH
        assert c.loc[(name, "all"), "auroc"] in (1.0,) or np.isnan(c.loc[(name, "all"), "auroc"])
    assert out["AH4"] is not None and out["AH4"]["n"] == N_BBEH + N_MATH - 1
    assert items["bbeh"][0] in set(R.with_judge(*_sol_rows(tmp_path))[0]["item"])


def _sol_rows(tmp_path):
    gen, ver = R.tier1_calls(tmp_path), R.verify_calls(tmp_path)
    return gen["bbeh"], ver["bbeh"], "sol61_low:judge", R.ARMS["haiku_off"] + R.ARMS["luna_low"]


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_with_judge_fills_items_without_candidates(tmp_path):
    items = fake_results(tmp_path)
    rows, missing = R.with_judge(*_sol_rows(tmp_path))
    filled = rows[(rows["item"] == items["bbeh"][0]) & (rows["source"] == "sol61_low:judge")]
    assert len(filled) == 1 and filled["correct"].iloc[0] == 0.0 and not filled["parsed"].iloc[0]
    assert missing == [items["bbeh"][1]]


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_exploratory_reads_and_markdown(tmp_path):
    items = fake_results(tmp_path)
    extra = R.explore_block1(tmp_path)
    dw = extra["depth_width"]
    assert set(dw["items"]) == {"bbeh", "math", "all"}
    assert "haiku_high" in set(dw[dw["items"] == "bbeh"]["arm"]) and "haiku_high" not in set(dw[dw["items"] == "all"]["arm"])
    one = dw[(dw["arm"] == "sol_low") & (dw["k"] == 1)]
    assert ((one["lo"] <= one["accuracy"]) & (one["accuracy"] <= one["hi"])).all()
    tr = extra["truncation"]
    assert tr["calls"].sum() == sum(len(pd.read_csv(tmp_path / r / "calls.csv"))
                                    for r in ("e51_haiku_bbeh", "e51_sonnet_math_t30", "e51_sol_math_low"))
    lf = extra["label_free"]
    assert set(lf["method"]) == {"plain", "pooled"} and lf["estimate"].between(0, 1).all()
    assert set(extra["tail"]["k"]) == {1, 2, 3, 4, 5} and len(extra["atlas"]) > 0
    sc = extra["second_calls"].set_index(["items", "arm"])
    assert sc.loc[("bbeh", "sonnet_off"), "n"] == 5 and sc.loc[("all", "sonnet_low"), "n"] == 7
    r3 = R.read_block3(tmp_path)
    t3 = r3["arms"]
    assert set(t3["tier2"]) == {"opus"} and (t3["n"] == 6).all() and "opus" in set(t3["arm"])
    assert t3.loc[t3["arm"] == "opus", "accuracy"].iloc[0] == 1.0
    # audit 80: a tier-2 `_t30` fallback holding at least the run's items replaces it in block 3
    g = golds()
    d = tmp_path / "e51_tier2_anth_bbeh_t30"
    d.mkdir()
    pd.DataFrame([row(i, "bbeh", "opus_nothink:base", 0, False, g[i]) for i in items["bbeh"][:8]]).to_csv(
        d / "calls.csv", index=False)
    t3b = R.read_block3(tmp_path)["arms"]
    assert (t3b["n"] == 8).all() and t3b.loc[t3b["arm"] == "opus", "accuracy"].iloc[0] == 0.0
    assert set(R.BLOCKS) == {"block1", "block2", "block3"}
    ps = extra["parse_stages"]
    assert set(ps.columns) >= {"source", "task_kind", "parsed_run", "parsed_read"} and len(ps) > 0
    a2 = extra["ah2_readable"]
    assert 0 < a2["n"] <= a2["n_all"] and set(a2) >= {"haiku", "luna", "p"}
    assert extra["timeouts"] == {"rows": [], "changed": [], "family": None}  # fake math rows grade without timeouts
    text = R.block1_md(R.read_block1(tmp_path), extra) + R.block2_md(R.read_block2(tmp_path)) + R.block3_md(r3)
    assert "## Block 1:" in text and "## Block 2:" in text and "## Block 3:" in text and "| AH2 |" in text
    assert "No math row hit a timeout." in text
    whole = R.block1(tmp_path) + R.block2(tmp_path)  # audit 92: graded once, every timeout of the block counted
    assert "timeouts during the whole block-1 read (all grading, vote classes included): 0." in whole
    assert "timeouts during the whole block-2 read: 0." in whole


def test_counting_timeouts_counts_inside_the_block_only():
    import logging

    log = logging.getLogger("math_verify.grader")
    with R.counting_timeouts() as counter:
        log.warning("Timeout during comparison")
        log.warning("something else")
    log.warning("Timeout during comparison")  # after the block: not counted
    assert counter.n == 1 and not logging.getLogger("math_verify").handlers


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_timeout_sensitivity_recomputes_the_family_with_timeout_rows_counted_right(tmp_path):
    """Audit 91: rows whose read hit a math-verify timeout are listed, and AH2 and AH3 are recomputed with them counted
    correct (here: every wrong math row of the fake panel is marked as a timeout)."""
    fake_results(tmp_path)
    calls = R.tier1_calls(tmp_path)
    math = calls["math"]
    marked = {**calls, "math": math.assign(timeouts=(math["correct"] == 0.0).astype(int))}
    out = R.timeout_sensitivity(tmp_path, marked)
    assert len(out["rows"]) == int((math["correct"] == 0.0).sum()) > 0
    assert set(out["family"]["test"]) >= {"AH2", "AH3"} and "passes_timeouts_right" in out["family"]
    assert set(out["changed"]) <= set(R.CONFIRMATORY)


def test_panel_reads_the_fallback_run_when_it_exists(tmp_path, monkeypatch):
    """Audit 77: a judge or self-check reads `<run>_t30/calls.csv` when it exists, as the anchor's read does."""
    from autoagentnet.evidence.panel import PanelConfig, panel_files

    monkeypatch.chdir(tmp_path)
    (tmp_path / "results/e51_luna_bbeh").mkdir(parents=True)
    (tmp_path / "results/e51_luna_bbeh/calls.csv").write_text("item\n")
    cfg = PanelConfig.model_validate({"kind": "panel", "name": "j", "task_kind": "bbeh", "tasks": "t", "items": "i",
                                      "sources": [{"ref": "x", "prompt": "judge"}],
                                      "panel_results": ["results/e51_luna_bbeh/calls.csv", "results/e51_haiku_bbeh/calls.csv"]})
    assert panel_files(cfg) == cfg.panel_results
    (tmp_path / "results/e51_luna_bbeh_t30").mkdir()
    (tmp_path / "results/e51_luna_bbeh_t30/calls.csv").write_text("item\n")
    assert panel_files(cfg) == ["results/e51_luna_bbeh_t30/calls.csv", "results/e51_haiku_bbeh/calls.csv"]
    assert R.fallback("e51_luna_bbeh", tmp_path / "results") == "e51_luna_bbeh_t30"  # the read agrees


def test_a_shorter_fallback_is_not_read_and_a_paid_run_refuses_it(tmp_path, monkeypatch):
    """Audit 78: a `_t30` file with fewer items than its run is not read (by the run or the read), and a paid run that
    would read panel files refuses while one is uncommitted or such a fallback exists."""
    from autoagentnet.evidence.panel import PanelConfig, panel_file_problems, panel_files

    monkeypatch.chdir(tmp_path)  # not a git repository: every file counts as uncommitted
    for run, items in (("e51_luna_bbeh", "a\nb\nc\n"), ("e51_luna_bbeh_t30", "a\nb\n")):
        (tmp_path / "results" / run).mkdir(parents=True)
        (tmp_path / "results" / run / "calls.csv").write_text("item\n" + items)
    cfg = PanelConfig.model_validate({"kind": "panel", "name": "j", "task_kind": "bbeh", "tasks": "t", "items": "i",
                                      "sources": [{"ref": "x", "prompt": "judge"}],
                                      "panel_results": ["results/e51_luna_bbeh/calls.csv"]})
    assert panel_files(cfg) == ["results/e51_luna_bbeh/calls.csv"]
    assert R.fallback("e51_luna_bbeh", tmp_path / "results") == "e51_luna_bbeh"
    problems = panel_file_problems(cfg)
    assert any("must be committed" in p for p in problems) and any("fewer items" in p for p in problems)
    (tmp_path / "results/e51_luna_bbeh_t30/calls.csv").write_text("item\na\nb\nc\nd\n")
    assert panel_files(cfg) == ["results/e51_luna_bbeh_t30/calls.csv"] and not any("fewer" in p for p in panel_file_problems(cfg))



@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_sol_medium_math_cells_are_dropped_and_sol_low_math_comes_from_the_variant(tmp_path):
    """Audit 87: the read takes Sol low's math cells from e51_sol_math_low and none of Sol medium's; complete arms keep
    Sol low and leave Sol medium out of math, while BBEH keeps it."""
    fake_results(tmp_path)
    calls = R.tier1_calls(tmp_path)
    math = calls["math"]
    assert not (math["source"] == "sol61_med:base").any() and (math["source"] == "sol61_low:base").any()
    assert not math.duplicated(["item", "source", "call"]).any()
    full = R.complete_arms(calls)
    assert "sol_low" in full and "sol_med" not in full
    assert "sol_med" in R.complete_arms({"bbeh": calls["bbeh"]})


def test_self_check_rows_are_parsed_again_from_their_replies(tmp_path):
    """Audit 93: the read parses every self-check's verdict and confidence from its stored reply (a boxed confidence
    the run-time parser missed is read), a refused row has no verdict, and a truncated row keeps no verdict."""
    d = tmp_path / "e51_verify_open_math"
    d.mkdir()
    replies = ["work\nVERDICT: correct\nCONFIDENCE: \\(\\boxed{0.99}\\)", "work\nVERDICT: incorrect\n\\boxed{\\text{CONFIDENCE: }0.4}",
               "VERDICT: correct\nCONFIDENCE: 0.8", "VERDICT: correct\nCONFIDENCE: 0.8"]
    pd.DataFrame({"item": ["a", "b", "c", "d"], "task_kind": "math", "source": "sol61_low:self_check",
                  "prompt": "self_check", "call": 0, "reply": replies, "answer": ["correct", "incorrect", "correct", "correct"],
                  "prob": [None, None, 0.8, 0.8], "parsed": [False, False, True, True],
                  "stop_reason": ["stop", "stop", "content_filter", "stop"], "truncated": [False, False, False, True]}
                 ).to_csv(d / "calls.csv", index=False)
    c = R.verify_calls(tmp_path, {"math": ["e51_verify_open_math"]})["math"].set_index("item")
    assert c.loc["a", "prob"] == 0.99 and c.loc["b", "prob"] == 0.4 and c.loc["b", "answer"] == "incorrect"
    assert pd.isna(c.loc["c", "answer"]) and pd.isna(c.loc["c", "prob"])  # refused
    assert pd.isna(c.loc["d", "answer"])  # truncated: no verdict


def test_bare_bounds_are_counted_per_arm():
    """Prereg "Audit 89": the read counts, per arm, the math answers that only bound the value (form only); a value with
    a condition, an abstention, an equation and a BBEH answer are not bounds. Made-up answers."""
    assert R.bare_bound("r\\ge 8") and R.bare_bound("v_*\\geq 3") and R.bare_bound("0 < x")
    for a in ("7", "7\\quad(n\\ge 2)", "\\text{unknown; at least } 3", "x = 3", "\\{u: u\\le 1\\}", None):
        assert not R.bare_bound(a), a
    rows = pd.DataFrame({"item": ["i1", "i2", "i3", "i4"], "source": ["a:base", "a:base", "b:base", "b:base"],
                         "task_kind": ["math", "math", "math", "bbeh"], "answer": ["r\\ge 8", "5", "r\\ge 7", "x > y"],
                         "parsed": [True, True, False, True], "run_parsed": [True, True, False, True]})
    ps = R.parse_stages({"math": rows[rows.task_kind == "math"], "bbeh": rows[rows.task_kind == "bbeh"]}).set_index("source")
    assert ps.loc["a:base", "bounds"] == 1 and ps.loc["a:base", "bounds_read"] == 1
    m = ps[ps["task_kind"] == "math"]
    assert m.loc["b:base", "bounds"] == 1 and m.loc["b:base", "bounds_read"] == 0
    assert ps[ps["task_kind"] == "bbeh"]["bounds"].sum() == 0  # only math answers are bounds


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_block3_shows_truncations_and_tokens_and_gives_tier2_math_as_facts_only(tmp_path):
    """D1 (session E6), audit 95 finding 5: block 3 lists each tier-2 source's truncations and tokens, gives tier-2 math
    without accuracy, and says Astra was not run. Fake tier-2 rows: 6 BBEH items, 4 math items of which 1 truncated."""
    items = fake_results(tmp_path)
    g = golds()
    for kind, n in (("bbeh", 6), ("math", 4)):
        rows = [row(i, kind, "sonnet_high:base", 0, True, g[i]) for i in items[kind][:n]]
        for r in rows:
            r["output_tokens"], r["visible_output_tokens"] = 1000, 100
        if kind == "math":
            rows[0]["truncated"], rows[0]["stop_reason"] = True, "max_tokens"
        d = tmp_path / f"e51_tier2_anth_{kind}"
        d.mkdir(exist_ok=True)
        old = pd.read_csv(d / "calls.csv") if (d / "calls.csv").exists() else pd.DataFrame()
        pd.concat([old, pd.DataFrame(rows)], ignore_index=True).to_csv(d / "calls.csv", index=False)
    r3 = R.read_block3(tmp_path)
    f = r3["facts"].set_index(["items_kind", "source"])
    assert f.loc[("math", "sonnet_high:base"), "truncated"] == 1 and f.loc[("math", "sonnet_high:base"), "calls"] == 4
    assert f.loc[("bbeh", "sonnet_high:base"), "output_tokens_mean"] == 1000
    a = r3["arms"]
    assert a[a["items"] == "math"]["accuracy"].isna().all() and (a[a["items"] == "math"]["note"] == R.MATH_FACTS_ONLY).all()
    assert a[(a["items"] == "bbeh") & (a["tier2"] == "sonnet_high")]["accuracy"].notna().all()
    text = R.block3_md(r3)
    assert "astra_low: skipped by Kevin's decision D1" in text and "Cost and token facts" in text
