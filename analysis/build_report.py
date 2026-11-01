"""Build reports/pilot/report.html and report.pdf from the analysis outputs.

The prose lives in reports/pilot/report.md. Numbers never are typed into it by hand; it
pulls them in with placeholders that this script fills from files the analysis scripts wrote:

  {{table:NAME}}         reports/pilot/tables/NAME.csv as an HTML table
  {{figure:NAME|CAPTION}} reports/pilot/figures/NAME.png with a caption
  {{include:PATH}}       a Markdown file from the repo (e.g. research/data_cards.md), headings demoted
  {{value:KEY}}          a number from reports/pilot/tables/values.json

Steps: run analysis.budget (always) and analysis.gate / analysis.landscape when their
results exist, then render. The PDF is printed by Chromium through Node Playwright
(analysis/print_pdf.mjs); no LaTeX toolchain is installed in the cloud session.

Usage: python -m analysis.build_report
"""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path

import pandas as pd

from . import common

CSS = """
@page { size: Letter; margin: 0.75in 0.7in; }
body { font-family: "Times New Roman", "Liberation Serif", "DejaVu Serif", serif; font-size: 10pt; line-height: 1.3;
       color: #000; background: #fff; }
h1 { font-size: 15pt; text-align: center; margin: 0 0 4pt; }
.byline { text-align: center; font-size: 10pt; margin-bottom: 10pt; }
.abstract { margin: 0 0.5in 12pt; font-size: 9.5pt; }
.columns { column-count: 2; column-gap: 0.28in; }
h2 { font-size: 11pt; margin: 10pt 0 4pt; break-after: avoid; }
h3 { font-size: 10pt; margin: 8pt 0 3pt; break-after: avoid; }
h4 { font-size: 10pt; font-style: italic; margin: 6pt 0 2pt; }
p, li { text-align: justify; hyphens: auto; }
ul, ol { padding-left: 14pt; margin: 3pt 0; }
table { border-collapse: collapse; font-size: 7.5pt; margin: 4pt 0 8pt; width: 100%; break-inside: avoid; }
th, td { border-top: 0.5pt solid #444; border-bottom: 0.5pt solid #444; padding: 1.5pt 3pt; text-align: right; }
th:first-child, td:first-child { text-align: left; }
th { background: #eee; }
figure { margin: 6pt 0 10pt; break-inside: avoid; }
figure img { width: 100%; }
figcaption { font-size: 8.5pt; }
code { font-size: 8.5pt; }
.wide { column-span: all; }
table.wide { font-size: 7pt; }
.appendix { break-before: page; }
"""

PLACEHOLDER = re.compile(r"\{\{(table|figure|include|value):([^}|]+)(?:\|([^}]*))?\}\}")


def csv_table(name: str) -> str:
    path = common.TABLES / f"{name}.csv"
    if not path.exists():
        return f"<p><em>[table {html.escape(name)} not produced: no data for it yet]</em></p>"
    df = pd.read_csv(path)
    html_table = df.to_html(index=False, na_rep="", float_format=lambda x: f"{x:.4g}", border=0)
    if len(df.columns) > 5:  # too wide for one column of the two-column layout
        html_table = html_table.replace('<table class="dataframe">', '<table class="dataframe wide">', 1)
    return html_table


def figure(name: str, caption: str) -> str:
    path = common.FIGURES / f"{name}.png"
    if not path.exists():
        return f"<p><em>[figure {html.escape(name)} not produced: no data for it yet]</em></p>"
    return f'<figure><img src="figures/{name}.png" alt="{html.escape(name)}"><figcaption>{caption}</figcaption></figure>'


def include(path: str) -> str:
    source = common.ROOT / path.strip()
    if not source.exists():
        return f"*[{path} not found]*"
    text = source.read_text()
    return re.sub(r"^(#+)", lambda m: "#" * min(len(m.group(1)) + 2, 6), text, flags=re.MULTILINE)


def render(markdown_text: str, values: dict) -> str:
    import markdown

    def fill(m: re.Match) -> str:
        kind, key, extra = m.group(1), m.group(2).strip(), m.group(3) or ""
        if kind == "table":
            return "\n\n" + csv_table(key) + "\n\n"
        if kind == "figure":
            return "\n\n" + figure(key, extra) + "\n\n"
        if kind == "include":
            return include(key)
        if key not in values:
            return f"[{key}: n/a]"
        v = values[key]
        return f"{v:.4g}" if isinstance(v, float) else str(v)

    # includes first, so placeholders inside included files are filled too
    text = PLACEHOLDER.sub(lambda m: include(m.group(2)) if m.group(1) == "include" else m.group(0), markdown_text)
    text = PLACEHOLDER.sub(fill, text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "md_in_html"])

    def widen(m: re.Match) -> str:  # Markdown tables with more than 5 columns span both columns too
        return m.group(0).replace("<table>", '<table class="wide">', 1) if m.group(0).count("<th") > 5 else m.group(0)

    return re.sub(r"<table>\s*<thead>.*?</thead>", widen, body, flags=re.DOTALL)


def wrap(body: str, title: str) -> str:
    return f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>"


def print_pdf(html_path: Path, pdf_path: Path) -> str:
    script = Path(__file__).with_name("print_pdf.mjs")
    done = subprocess.run(["node", str(script), str(html_path), str(pdf_path)], capture_output=True, text=True)
    return "ok" if done.returncode == 0 else f"PDF failed: {done.stderr.strip()[:300]}"


def setup_tables() -> None:
    """Tables that describe the setup: prices (ours vs official), every pilot config, recorded
    estimates, the worst-case cost of named configs, and the scale-up designs."""
    import yaml

    from autoagentnet.pricing import PriceBook

    book = PriceBook.from_yaml(common.ROOT / "configs/pricing.yaml")
    official = pd.read_csv(common.ROOT / "research/official_prices.csv")
    ours = []
    for model in official["model"]:
        p = book.price(model, "x")
        ours.append({"model": model, "ours_input": p.input,
                     "ours_cache_write": p.cache_write if p.cache_write is not None else p.input,
                     "ours_cache_read": p.cache_read if p.cache_read is not None else p.input, "ours_output": p.output})
    prices = official.merge(pd.DataFrame(ours), on="model")
    prices["ours_at_or_above_official"] = (
        (prices["ours_input"] >= prices["input_usd_per_mtok"])
        & (prices["ours_cache_write"] >= prices["cache_write_usd_per_mtok"])
        & (prices["ours_cache_read"] >= prices["cache_read_usd_per_mtok"])
        & (prices["ours_output"] >= prices["output_usd_per_mtok"]))
    common.save_table(prices.drop(columns=["source", "note"]), "prices")

    rows = []
    for path in sorted((common.ROOT / "configs/experiments/pilot").glob("*.yaml")):
        c = yaml.safe_load(path.read_text())
        grid = c.get("configs")
        if grid == "all":
            n_configs = "all 216"
        elif isinstance(grid, dict):  # factorial: every combination of the levels in the 3 middle stages
            n_configs = f"{len(grid['levels']) ** 3} (levels {'/'.join(map(str, grid['levels']))})"
        else:
            n_configs = len(grid or []) + 1  # the listed configs plus dense
        rows.append({"experiment": c["name"], "network": Path(c["network"]).stem, "tasks": Path(c["tasks"]).stem,
                     "offset": c.get("task_offset", 0), "limit": c.get("task_limit"), "ref": c.get("model_override"),
                     "configs": n_configs, "replicates": c.get("replicates", 1), "max_usd": c.get("max_usd")})
    configs_table = pd.DataFrame(rows)
    common.save_table(configs_table, "pilot_configs")

    est_path = common.ROOT / "research/estimates.csv"
    if est_path.exists():
        est = pd.read_csv(est_path)
        est = est[est["experiment"].isin(configs_table["experiment"])]  # superseded configs stay in the CSV as history
        est = est[est["date"] == est.groupby("experiment")["date"].transform("max")]
        est = est.groupby("experiment")[["calls", "worst_case_x_safety"]].sum().reset_index()
        est["step"] = est["experiment"].str.split("_").str[0]
        common.save_table(est[["step", "experiment", "calls", "worst_case_x_safety"]].sort_values("experiment").round(4),
                          "estimates")

    demo = common.REPORT / "demo" / "data.json"
    if demo.exists():
        data = json.loads(demo.read_text())
        configs = pd.DataFrame(data["configs"])
        named = {"k6-6-6-1": "dense", "k6-2-2-1": "propose-heavy", "k3-3-3-1": "uniform 3", "k2-2-2-1": "uniform 2",
                 "k1-1-1-1": "minimal"}
        t = configs[configs["id"].isin(named)].assign(name=lambda d: d["id"].map(named))
        dense = configs.loc[configs["id"] == "k6-6-6-1", "worst_usd"].iloc[0]
        t["share_of_dense"] = t["worst_usd"] / dense
        common.save_table(t[["name", "id", "calls", "worst_usd", "share_of_dense"]].sort_values("calls", ascending=False).round(5),
                          "worst_case_named")
        plot_worst_case(configs, named, data["shared_calls_per_task"], data["naive_calls_per_task"])

    from . import power, scaleup_costs

    scaleup_costs.main()
    power.main()


def plot_worst_case(configs: pd.DataFrame, named: dict, shared: float, naive: int) -> None:
    """Figure (g): the cost axis of the landscape, known before any run: worst-case dollars per
    task of all 216 configs against the number of agent calls."""
    plt = common.style()
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    ax.scatter(configs["calls"], 1000 * configs["worst_usd"], s=10, color="0.55", label="216 configs")
    for i, (cid, name) in enumerate(named.items()):
        row = configs[configs["id"] == cid].iloc[0]
        ax.scatter(row["calls"], 1000 * row["worst_usd"], marker="D", s=34, color=common.color(i),
                   label=f"{name} ({cid})", zorder=3)
    ax.set_xlabel("agent calls per task")
    ax.set_ylabel("worst-case cost per task (USD x 1000)")
    ax.set_title(f"Worst-case bound for all 216 configs; together they need {shared:.0f} distinct calls per task, not {naive}",
                 fontsize=7)
    ax.legend(fontsize=6)
    common.save_figure(fig, "g_worst_case")


def p4_halves(results: Path | None = None, configs: Path | None = None) -> tuple[list[Path], list[Path]]:
    """P4 result folders split by part letter: the first half of the *configured* parts
    (configs/experiments/pilot/p4_*_grid_*.yaml in v2) is the search half, the rest held out, so a
    partly finished P4 never labels a search part as held out (audit 2, finding 6; audit 3, finding 3)."""
    results = results or common.ROOT / "results"
    configs = configs or common.ROOT / "configs/experiments/pilot"
    search, held = [], []
    parts = sorted(results.glob("p4_*_grid_?")) + sorted(results.glob("p4_*_landscape_?"))  # v2 grid, v1 landscape
    for done in parts:
        prefix, letter = done.name[:-1], done.name[-1]
        n_parts = len(list(configs.glob(f"{prefix}?.yaml")))
        index = "abcdefghijklmnopqrst".index(letter)
        (search if index < max(1, n_parts // 2) else held).append(done)
    return search, held


def run_analyses() -> dict:
    from . import budget, calibration, gate

    values: dict = {}
    setup_tables()
    est = pd.read_csv(common.TABLES / "estimates.csv")
    by_step = est.groupby("step")["worst_case_x_safety"].sum()
    for step, usd in by_step.items():
        values[f"est_{step}_usd"] = round(float(usd), 3)
    values["est_total_usd"] = round(float(by_step.sum()), 2)
    configs = pd.read_csv(common.TABLES / "pilot_configs.csv").set_index("experiment")
    grid = est[est["experiment"].str.match(r"p4_.*_grid_a$")]
    if len(grid):  # distinct calls per task of the factorial grid, from the recorded estimate
        values["grid_calls_per_task"] = int(grid["calls"].iloc[0] / configs.loc[grid["experiment"].iloc[0], "limit"])
    scale = pd.read_csv(common.TABLES / "scaleup_costs.csv")
    for design, usd in scale.groupby("design")["worst_x_safety_usd"].sum().items():
        values[f"scale_{design}_usd"] = round(float(usd), 2)
    options = pd.read_csv(common.TABLES / "scaleup_options.csv")  # B's low/high differ until P4's picks are known
    for row in options.to_dict("records"):
        key = row["option"].replace(" + ", "_").replace(" ", "_")
        values[f"scale_option_{key}_low_usd"], values[f"scale_option_{key}_high_usd"] = row["low_usd"], row["high_usd"]
    named = pd.read_csv(common.TABLES / "worst_case_named.csv").set_index("name")
    values["dense_worst_usd"] = round(float(named.loc["dense", "worst_usd"]), 4)
    values["minimal_worst_usd"] = round(float(named.loc["minimal", "worst_usd"]), 4)
    demo = json.loads((common.REPORT / "demo" / "data.json").read_text())
    values["shared_calls"] = int(round(demo["shared_calls_per_task"]))
    values["naive_calls"] = demo["naive_calls_per_task"]
    calibration.main()
    tables = budget.main(pilot_only=True)  # the market town and v3 report their own spend
    accounts = tables["by_account"].set_index("account")
    values["spent_total_usd"] = round(float(accounts["spent_usd"].sum()), 4)
    for account in accounts.index:
        values[f"spent_{account}_usd"] = round(float(accounts.loc[account, "spent_usd"]), 4)
    for step in ("p2", "p3"):
        if gate.find_pairs(step):
            gate.main(step)
    search_dirs, held_dirs = p4_halves()
    if search_dirs:
        from . import economics, landscape

        singles = [str(p) for p in sorted((common.ROOT / "results").glob("p[34]*_*_single*/results.csv"))
                   if "sonnet" not in p.parent.name]  # single Haiku runs only (incl. p4_*_single_held)
        summary = landscape.main([str(d) for d in search_dirs], [str(d) for d in held_dirs], single_results=singles)
        values.update({f"p4_{k}": v for k, v in summary.items() if not isinstance(v, dict)})
        economics.main([str(d) for d in search_dirs], [str(d) for d in held_dirs])  # figures h, i; econ_* tables
    from . import designs

    designs.main(search_dirs, held_dirs)  # research/designs.md and tables/designs.csv (a planned list until P4 runs)
    if (common.ROOT / "results" / "p4_bbeh_single_held").exists():
        from . import headline

        headline.main()  # tables/headline.csv: dense vs single, vote6 and Sonnet by item set (session 4)
    return values


def main(source: Path | None = None) -> Path:
    source = source or common.REPORT / "report.md"
    values = run_analyses()
    values_path = common.TABLES / "values.json"
    values_path.parent.mkdir(parents=True, exist_ok=True)
    values_path.write_text(json.dumps(values, indent=2, default=str))
    text = source.read_text()
    title = text.splitlines()[0].lstrip("# ").strip()
    out = common.REPORT / "report.html"
    out.write_text(wrap(render(text, values), title))
    print(f"wrote {out}; {print_pdf(out, common.REPORT / 'report.pdf')}")
    return out


if __name__ == "__main__":
    main()
