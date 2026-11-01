"""The Phase 3C cascade selection rule and lockbox read (analysis/pruning_cascade.py) on simulated panels, and the
guard that keeps the lockbox unread until selected.json is committed; offline."""

import json

import numpy as np
import pandas as pd
import pytest

import analysis.pruning_cascade as R
from analysis.pruning_cascade_power import BASE, simulate


@pytest.fixture(scope="module")
def selection():
    rng = np.random.default_rng(3)
    search = simulate(300, BASE, rng)
    return R.select({"base": search, "persona": search.subset(np.arange(200))}), rng


def test_rule_covers_every_first_round_and_escalation(selection):
    sel, _ = selection
    table = pd.DataFrame(sel["table"])
    assert len(table) == len(R.FIRST_ROUNDS) * len(R.ESCALATIONS)
    persona = table[table["first round"].str.contains("personas")]
    assert (persona["items"] == 200).all() and (table.loc[~table.index.isin(persona.index), "items"] == 300).all()
    assert table[["acceptance at 0.05", "acceptance at 0.1", "acceptance at 0.2"]].notna().all().all()


def test_selected_policy_is_the_cheapest_that_qualifies(selection):
    sel, _ = selection
    table = pd.DataFrame(sel["table"])
    ok = table[table["accuracy"] >= table["sonnet accuracy"] - R.MARGIN - 1e-12]
    best = ok.sort_values("dollars").iloc[0]
    assert sel["policy"]["first round"] == best["first round"]
    assert sel["policy"]["escalation"] == R.ESCALATIONS[best["escalation"]]
    assert sel["policy"]["t"] == sel["policy"]["t by alpha"][str(R.ALPHA)]
    assert sel["c2"]["mixed"]["first round"] in R.MIXED and sel["c2"]["haiku x5"]["first round"] == "haiku x5"
    assert sel["void"] == []


def test_nothing_qualifies_makes_c1_and_c2_void():
    """Cheap calls always wrong, Sonnet and Sol always right: every cascade would escalate every item, which is the
    escalation model plus overhead, so nothing qualifies and C1 and C2 are void (never a free pass)."""
    from analysis.pruning_cascade_power import UNITS
    from autoagentnet.pruning.replay import Panel

    n = 300
    A = np.ones((n, len(UNITS)), dtype=int)
    A[:, [k for k, u in enumerate(UNITS) if u.startswith(("sonnet", "sol"))]] = 0
    panel = Panel.from_arrays(A, (A == 0).astype(float), np.full(A.shape, 0.001),
                              sources=[u.rsplit(":", 1)[0] for u in UNITS], calls=[int(u.rsplit(":", 1)[1]) for u in UNITS],
                              items=[f"bbeh-t{i % 4}-{i:04d}" for i in range(n)])
    sel = R.select({"base": panel, "persona": panel.subset(np.arange(200))})
    assert sel["policy"] is None and sel["void"] == ["C1", "C2"]
    assert not any(row["qualifies"] for row in sel["table"])


def test_lockbox_tests_apply_the_frozen_policy_without_refitting(selection):
    sel, rng = selection
    lock = simulate(200, BASE, rng)
    out = R.lockbox_tests(lock, sel, status={"C1": "conf", "C2": "conf"}).set_index("test")
    assert {"C1", "C1b", "C2", "C3", "comparator: Sol alone", "comparator: Sonnet alone"} <= set(out.index)
    assert out.loc["C1b", "status"] == "expl"
    assert out.loc["comparator: policy", "dollars"] == pytest.approx(R.apply_policy(lock, sel["policy"])["dollars"].mean())
    policy = R.apply_policy(lock, sel["policy"])
    g = R.C.unit_positions(lock, [R.SONNET])[0]
    assert out.loc["C1", "difference"] == pytest.approx((policy["correct"].to_numpy() - lock.correct_matrix()[:, g]).mean())
    assert out.loc["C3", "difference"] == pytest.approx(policy["accepted_wrong"].mean())
    assert out.loc["C3", "hi"] >= out.loc["C3", "difference"]
    assert out.loc[["C1", "C2"], "passes"].notna().all()
    o = R.C.unit_positions(lock, [R.ESCALATIONS["sol"]])[0]  # C1s: the policy against Sol alone (deviation 28)
    assert out.loc["C1s", "difference"] == pytest.approx((policy["correct"].to_numpy() - lock.correct_matrix()[:, o]).mean())
    assert out.loc["C1s", "dollar ratio"] == pytest.approx(policy["dollars"].mean() / lock.cost[:, o].mean())
    assert out.loc["C1s", "status"] == "expl" and pd.isna(out.loc["C1s", "passes"])


def test_frontier_against_sol(selection):
    """Every base-prompt cascade, cross-fitted at three alphas and in-sample at every grid threshold; "near Sol" is
    the stated criterion, and the loosest in-sample threshold accepts at least as much as the strictest."""
    _, rng = selection
    panel = simulate(200, BASE, rng)
    table = R.frontier_vs_sol(panel)
    per = len(R.ESCALATIONS) * (len(R.C.ALPHAS) + len(R.C.THRESHOLDS))
    assert len(table) == len(R.BASE_ROUNDS) * per and not table["first round"].str.contains("personas").any()
    ins = table[table["kind"] == "in-sample"]
    loose, strict = ins[ins["setting"] == "t 0.05"], ins[ins["setting"] == "t 1.00"]
    assert (loose["acceptance"].to_numpy() >= strict["acceptance"].to_numpy()).all()
    o = R.C.unit_positions(panel, [R.ESCALATIONS["sol"]])[0]
    near = (table["accuracy"] >= panel.correct_matrix()[:, o].mean() - R.SOL_GAP - 1e-9) & (
        table["dollars"] <= R.SOL_RATIO * panel.cost[:, o].mean())
    assert (table["near_sol"] == near).all()


def test_clopper_pearson_upper_bound():
    assert R.upper_bound(0, 200) == pytest.approx(1 - 0.05 ** (1 / 200))
    assert R.upper_bound(200, 200) == 1.0


def test_lockbox_read_refuses_without_a_committed_selection(tmp_path, monkeypatch):
    fake, early = tmp_path / "selected.json", tmp_path / "selected_forecast.json"
    monkeypatch.setattr(R, "OUT", fake)
    monkeypatch.setattr(R, "FORECAST_OUT", early)
    monkeypatch.setattr(R, "LOCKBOX_OUT", {k: tmp_path / f"lockbox_{k}.md" for k in ("bbeh", "forecast")})
    monkeypatch.setattr(R, "read_runs", lambda runs: pytest.fail("read the lockbox calls before the selection"))
    for kind in ("bbeh", "forecast"):
        with pytest.raises(SystemExit, match="must exist and be committed"):
            R.lockbox_main(kind)
    fake.write_text("{}")
    monkeypatch.setattr(R, "committed", lambda path: False)
    with pytest.raises(SystemExit, match="must exist and be committed"):
        R.lockbox_main("forecast")
    # an early ForecastBench selection opens the ForecastBench lockbox only
    early.write_text(json.dumps({"forecast": {"policy": None}}))
    monkeypatch.setattr(R, "committed", lambda path: path == early)
    assert set(R.frozen_selection()) == {"forecast"}
    with pytest.raises(SystemExit, match="must exist and be committed"):
        R.lockbox_main("bbeh")
    (tmp_path / "lockbox_forecast.md").write_text("read")
    with pytest.raises(SystemExit, match="never read again"):
        R.lockbox_main("forecast")


def test_full_selection_keeps_a_committed_early_forecast_freeze(tmp_path, monkeypatch):
    """Audit 64: select_main uses selected_forecast.json only when it is committed unchanged, and stops otherwise."""
    early = tmp_path / "selected_forecast.json"
    monkeypatch.setattr(R, "FORECAST_OUT", early)
    assert R.early_forecast() is None
    early.write_text(json.dumps({"forecast": {"policy": {"first round": "haiku x2 + luna x2"}}}))
    monkeypatch.setattr(R, "committed", lambda path: False)
    with pytest.raises(SystemExit, match="not committed"):
        R.early_forecast()
    monkeypatch.setattr(R, "committed", lambda path: path == early)
    assert R.early_forecast()["policy"]["first round"] == "haiku x2 + luna x2"


def test_early_forecast_selection_needs_the_committed_g2b_read(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "OUT", tmp_path / "selected.json")
    monkeypatch.setattr(R, "FORECAST_OUT", tmp_path / "selected_forecast.json")
    monkeypatch.setattr(R, "READS_FIRST", [tmp_path / "a.md", tmp_path / "phase1_forecast.md", tmp_path / "b.md"])
    with pytest.raises(SystemExit, match="G2b read"):
        R.select_forecast_main()
    (tmp_path / "selected_forecast.json").write_text("{}")
    with pytest.raises(SystemExit, match="never rewritten"):
        R.select_forecast_main()


def test_committed_is_false_for_an_untracked_file():
    probe = R.ROOT / "research/v3/pruning/_untracked_probe.json"
    probe.write_text("{}")
    try:
        assert not R.committed(probe)
    finally:
        probe.unlink()
    assert R.committed(R.ROOT / "analysis/pruning_cascade.py") in (True, False)  # tracked; clean or not


def test_nothing_else_reads_the_lockbox_calls():
    """Only analysis/pruning_cascade.py (behind its guard) and the e31 run itself touch results/e31_*/calls.csv."""
    readers = []
    for path in list((R.ROOT / "analysis").glob("*.py")) + list((R.ROOT / "autoagentnet").rglob("*.py")):
        text = path.read_text()
        if "e31_lockbox" in text and "read_csv" in text and path.name not in ("pruning_cascade.py", "pruning_lockbox.py"):
            readers.append(path.name)
    assert readers == []


def test_selection_refuses_before_the_committed_reads(tmp_path, monkeypatch):
    """Audit 52: the selection reads sealed Phase 1-2 labels, so the G2a, G2b and Phase 2 reads come first."""
    monkeypatch.setattr(R, "OUT", tmp_path / "selected.json")
    monkeypatch.setattr(R, "READS_FIRST", [tmp_path / "phase1_bbeh.md"])
    with pytest.raises(SystemExit, match="not selecting"):
        R.select_main()


@pytest.mark.needs_external("evidence/bbeh.jsonl")
def test_blind_runs_write_no_grade_and_the_read_regrades():
    """Audit 52: lockbox calls carry no grade on disk; the committed read grades them from the task file."""
    from autoagentnet.evidence.panel import blinded
    from autoagentnet.tasks import load_tasks

    graded = {"answer": "(B)", "parsed": True, "correct": 1.0, "prob": None}
    assert blinded(graded, True)["correct"] is None and blinded(graded, False)["correct"] == 1.0
    tasks = load_tasks(R.ROOT / "data/external/evidence/bbeh.jsonl")[:3]
    calls = pd.DataFrame({"item": [t.id for t in tasks], "answer": [tasks[0].answer, "zzz", tasks[2].answer],
                          "parsed": [True, True, False], "correct": [None] * 3})
    assert R.regrade(calls, "bbeh")["correct"].tolist() == [1.0, 0.0, 0.0]


def test_e31_configs_are_blind():
    import yaml

    for path in (R.ROOT / "configs/experiments/evidence").glob("e31_lockbox_*.yaml"):
        cfg = yaml.safe_load(path.read_text())
        assert cfg["blind"] is True and "requires" not in cfg


def forecast_calls(n=200, seed=5):
    """Simulated ForecastBench calls for every forecast unit: Sol sharp and dear, Sonnet a little less sharp and
    dearer, Haiku and Luna noisy and cheap."""
    rng = np.random.default_rng(seed)
    units = sorted({u for name in R.FORECAST_ROUNDS for u in R.FIRST_ROUNDS[name]} | set(R.ESCALATIONS.values()))
    noise = {"haiku_nothink": 1.2, "luna_none": 1.5, "sonnet_nothink": 0.6, "sol61_low": 0.5}
    usd = {"haiku_nothink": 0.0002, "luna_none": 0.0001, "sonnet_nothink": 0.004, "sol61_low": 0.002}
    truth = rng.normal(0, 1.5, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-truth))).astype(int)
    rows = []
    for i in range(n):
        for u in units:
            ref, prompt, call = u.split(":")
            p = 1 / (1 + np.exp(-(truth[i] + rng.normal(0, noise[ref]))))
            rows.append({"item": f"fc-{i:03d}", "source": f"{ref}:{prompt}", "call": int(call), "prob": p,
                         "parsed": True, "outcome": y[i], "cost_usd": usd[ref], "seconds": 1.0})
    return pd.DataFrame(rows)


def test_forecast_rule_uses_sol_as_its_reference(monkeypatch):
    """Deviation 29: the table carries Sol's Brier and dollars as the reference, and the frozen policy is the
    cheapest whose cross-fitted Brier is within BRIER_MARGIN of Sol's."""
    calls = forecast_calls()
    monkeypatch.setattr(R, "read_items", lambda name: sorted(set(calls["item"])))
    panel, table = R.forecast_table(calls)
    o = R.C.unit_positions(panel, [R.ESCALATIONS["sol"]])[0]
    assert table["reference brier"].iloc[0] == pytest.approx(((panel.votes[:, o] - panel.outcome) ** 2).mean())
    assert table["reference dollars"].iloc[0] == pytest.approx(0.002)
    assert len(table) == len(R.FORECAST_ROUNDS) * len(R.ESCALATIONS)
    sel = R.select_forecast(calls)
    ok = table[table["brier"] <= table["reference brier"] + R.BRIER_MARGIN].sort_values(["dollars", "brier"])
    if ok.empty:
        assert sel["policy"] is None
    else:
        assert sel["policy"]["first round"] == ok.iloc[0]["first round"]
        assert sel["policy"]["reference"] == R.FORECAST_REFERENCE


def test_forecast_lockbox_read_is_three_way(monkeypatch):
    """The pre-logged reading (audit 61) and the read's rows: source-stratified and question intervals, the
    leave-one-source-out range, a dollar ratio, against Sol (decision) and Sonnet."""
    assert R.reading(-0.004, 0.008, 0.3) == "candidate"
    assert R.reading(-0.004, 0.008, 0.6) == "inconclusive"  # close enough, but not cheap enough
    assert R.reading(0.001, 0.02, 0.3) == "Sol is better"
    assert R.reading(-0.002, 0.012, 0.3) == "inconclusive"
    calls = forecast_calls(n=100, seed=7)
    monkeypatch.setattr(R, "read_items", lambda name: sorted(set(calls["item"])))
    frozen = R.select_forecast(calls)["policy"] or {"units": R.FIRST_ROUNDS["luna x5"], "escalation": R.FORECAST_REFERENCE, "s": 2.0}
    units = sorted(set(frozen["units"]) | {frozen["escalation"], R.SONNET, R.FORECAST_REFERENCE})
    panel = R.build(calls, "forecast", units)
    source = np.array([f"s{i % 5}" for i in range(panel.n)])
    resolution = np.array([f"2026-08-{1 + 7 * (i % 3):02d}" for i in range(panel.n)])  # 15 source x week cells
    text = "\n".join(R.forecast_lockbox(panel, frozen, source, resolution))
    assert text.count("within source") == 2 and "leaving one source out" in text
    assert text.count("the wider:") == 2 and "Reading (pre-logged, audits 61-62): **" in text and "minus Sonnet alone" in text


def test_forecast_decision_interval_is_the_wider_of_question_and_week_clusters():
    """H10 (deviation 31): when the differences move together within source x week cells, the cluster interval is
    wider than the question interval and becomes the decision interval; the choice is always the wider of the two."""
    rng = np.random.default_rng(11)
    cell = np.repeat(np.arange(12), 10)  # 12 source x week cells of 10 questions
    source = np.array([f"s{c % 4}" for c in cell])
    resolution = np.array([f"2026-08-{1 + 7 * (c // 4):02d}" for c in cell])
    d = rng.normal(0, 0.02, 12)[cell] + rng.normal(0, 0.002, 120)
    primary, found = R.decision_interval(d, source, resolution)
    width = {k: v["hi"] - v["lo"] for k, v in found.items()}
    assert primary == "source x week" and width["source x week"] > 2 * width["question"]
    primary, found = R.decision_interval(rng.normal(0, 0.02, 120), source, resolution)
    assert primary == max(("question", "source x week"), key=lambda k: found[k]["hi"] - found[k]["lo"])
