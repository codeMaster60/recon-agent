"""Everything a user actually runs: the CLI, the Streamlit app, the generator and the eval script."""

import json
import runpy
import sys

import pytest
from streamlit.testing.v1 import AppTest

import generate
import run_eval
from conftest import ROOT

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
    assert (tmp_path / "out" / "report.html").read_text().count("<tr class=") == 22
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


def test_app_landing_page():
    at = app().run()
    assert not at.exception and "Start with the settlement report" in at.info[0].value
    assert "rules only" in at.sidebar.markdown[0].value


def test_app_sample_data_flow_and_feedback(capsys):
    at = app().run()
    at.button[0].click().run()
    assert not at.exception and not at.error
    assert [m.label for m in at.metric] == [
        "Needs action now",
        "Payouts matched",
        "Expected payouts",
        "Received in bank",
    ]
    assert at.dataframe[0].value.shape == (22, 7) and len(at.download_button) == 2
    feedback = next(r for r in at.radio if r.label.startswith("Found something"))
    feedback.set_value("Yes").run()
    assert at.success[0].value == "Thanks - noted." and "FEEDBACK" in capsys.readouterr().out


def test_app_hindi_sample_without_ai_shows_error():
    at = app().run()
    at.button[0].click().run()
    at.radio[0].set_value("d (Hindi headers - needs AI)").run()
    assert "Could not map" in at.error[0].value


def test_app_reads_key_from_secrets_and_uses_ai(llm_server, monkeypatch):
    monkeypatch.delenv("RECON_LLM_API_KEY")  # the key must come from Streamlit secrets
    at = app()
    at.secrets["GROQ_API_KEY"] = "from-secrets"
    at.run()
    at.button[0].click().run()
    at.radio[0].set_value("d (Hindi headers - needs AI)").run()
    assert not at.error and any("AI-written" in h.value for h in at.subheader)
    assert llm_server.requests[-1]["headers"]["Authorization"] == "Bearer from-secrets"


def test_app_env_key_wins_over_secrets(llm_server, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "from-env")
    monkeypatch.delenv("RECON_LLM_API_KEY")
    at = app()
    at.secrets["GROQ_API_KEY"] = "from-secrets"
    at.run()
    assert "fake-model" in at.sidebar.markdown[0].value
    import os

    assert os.environ["GROQ_API_KEY"] == "from-env"


def test_app_uploaded_files_override_sample_and_handle_no_issues():
    at = app().run()
    at.button[0].click().run()  # sample mode on, then the user uploads their own files
    at.file_uploader[0].set_value(("report.csv", CLEAN_REPORT, "text/csv"))
    at.file_uploader[1].set_value(("bank.csv", NO_BALANCE_BANK, "text/csv"))
    at.run()
    assert not at.exception and not at.error
    assert at.subheader[1].value == "Issues (0)" and not at.dataframe
    assert any("could not be cross-checked" in c.value for c in at.caption)


def test_app_report_only_upload():
    at = app().run()
    at.file_uploader[0].set_value(("report.csv", CLEAN_REPORT, "text/csv")).run()
    assert not at.exception and at.metric[1].value == "0 / 0"


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
