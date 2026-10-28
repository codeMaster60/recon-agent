"""The plain-English summary and the shared HTML pieces, case by case."""

from types import SimpleNamespace

import pandas as pd

from recon.engine import Exception_, Result
from recon.ingest import MappingResult
from recon.look import file_story_html, issues_html, tiles_html
from recon.report import template_summary


def issue(kind, severity, amount, key="k"):
    return Exception_(kind, severity, key, amount, f"title {kind}", f"detail {key}", f"action {kind}")


def result(exceptions, payouts=10, matched=8):
    stats = {
        "settlements_in_period": payouts,
        "settlements_matched": matched,
        "at_risk_high": round(sum(e.amount_at_risk for e in exceptions if e.severity == "high"), 2),
        "received_payouts": 1000.0,
        "fees": 20.0,
        "gst": 3.6,
    }
    return Result(exceptions, pd.DataFrame(), stats, [])


def test_one_kind_of_high_issue_is_named_directly():
    text = template_summary(result([issue("missing_payout", "high", 5000.0)]))
    assert (
        text
        == "8 of 10 payouts reached your bank exactly as expected. ₹5,000.00 needs a look now: a payout that never arrived."
    )


def test_biggest_kind_leads_when_it_is_most_of_the_money():
    text = template_summary(
        result(
            [
                issue("missing_payout", "high", 900.0),
                issue("missing_payout", "high", 100.0, "k2"),
                issue("duplicate_payment", "high", 50.0),
            ]
        )
    )
    assert "most of it from 2 payouts that never arrived (₹1,000.00)" in text


def test_biggest_kind_is_only_included_when_it_is_under_half():
    exceptions = [
        issue("missing_payout", "high", 40.0),
        issue("duplicate_payment", "high", 30.0),
        issue("order_without_payment", "high", 30.0),
    ]
    assert "including a payout that never arrived (₹40.00)" in template_summary(result(exceptions))


def test_no_high_issues_and_singular_smaller_thing():
    text = template_summary(result([issue("fee_anomaly", "medium", 12.0)]))
    assert text == "8 of 10 payouts reached your bank exactly as expected. There is 1 smaller thing below."


def test_only_high_issues_has_no_smaller_things_line():
    assert "smaller" not in template_summary(result([issue("short_credit", "high", 150.0)]))


def test_issue_groups_skip_empty_priorities_and_merge_same_kind():
    page = issues_html(
        [
            issue("missing_payout", "high", 10.0, "a"),
            issue("missing_payout", "high", 5.0, "b"),
            issue("gst_mismatch", "low", 1.0, "c"),
        ]
    )
    assert 'Act now<span class="rc-count">2</span>' in page and 'Good to know<span class="rc-count">1</span>' in page
    assert "Worth a check" not in page
    assert page.count('class="rc-card"') == 2 and page.count("<li>") == 2 and "2 cases" in page
    assert page.count("action missing_payout") == 1  # next step shown once per kind, not per case


def test_tiles_show_dash_when_nothing_to_match():
    html = tiles_html(result([], payouts=0, matched=0).stats)
    assert '<div class="v">–</div>' in html and "rc-stat alert" not in html


def test_file_story_partial_balance_and_notes():
    chosen = MappingResult(
        {"date": "Txn Date"}, "llm", 0.9, {"balance_continuity": 0.93}, ["debit/credit looked swapped"]
    )
    loaded = SimpleNamespace(chosen=chosen, header_row=2, df=pd.DataFrame({"a": range(40)}))
    page = file_story_html("Bank statement", loaded)
    assert "row 3 and read 40 rows" in page and "The AI step worked out the columns" in page
    assert "adds up on 93% of rows" in page and "Debit/credit looked swapped." in page
    assert "<td>Txn Date</td><td>Date</td>" in page
