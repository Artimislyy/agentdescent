"""Prediction log: declare an effect, observe it, and score the calibration."""

import json
import math

import pytest

from agentdescent import cli
from agentdescent.prediction import (
    PredictionError,
    PredictionLog,
    ProposalPrediction,
)


def _prediction(delta=0.1, confidence=0.8, tasks=("t1", "t2")):
    return ProposalPrediction(
        expected_delta=delta, confidence=confidence,
        expected_tasks=tasks, rationale="the rule covers both tasks")


def test_pending_observation_and_hit(tmp_path):
    log = PredictionLog(str(tmp_path / "pred.jsonl"))
    pid = log.predict("skill", "d1", _prediction())
    assert log.pending()[0].prediction_id == pid
    assert log.records()[0].hit is None

    record = log.observe(pid, observed_delta=0.09,
                         observed_tasks=("t1", "t2"), tolerance=0.02)
    assert record.pending is False
    assert record.hit is True
    assert record.delta_error == pytest.approx(-0.01)
    assert record.task_overlap == 1.0
    assert record.brier == pytest.approx((0.8 - 1.0) ** 2)


def test_miss_on_delta_or_tasks(tmp_path):
    log = PredictionLog(str(tmp_path / "pred.jsonl"))
    pid = log.predict("skill", "d1", _prediction())
    slow = log.observe(pid, observed_delta=0.3, observed_tasks=("t1", "t2"))
    assert slow.hit is False
    assert slow.brier == pytest.approx(0.8 ** 2)

    pid2 = log.predict("skill", "d2", _prediction())
    wrong_tasks = log.observe(pid2, observed_delta=0.1,
                              observed_tasks=("t1", "t9"))
    assert wrong_tasks.hit is False
    assert wrong_tasks.task_overlap == pytest.approx(1 / 3)


def test_report_counts_calibration_and_persistence(tmp_path):
    path = tmp_path / "pred.jsonl"
    log = PredictionLog(str(path))
    p1 = log.predict("a", "d1", _prediction(confidence=0.9))
    log.observe(p1, observed_delta=0.1, observed_tasks=("t1", "t2"))
    p2 = log.predict("a", "d2", _prediction(confidence=0.1))
    log.observe(p2, observed_delta=0.5, observed_tasks=("t1",))
    log.predict("b", "d3", _prediction())  # pending

    report = log.report()
    assert report["predictions"] == 3
    assert report["observed"] == 2
    assert report["pending"] == 1
    assert report["hit_rate"] == pytest.approx(0.5)
    assert report["falsified"] == 1
    assert report["mean_brier"] == pytest.approx(((0.9 - 1) ** 2 + 0.1 ** 2) / 2)
    assert report["calibration"]

    reloaded = PredictionLog(str(path))
    assert len(reloaded.records()) == 3
    assert reloaded.records()[0].hit is True


def test_bad_predictions_are_refused(tmp_path):
    log = PredictionLog(str(tmp_path / "pred.jsonl"))
    with pytest.raises(PredictionError):
        ProposalPrediction(0.1, 1.1)
    with pytest.raises(PredictionError):
        ProposalPrediction(float("nan"), 0.5)
    pid = log.predict("a", "d", _prediction(), prediction_id="same")
    with pytest.raises(PredictionError):
        log.predict("a", "d", _prediction(), prediction_id="same")
    with pytest.raises(PredictionError):
        log.observe("missing", observed_delta=0.1)
    log.observe(pid, observed_delta=0.1, observed_tasks=("t1", "t2"))
    with pytest.raises(PredictionError):
        log.observe(pid, observed_delta=0.1)
    with pytest.raises(PredictionError):
        log.observe(pid, observed_delta=0.1, tolerance=-1)


def test_cli_predict_observe_report(tmp_path, capsys):
    store = str(tmp_path / "pred.jsonl")
    assert cli.main([
        "predictions", "predict", "--store", store,
        "--artifact-id", "skill", "--diff-id", "d1",
        "--delta", "0.1", "--confidence", "0.8",
        "--tasks", "t1,t2", "--json"]) == 0
    predicted = json.loads(capsys.readouterr().out)
    pid = predicted["prediction_id"]
    assert predicted["pending"] is True

    assert cli.main([
        "predictions", "observe", "--store", store,
        "--prediction-id", pid, "--delta", "0.09",
        "--tasks", "t1,t2", "--tolerance", "0.02", "--json"]) == 0
    observed = json.loads(capsys.readouterr().out)
    assert observed["hit"] is True

    assert cli.main(["predictions", "report", "--store", store,
                     "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["observed"] == 1
    assert report["hit_rate"] == 1.0

    assert cli.main(["predictions", "observe", "--store", store,
                     "--prediction-id", "missing", "--delta", "0.1",
                     "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_malformed_lines_are_skipped(tmp_path):
    path = tmp_path / "pred.jsonl"
    path.write_text("not json\n", encoding="utf-8")
    log = PredictionLog(str(path))
    pid = log.predict("a", "d", _prediction())
    log.observe(pid, observed_delta=0.1, observed_tasks=("t1", "t2"))
    assert len(log.records()) == 1
    assert log.report()["observed"] == 1


def test_calibration_boundaries_are_counted_once(tmp_path):
    log = PredictionLog(str(tmp_path / "pred.jsonl"))
    for index, confidence in enumerate((0.2, 0.4, 0.6, 0.8, 1.0)):
        pid = log.predict("a", f"d{index}",
                          _prediction(confidence=confidence, tasks=()))
        log.observe(pid, observed_delta=0.1, observed_tasks=())
    report = log.report()
    assert report["observed"] == 5
    assert sum(row["count"] for row in report["calibration"]) == 5
    assert [row["count"] for row in report["calibration"]] == [1, 1, 1, 2]


def test_one_bad_row_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "pred.jsonl"
    path.write_text(json.dumps({
        "event": "prediction", "prediction_id": "bad",
        "artifact_id": "a", "diff_id": "d", "created_at": 1.0,
        "prediction": {"expected_delta": 0.1, "confidence": 5.0,
                       "expected_tasks": []},
    }) + "\n", encoding="utf-8")
    log = PredictionLog(str(path))
    pid = log.predict("a", "d", _prediction())
    log.observe(pid, observed_delta=0.1, observed_tasks=("t1", "t2"))
    report = log.report()
    assert report["observed"] == 1
    assert report["predictions"] == 1
    assert report["skipped"] == 1
