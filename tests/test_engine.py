"""Reconciliation rules: each branch of matching and every exception check."""

from datetime import date

import pandas as pd

from conftest import make_bank, make_report
from recon.engine import Config, reconcile

D = lambda day, month=9: date(2026, month, day)  # noqa: E731
EDGES = [  # statement runs 1-30 Sep: an opening and a closing row pin the period
    {"date": D(1), "description": "OPENING", "amount": 1.0},
    {"date": D(30), "description": "UPI CHARGES", "amount": -1.0},
]


def payout(sid, amount, day, utr="AXISN26245000001", **extra):
    return {
        "entity_id": f"pay_{sid}",
        "type": "payment",
        "amount": amount,
        "settlement_id": sid,
        "settlement_utr": utr,
        "settled_at": D(day) if isinstance(day, int) else day,
        **extra,
    }


def bank(*rows):
    return make_bank(list(EDGES) + list(rows))


def test_exceptions_frame_and_to_dict():
    report = make_report([payout("s1", 1000.0, 10)])
    clean = reconcile(report, bank({"date": D(10), "description": "NEFT/AXISN26245000001/RAZORPAY", "amount": 1000.0}))
    assert clean.exceptions == [] and clean.exceptions_frame().empty
    assert list(clean.exceptions_frame().columns) == [
        "severity",
        "type",
        "key",
        "amount_at_risk",
        "title",
        "detail",
        "action",
    ]
    missing = reconcile(report, bank())
    frame = missing.exceptions_frame()
    assert frame.loc[0, "type"] == "missing_payout" and missing.exceptions[0].to_dict()["key"] == "s1"


def test_report_only_uses_last_payment_date_as_of():
    report = make_report(
        [
            payout("s1", 1000.0, 3, created_at=D(1)),
            {"entity_id": "pay_x", "type": "payment", "amount": 50.0, "settled": False, "created_at": D(20)},
        ]
    )
    result = reconcile(report)
    assert set(result.settlements["status"]) == {"no_bank_statement"}
    assert result.stats["as_of"] == "2026-09-20" and result.stats["statement_from"] is None
    assert result.stats["received_payouts"] == 0


def test_explicit_as_of_controls_unsettled_check():
    report = make_report(
        [{"entity_id": "pay_x", "type": "payment", "amount": 50.0, "settled": False, "created_at": D(10)}]
    )
    assert reconcile(report, as_of=D(11)).exceptions == []
    assert [e.type for e in reconcile(report, as_of=D(20)).exceptions] == ["unsettled_payment"]


def test_settlement_before_statement_is_ignored():
    result = reconcile(make_report([payout("s1", 1000.0, date(2026, 8, 20))]), bank())
    assert result.settlements.loc[0, "status"] == "before_statement" and result.exceptions == []


def test_settlement_without_utr_matches_on_amount_and_date():
    result = reconcile(
        make_report([payout("s1", 1000.0, 10, utr="")]),
        bank({"date": D(11), "description": "NEFT CR-RAZORPAY SOFTWARE PRIVATE LIM", "amount": 1000.0}),
    )
    assert result.settlements.loc[0, "match_method"] == "amount+date" and result.exceptions == []


def test_two_settlements_competing_for_one_credit():
    report = make_report(
        [payout("s1", 1000.0, 10, utr="AXISN26245000001"), payout("s2", 1010.0, 10, utr="AXISN26245000002")]
    )
    result = reconcile(
        report, bank({"date": D(11), "description": "NEFT CR-RAZORPAY SOFTWARE PRIVATE LIM", "amount": 900.0})
    )
    assert sorted((e.type, e.key) for e in result.exceptions) == [("missing_payout", "s2"), ("short_credit", "s1")]


def test_excess_credit_is_low_severity():
    result = reconcile(
        make_report([payout("s1", 1000.0, 10)]),
        bank({"date": D(10), "description": "NEFT/AXISN26245000001/RAZORPAY", "amount": 1100.0}),
    )
    (e,) = result.exceptions
    assert (e.type, e.severity, e.amount_at_risk) == ("excess_credit", "low", 100.0)


def test_missing_payout_near_statement_end_is_medium_with_caveat():
    (e,) = reconcile(make_report([payout("s1", 1000.0, 29)]), bank()).exceptions
    assert e.severity == "medium" and "next one" in e.detail


def test_unknown_credit_without_utr_uses_row_number():
    result = reconcile(
        make_report([payout("s0", 50.0, date(2026, 8, 1))]),  # only an old, out-of-period settlement
        bank({"date": D(12), "description": "NEFT CR-RAZORPAY SOFTWARE", "amount": 777.0}),
    )
    (e,) = result.exceptions
    assert e.type == "unknown_credit" and e.key == "bank-row-2"


def test_payment_checks_skip_zero_amounts_and_missing_dates():
    report = make_report(
        [
            {"entity_id": "pay_zero", "type": "payment", "amount": 0.0, "settled": False, "created_at": None},
            {
                "entity_id": "pay_free",
                "type": "payment",
                "amount": 100.0,
                "fee": 0.0,
                "settled": True,
                "settlement_id": "s1",
                "settlement_utr": "AXISN26245000001",
                "settled_at": D(3),
            },
        ]
    )
    assert reconcile(report, as_of=D(30)).exceptions == []


def test_rate_card_is_respected():
    report = make_report([payout("s1", 1000.0, 10, fee=30.0, tax=5.4, method="card")])
    credit = bank({"date": D(10), "description": "NEFT/AXISN26245000001/RAZORPAY", "amount": 964.6})
    assert [e.type for e in reconcile(report, credit).exceptions] == ["fee_anomaly"]
    assert reconcile(report, credit, cfg=Config(rate_card={"card": 3.0})).exceptions == []


def test_order_checks_pending_unknown_receipt_and_blank_receipt():
    report = make_report(
        [
            {
                "entity_id": "pay_a",
                "type": "payment",
                "amount": 500.0,
                "order_receipt": "GHOST-1",
                "settled": False,
                "created_at": D(29),
            },
            {
                "entity_id": "pay_b",
                "type": "payment",
                "amount": 200.0,
                "order_receipt": "",
                "settled": False,
                "created_at": D(29),
            },
        ]
    )
    orders = pd.DataFrame(
        [
            {
                "order_ref": "P-1",
                "amount": 300.0,
                "status": "pending",
                "status_raw": "awaiting",
                "created_at": D(5),
                "customer": "x",
            }
        ]
    )
    result = reconcile(report, orders=orders, as_of=D(30))
    assert [(e.type, e.key) for e in result.exceptions] == [("payment_without_order", "GHOST-1")]


def test_empty_orders_frame_skips_order_checks():
    report = make_report(
        [
            {
                "entity_id": "pay_a",
                "type": "payment",
                "amount": 500.0,
                "order_receipt": "X",
                "settled": False,
                "created_at": D(29),
            }
        ]
    )
    empty = pd.DataFrame(columns=["order_ref", "amount", "status", "status_raw", "created_at", "customer"])
    assert reconcile(report, orders=empty, as_of=D(30)).exceptions == []


def test_stats_count_issues_by_type():
    report = make_report([payout("s1", 1000.0, 10), payout("s2", 2000.0, 12, utr="AXISN26245000002")])
    stats = reconcile(report, bank()).stats
    assert stats["by_type"] == {"missing_payout": {"count": 2, "amount": 3000.0}}
    assert stats["at_risk_high"] == 3000.0 and stats["settlements_in_period"] == 2


def test_duplicate_charge_already_refunded_is_not_flagged():
    def pay(pid, receipt="FX1"):
        return {
            "entity_id": pid,
            "type": "payment",
            "amount": 500.0,
            "order_receipt": receipt,
            "settled": False,
            "created_at": D(29),
        }

    refund = {
        "entity_id": "rfnd_1",
        "type": "refund",
        "amount": 500.0,
        "order_receipt": "FX1",
        "settled": False,
        "created_at": D(29),
    }
    orders = pd.DataFrame(
        [
            {
                "order_ref": "FX1",
                "amount": 500.0,
                "status": "paid",
                "status_raw": "completed",
                "created_at": D(28),
                "customer": "x",
            }
        ]
    )
    charged_twice = make_report([pay("pay_1"), pay("pay_2")])
    assert [e.type for e in reconcile(charged_twice, orders=orders, as_of=D(30)).exceptions] == ["duplicate_payment"]
    refunded = make_report([pay("pay_1"), pay("pay_2"), refund])
    assert reconcile(refunded, orders=orders, as_of=D(30)).exceptions == []
