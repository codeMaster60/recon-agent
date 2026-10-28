import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "data")]

import generate  # noqa: E402

from recon import reconcile  # noqa: E402
from recon.ingest import MappingError, load_bank, load_orders, load_report  # noqa: E402
from recon.parse import extract_utr_candidates, inr, parse_amount, parse_dates  # noqa: E402
from recon.report import llm_summary, template_summary  # noqa: E402


class FakeLLM:
    model = "fake"

    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, system, user, json_mode=False):
        self.calls += 1
        return self.reply if isinstance(self.reply, str) else json.dumps(self.reply, ensure_ascii=False)


@pytest.fixture(scope="module")
def month(tmp_path_factory):
    out = tmp_path_factory.mktemp("samples")
    data = generate.build(seed=11)
    generate.write(data, out)
    return out, {(t["type"], t["key"]) for t in data["truth"]}


# ---------------------------------------------------------------- parsing

@pytest.mark.parametrize("raw,expected", [
    ("1,23,456.00", 123456.0), ("₹ 499", 499.0), ("(250.00)", -250.0), ("500.00 Cr", 500.0),
    ("500.00 Dr", -500.0), ("-12.5", -12.5), ("", None), ("abc", None), ("--", None),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_dates_prefer_day_first():
    assert parse_dates(["04/09/26", "12/09/26"]) == [date(2026, 9, 4), date(2026, 9, 12)]
    assert parse_dates(["04-Sep-2026"]) == [date(2026, 9, 4)]
    assert parse_dates(["2026-09-04 11:22:10"]) == [date(2026, 9, 4)]


def test_utr_extraction_skips_ifsc_and_upi_refs():
    text = "BY TRANSFER-NEFT*UTIB0000247*AXISN26247123456*RAZORPAY UPI/CR/941844010951/X"
    assert extract_utr_candidates(text) == ["AXISN26247123456"]


def test_inr_grouping():
    assert inr(123456.5) == "1,23,456.50"
    assert inr(999) == "999.00"


# ---------------------------------------------------------------- column mapping

@pytest.mark.parametrize("name", ["bank_format_a.csv", "bank_format_b.xlsx", "bank_format_c.csv"])
def test_rules_map_common_layouts(month, name):
    out, _ = month
    loaded = load_bank(out / name)
    assert loaded.chosen.source == "rules"
    assert loaded.chosen.checks["balance_continuity"] == 1.0
    assert len(loaded.df) > 50


def test_hindi_layout_fails_cleanly_without_llm(month):
    out, _ = month
    with pytest.raises(MappingError, match="GROQ_API_KEY"):
        load_bank(out / "bank_format_d.csv")


def test_llm_maps_hindi_layout_and_code_verifies_it(month):
    out, _ = month
    llm = FakeLLM({"date": "लेनदेन तिथि", "description": "विवरण", "ref": "संदर्भ संख्या",
                   "debit": "नामे", "credit": "जमा", "balance": "शेष"})
    loaded = load_bank(out / "bank_format_d.csv", client=llm)
    assert loaded.chosen.source == "llm" and llm.calls == 1
    assert loaded.chosen.checks["balance_continuity"] == 1.0  # newest-first order handled


def test_llm_swapped_debit_credit_is_repaired_by_balance_check(month):
    out, _ = month
    llm = FakeLLM({"date": "लेनदेन तिथि", "description": "विवरण", "debit": "जमा", "credit": "नामे", "balance": "शेष"})
    loaded = load_bank(out / "bank_format_d.csv", client=llm)
    assert any("swapped" in n for n in loaded.chosen.notes)
    assert loaded.df["amount"].max() > 0 and (loaded.df["description"].str.contains("RAZORPAY") & (loaded.df["amount"] > 0)).any()


def test_llm_garbage_mapping_is_rejected(month):
    out, _ = month
    llm = FakeLLM({"date": "विवरण", "description": "शेष", "amount": "लेनदेन तिथि"})
    with pytest.raises(MappingError):
        load_bank(out / "bank_format_d.csv", client=llm)


def test_rules_fast_path_skips_llm(month):
    out, _ = month
    llm = FakeLLM({})
    load_bank(out / "bank_format_a.csv", client=llm)
    assert llm.calls == 0


# ---------------------------------------------------------------- reconciliation

@pytest.mark.parametrize("name", ["bank_format_a.csv", "bank_format_b.xlsx", "bank_format_c.csv"])
def test_finds_every_injected_problem_and_nothing_else(month, name):
    out, truth = month
    result = reconcile(load_report(out / "settlement_report.csv").df, load_bank(out / name).df,
                       load_orders(out / "orders.csv").df)
    assert {(e.type, e.key) for e in result.exceptions} == truth


def _report(rows):
    base = {"fee": 0.0, "tax": 0.0, "on_hold": False, "settled": True, "order_receipt": "", "method": "upi",
            "created_at": date(2026, 9, 1)}
    frame = pd.DataFrame([{**base, **r} for r in rows])
    frame["credit"] = frame.apply(lambda r: r["amount"] - r["fee"] - r["tax"] if r["type"] == "payment" else 0.0, axis=1)
    frame["debit"] = frame.apply(lambda r: r["amount"] if r["type"] == "refund" else 0.0, axis=1)
    return frame


def _bank(rows):
    return pd.DataFrame([{"ref": "", "balance": None, **r} for r in rows]).assign(row=lambda f: range(len(f)))


def test_negative_settlement_carries_into_next_payout():
    report = _report([
        {"entity_id": "pay_1", "type": "payment", "amount": 100.0, "settlement_id": "s1", "settlement_utr": "AXISN26245000001", "settled_at": date(2026, 9, 3)},
        {"entity_id": "rfnd_1", "type": "refund", "amount": 300.0, "settlement_id": "s1", "settlement_utr": "AXISN26245000001", "settled_at": date(2026, 9, 3)},
        {"entity_id": "pay_2", "type": "payment", "amount": 1000.0, "settlement_id": "s2", "settlement_utr": "AXISN26246000002", "settled_at": date(2026, 9, 4)},
    ])
    bank = _bank([
        {"date": date(2026, 9, 1), "description": "OPENING", "amount": 1.0},
        {"date": date(2026, 9, 4), "description": "NEFT/AXISN26246000002/RAZORPAY", "amount": 800.0},
        {"date": date(2026, 9, 30), "description": "UPI", "amount": -5.0},
    ])
    result = reconcile(report, bank)
    assert result.exceptions == []
    assert set(result.settlements["status"]) == {"no_payout_expected", "matched"}


def test_short_credit_without_utr_is_paired_not_split():
    report = _report([
        {"entity_id": "pay_1", "type": "payment", "amount": 5000.0, "settlement_id": "s1", "settlement_utr": "AXISN26245000001", "settled_at": date(2026, 9, 10)},
    ])
    bank = _bank([
        {"date": date(2026, 9, 1), "description": "OPENING", "amount": 1.0},
        {"date": date(2026, 9, 12), "description": "NEFT CR-RAZORPAY SOFTWARE PRIVATE LIM", "amount": 4500.0},
        {"date": date(2026, 9, 30), "description": "UPI", "amount": -5.0},
    ])
    kinds = [e.type for e in reconcile(report, bank).exceptions]
    assert kinds == ["short_credit"]


# ---------------------------------------------------------------- summary guard

def _result(month):
    out, _ = month
    return reconcile(load_report(out / "settlement_report.csv").df, load_bank(out / "bank_format_a.csv").df,
                     load_orders(out / "orders.csv").df)


def test_llm_summary_with_invented_number_falls_back(month):
    result = _result(month)
    text, used = llm_summary(result, FakeLLM("You lost Rs 98,765.43 this month."))
    assert not used and text == template_summary(result)


def test_llm_summary_with_real_numbers_is_kept(month):
    result = _result(month)
    s = result.stats
    reply = f"Rs {inr(s['at_risk_high'])} needs action. {s['settlements_matched']} payouts matched."
    text, used = llm_summary(result, FakeLLM(reply))
    assert used and text == reply
