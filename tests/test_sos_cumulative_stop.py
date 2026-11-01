"""LAB-Bench Amendment 5: with stop_scope "cumulative" the stop rules read every call of the config so far (all
slices, replays counted as live), so slicing a run cannot by itself trip a rule (offline, synthetic rows)."""
import pandas as pd

from autoagentnet.evidence.panel import PanelExpect, expectation_misses
from autoagentnet.self_or_social.run import SelfOrSocialConfig, judged_calls


def calls(n, bad, from_cache=False):
    return [{"source": "C:branch", "ref": "sol61_med", "parsed": i >= bad, "truncated": False, "from_cache": from_cache,
             "stop_reason": "content_filter" if i < bad else "stop", "answer": None if i < bad else "A",
             "task_kind": "mcq", "cost_usd": 0.01} for i in range(n)]


def test_a_slice_is_judged_with_all_earlier_calls_when_cumulative():
    expect = PanelExpect(min_calls=20, max_unparsed_rate=0.10, max_truncation_rate=0.10)
    slice_rows = calls(24, 3)                                  # one refused item: 3 of 24 = 12.5% in the slice
    table = pd.DataFrame(calls(48, 0, from_cache=True) + slice_rows)   # earlier slices (replayed rows included)
    assert expectation_misses(judged_calls(slice_rows, table, "run"), expect)          # per slice: trips
    assert not expectation_misses(judged_calls(slice_rows, table, "cumulative"), expect)   # 3 of 72: passes
    many = pd.DataFrame(calls(48, 9) + slice_rows)            # 12 of 72 = 16.7% over the whole run: still trips
    assert expectation_misses(judged_calls(slice_rows, many, "cumulative"), expect)


def test_stop_scope_defaults_to_the_run():
    field = SelfOrSocialConfig.model_fields["stop_scope"]
    assert field.default == "run"
