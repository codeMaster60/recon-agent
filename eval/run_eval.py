"""Measure detection accuracy against injected ground truth, across seeds and bank layouts.

    python eval/run_eval.py                 # rules only, 20 seeds x 3 layouts
    python eval/run_eval.py --llm           # also run the LLM mapping path (needs GROQ_API_KEY)
    python eval/run_eval.py --seeds 50 --write eval/RESULTS.md
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

import generate  # noqa: E402

from recon import reconcile  # noqa: E402
from recon.ingest import MappingError, load_bank, load_orders, load_report  # noqa: E402
from recon.llm import get_client  # noqa: E402

LAYOUTS = {"a": "bank_format_a.csv", "b": "bank_format_b.xlsx", "c": "bank_format_c.csv", "d": "bank_format_d.csv"}


def run(seeds: int, layouts: list[str], use_llm: bool, hard: bool = False) -> dict:
    client = get_client() if use_llm else None
    mode = "llm" if client else "rules"
    counts = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    mapping = defaultdict(lambda: {"ok": 0, "fail": 0, "source": defaultdict(int)})
    fp_examples: list[str] = []
    high = {"tp": 0, "fp": 0}
    t0 = time.time()
    for seed in range(1, seeds + 1):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            data = generate.build(seed, hard=hard)
            generate.write(data, out)
            truth = {(t["type"], t["key"]) for t in data["truth"]}
            report = load_report(out / "settlement_report.csv").df
            orders = load_orders(out / "orders.csv").df
            for layout in layouts:
                try:
                    loaded = load_bank(out / LAYOUTS[layout], client=client, mode=mode)
                except MappingError:
                    mapping[layout]["fail"] += 1
                    continue
                mapping[layout]["ok"] += 1
                mapping[layout]["source"][loaded.chosen.source] += 1
                exceptions = reconcile(report, loaded.df, orders).exceptions
                found = {(e.type, e.key) for e in exceptions}
                for e in exceptions:
                    if e.severity == "high":
                        high["tp" if (e.type, e.key) in truth else "fp"] += 1
                for kind in {t for t, _ in truth | found}:
                    t_k = {k for t, k in truth if t == kind}
                    f_k = {k for t, k in found if t == kind}
                    counts[kind]["tp"] += len(t_k & f_k)
                    counts[kind]["fp"] += len(f_k - t_k)
                    counts[kind]["fn"] += len(t_k - f_k)
                    if f_k - t_k and len(fp_examples) < 10:
                        fp_examples.append(f"seed {seed} layout {layout}: {kind} {sorted(f_k - t_k)}")
    return {"counts": counts, "mapping": mapping, "fp_examples": fp_examples, "seconds": time.time() - t0,
            "seeds": seeds, "mode": mode, "hard": hard, "high": high}


def to_markdown(res: dict) -> str:
    lines = [f"Seeds: {res['seeds']} · data: {'hard (posting lag + truncated narrations)' if res['hard'] else 'clean'} · "
             f"mapping mode: `{res['mode']}` · runtime {res['seconds']:.1f}s", "",
             "### Column mapping by bank layout", "", "| Layout | Mapped | Failed | Source |", "|---|---|---|---|"]
    for layout, m in sorted(res["mapping"].items()):
        src = ", ".join(f"{k}: {v}" for k, v in m["source"].items()) or "-"
        lines.append(f"| {layout} | {m['ok']} | {m['fail']} | {src} |")
    lines += ["", "### Exception detection (mapped layouts only)", "",
              "| Problem | Injected | Caught | False alarms | Precision | Recall |", "|---|---|---|---|---|---|"]
    tp = fp = fn = 0
    for kind, c in sorted(res["counts"].items()):
        injected = c["tp"] + c["fn"]
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 1.0
        r = c["tp"] / injected if injected else 1.0
        lines.append(f"| {kind} | {injected} | {c['tp']} | {c['fp']} | {p:.1%} | {r:.1%} |")
        tp, fp, fn = tp + c["tp"], fp + c["fp"], fn + c["fn"]
    lines.append(f"| **all** | **{tp + fn}** | **{tp}** | **{fp}** | **{tp / max(1, tp + fp):.1%}** | **{tp / max(1, tp + fn):.1%}** |")
    h = res["high"]
    lines += ["", f"High-severity alerts (the ones a merchant acts on first): {h['tp'] + h['fp']} raised, "
              f"{h['fp']} false, precision {h['tp'] / max(1, h['tp'] + h['fp']):.1%}."]
    if res["fp_examples"]:
        lines += ["", "False alarm examples:", ""] + [f"- {x}" for x in res["fp_examples"]]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=20)
    parser.add_argument("--layouts", default="abcd")
    parser.add_argument("--llm", action="store_true")
    parser.add_argument("--hard", action="store_true", help="posting lag + truncated narrations")
    parser.add_argument("--write", type=Path)
    args = parser.parse_args()
    md = to_markdown(run(args.seeds, list(args.layouts), args.llm, args.hard))
    print(md)
    if args.write:
        args.write.write_text("# Evaluation results\n\n" + md + "\n")


if __name__ == "__main__":
    main()
