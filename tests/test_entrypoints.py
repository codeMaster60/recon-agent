"""Everything a user actually runs: the CLI, the Streamlit app, the generator and the eval script."""

import json
import runpy
import sys

import pytest
from streamlit.testing.v1 import AppTest

import generate
import run_eval
from conftest import ROOT

SAMPLE_TRUTH = json.loads((ROOT / "data" / "samples" / "ground_truth.json").read_text())


def generate_truth():
    return {(t["type"], t["key"]) for t in SAMPLE_TRUTH}


SAMPLES = ROOT / "data" / "samples"
CLEAN_REPORT = (
    b"entity_id,type,amount,fee,tax,settled,settlement_id,settlement_utr,settled_at,created_at,method\n"
    b"pay_1,payment,1000,20,3.6,1,setl_1,AXISN26245000001,03/09/2026,01/09/2026,upi\n"
)
NO_BALANCE_BANK = (
    b"Date,Narration,Debit,Credit\n01/09/2026,OPENING,,1\n03/09/2026,NEFT/AXISN26245000001/RAZORPAY,,976.40\n"
)


def run_cli(monkeypatch, *args):
    monkeypatch.setattr(sys, "argv", ["recon", *map(str, args)])
    runpy.run_module("recon", run_name="__main__")


# ---------------------------------------------------------------- CLI


def test_cli_full_run_with_rate_card(monkeypatch, tmp_path, capsys):
    rates = tmp_path / "rates.json"
    rates.write_text('{"card": 2.0}')
    run_cli(
        monkeypatch,
        "--report",
        SAMPLES / "settlement_report.csv",
        "--bank",
        SAMPLES / "bank_format_b.xlsx",
        "--orders",
        SAMPLES / "orders.csv",
        "--out",
        tmp_path / "out",
        "--rate-card",
        rates,
        "--llm",
        "off",
    )
    summary = json.loads((tmp_path / "out" / "summary.json").read_text())
    assert summary["stats"]["exceptions"] == 22 and summary["llm_summary"] is False
    report_html = (tmp_path / "out" / "report.html").read_text()
    assert all(key in report_html for _, key in generate_truth()) and "Act now · 14" in report_html
    assert len((tmp_path / "out" / "exceptions.csv").read_text().splitlines()) == 23
    assert "wrote" in capsys.readouterr().out


def test_cli_report_only_auto_mode_without_key(monkeypatch, tmp_path, capsys):
    run_cli(monkeypatch, "--report", SAMPLES / "settlement_report.csv", "--out", tmp_path)
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert (
        lines[0].startswith("report ")
        and not any(line.startswith(("bank ", "orders ")) for line in lines)
        and (tmp_path / "report.html").exists()
    )


def test_cli_mapping_error_exits_with_message(monkeypatch, tmp_path):
    with pytest.raises(SystemExit, match="error: Could not map"):
        run_cli(
            monkeypatch,
            "--report",
            SAMPLES / "settlement_report.csv",
            "--bank",
            SAMPLES / "bank_format_d.csv",
            "--out",
            tmp_path,
            "--llm",
            "off",
        )


def test_cli_with_llm_maps_hindi_and_writes_ai_summary(monkeypatch, tmp_path, llm_server):
    run_cli(
        monkeypatch,
        "--report",
        SAMPLES / "settlement_report.csv",
        "--bank",
        SAMPLES / "bank_format_d.csv",
        "--out",
        tmp_path,
        "--llm",
        "on",
    )
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["llm_summary"] is True and summary["summary"].endswith("needs action now.")


# ---------------------------------------------------------------- Streamlit app


def app():
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)


def page(at) -> str:
    """Everything the app wrote as HTML, joined, so tests can check what a visitor reads."""
    return "\n".join(m.value for m in at.markdown)


def load_sample(at, bank=None):
    at.button[0].click().run()
    if bank:
        at.radio[0].set_value(bank).run()
    return at


HINDI = "Bank D · Hindi column names (needs the AI step)"


def test_app_landing_page():
    at = app().run()
    html = page(at)
    assert not at.exception
    assert "Did every payout land?" in html and "Results show up here" in html
    assert "AI step off in this demo" in html and "How it works" in html
    assert at.button[0].label == "No files handy? Load a sample month"


def test_app_sample_month_shows_every_issue_and_takes_feedback(capsys, month):
    at = load_sample(app().run())
    html = page(at)
    assert not at.exception
    assert "Needs a look now" in html and "Act now · 14" in html and "Worth a check · 5" in html
    truth = {k for _, k in generate_truth()}
    assert all(key in html for key in truth)
    assert "2 payouts that never arrived" in html
    assert len(at.download_button) == 2 and "How your files were read" in html
    feedback = next(r for r in at.radio if r.label.startswith("Did this catch"))
    feedback.set_value("Yes").run()
    assert "Thanks, noted." in page(at) and "FEEDBACK" in capsys.readouterr().out


def test_app_every_sample_bank_format_reads(month):
    at = app().run()
    at.button[0].click().run()
    for label in ("Bank B · Excel download", "Bank C · one amount column marked Cr or Dr"):
        at.radio[0].set_value(label).run()
        assert not at.exception and "Act now · 14" in page(at)


def test_app_hindi_sample_without_ai_explains_instead_of_erroring():
    at = load_sample(app().run(), HINDI)
    html = page(at)
    assert not at.exception and not at.error
    assert "read the bank statement." in html and "switched off in this public demo" in html
    assert "Could not map" in at.code[0].value  # raw detail kept behind "Technical details"


def test_app_reads_key_from_secrets_and_uses_ai(llm_server, monkeypatch):
    monkeypatch.delenv("RECON_LLM_API_KEY")  # the key must come from Streamlit secrets
    at = app()
    at.secrets["GROQ_API_KEY"] = "from-secrets"
    at.run()
    html = page(load_sample(at, HINDI))
    assert "Summary written by the AI step" in html and "The AI step worked out the columns" in html
    assert llm_server.requests[-1]["headers"]["Authorization"] == "Bearer from-secrets"


def test_app_env_key_wins_over_secrets(llm_server, monkeypatch):
    import os

    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    monkeypatch.delenv("RECON_LLM_API_KEY")
    at = app()
    at.secrets["GROQ_API_KEY"] = "from-secrets"
    at.run()
    assert "AI step on · fake-model" in page(at) and os.environ["GROQ_API_KEY"] == "from-env"


def test_app_ai_cannot_read_file_either(llm_server):
    at = app().run()
    at.file_uploader[0].set_value(("report.csv", CLEAN_REPORT, "text/csv"))
    at.file_uploader[1].set_value(("bank.csv", b"Foo,Bar,Baz\nx,y,12\n", "text/csv"))
    at.run()
    assert "couldn't make sense of it either" in page(at)


def test_app_empty_export_and_wrong_file_messages():
    at = app().run()
    at.file_uploader[0].set_value(("report.csv", b"entity_id,type,amount,settlement_id\n", "text/csv")).run()
    assert "no rows under them" in page(at)
    at.file_uploader[0].set_value(("notes.csv", b"just a note\n", "text/csv")).run()
    assert "couldn't find a row of column names" in page(at)


def test_app_uploaded_files_override_sample_and_handle_no_issues():
    at = app().run()
    at.button[0].click().run()  # sample mode on, then the user uploads their own files
    at.file_uploader[0].set_value(("report.csv", CLEAN_REPORT, "text/csv"))
    at.file_uploader[1].set_value(("bank.csv", NO_BALANCE_BANK, "text/csv"))
    at.run()
    html = page(at)
    assert not at.exception
    assert "Nothing to fix." in html and "The one payout in this statement reached your bank" in html
    assert "could not be cross-checked" in html
    assert at.download_button[1].proto.disabled  # nothing to put in the CSV


def test_app_report_only_upload():
    at = app().run()
    at.file_uploader[0].set_value(("report.csv", CLEAN_REPORT, "text/csv")).run()
    html = page(at)
    assert not at.exception and "Add the bank statement for the same dates" in html
    assert '<div class="rc-v">–</div>' in html  # payouts matched: nothing to match yet


# ---------------------------------------------------------------- generator


def test_generator_cli_writes_every_file(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(sys, "argv", ["generate.py", "--seed", "3", "--out", str(tmp_path), "--hard"])
    runpy.run_path(str(ROOT / "data" / "generate.py"), run_name="__main__")
    names = {p.name for p in tmp_path.iterdir()}
    assert names == {
        "settlement_report.csv",
        "orders.csv",
        "bank_format_a.csv",
        "bank_format_b.xlsx",
        "bank_format_c.csv",
        "bank_format_d.csv",
        "ground_truth.json",
    }
    assert "22 injected problems" in capsys.readouterr().out


def test_hard_mode_drops_payouts_posted_after_month_end():
    def payouts(d):
        return sum(t["kind"] == "payout" for t in d["bank"])

    assert any(payouts(generate.build(s, hard=True)) < payouts(generate.build(s)) for s in range(1, 15))


def test_generator_is_deterministic():
    assert generate.build(5) == generate.build(5)


# ---------------------------------------------------------------- evaluation script


def test_eval_clean_has_no_false_alarms_and_layout_d_needs_ai():
    res = run_eval.run(2, ["a", "d"], use_llm=False)
    assert res["mapping"]["d"]["fail"] == 2 and res["mapping"]["a"]["ok"] == 2
    md = run_eval.to_markdown(res)
    assert "| **all** | **44** | **44** | **0** |" in md and "False alarm examples" not in md


def test_eval_hard_reports_false_alarms():
    md = run_eval.to_markdown(run_eval.run(3, ["a"], use_llm=False, hard=True))  # seed 3 has a known false alarm
    assert "False alarm examples" in md and "hard (posting lag" in md


def test_eval_llm_path_maps_layout_d(llm_server):
    res = run_eval.run(1, ["d"], use_llm=True)
    assert res["mode"] == "llm" and dict(res["mapping"]["d"]["source"]) == {"llm": 1}


def test_eval_script_main_writes_results(monkeypatch, tmp_path, capsys):
    target = tmp_path / "r.md"
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--seeds", "1", "--layouts", "a", "--write", str(target)])
    runpy.run_path(str(ROOT / "eval" / "run_eval.py"), run_name="__main__")
    assert target.read_text().startswith("# Evaluation results")
    monkeypatch.setattr(sys, "argv", ["run_eval.py", "--seeds", "1", "--layouts", "a"])
    run_eval.main()
    assert "Exception detection" in capsys.readouterr().out


def test_cli_module_can_be_imported_without_running():
    import importlib

    module = importlib.import_module("recon.__main__")
    assert callable(module.main)
