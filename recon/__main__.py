"""Command line:  python -m recon --report R.csv --bank B.csv [--orders O.csv] [--out out/]"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import Config, reconcile
from .ingest import MappingError, load_bank, load_orders, load_report
from .llm import get_client
from .report import llm_summary, template_summary, to_html


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m recon", description="Reconcile Razorpay settlements with your bank statement and orders.")
    ap.add_argument("--report", required=True, type=Path, help="Razorpay settlement recon report (CSV/XLSX)")
    ap.add_argument("--bank", type=Path, help="bank statement for the same period (CSV/XLSX, any bank layout)")
    ap.add_argument("--orders", type=Path, help="your own orders/bookings export (optional)")
    ap.add_argument("--out", type=Path, default=Path("out"))
    ap.add_argument("--llm", choices=["auto", "on", "off"], default="auto",
                    help="auto: LLM only when rules can't map a file; on: always try it; off: never")
    ap.add_argument("--rate-card", type=Path, help="JSON like {\"upi\": 0, \"card\": 2.0} with your fee %% per method")
    args = ap.parse_args()

    client = None if args.llm == "off" else get_client()
    mode = {"auto": "auto", "on": "llm", "off": "rules"}[args.llm]
    cfg = Config()
    if args.rate_card:
        cfg.rate_card.update(json.loads(args.rate_card.read_text()))

    try:
        report = load_report(args.report, client=client, mode=mode)
        bank = load_bank(args.bank, client=client, mode=mode) if args.bank else None
        orders = load_orders(args.orders, client=client, mode=mode) if args.orders else None
    except MappingError as exc:
        raise SystemExit(f"error: {exc}")

    mapping_notes = []
    for label, loaded in (("report", report), ("bank", bank), ("orders", orders)):
        if loaded:
            print(f"{label:7} {loaded.describe()}")
            mapping_notes += [f"{label}: {n}" for n in loaded.chosen.notes]

    result = reconcile(report.df, bank.df if bank else None, orders.df if orders else None, cfg)
    summary, used_llm = llm_summary(result, client) if client else (template_summary(result), False)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.html").write_text(to_html(result, summary, mapping_notes), encoding="utf-8")
    result.exceptions_frame().to_csv(args.out / "exceptions.csv", index=False)
    (args.out / "summary.json").write_text(json.dumps({"summary": summary, "llm_summary": used_llm, "stats": result.stats,
                                                       "notes": result.notes}, indent=2, default=str))
    print("\n" + summary)
    print(f"\nwrote {args.out}/report.html, exceptions.csv, summary.json")


if __name__ == "__main__":
    main()
