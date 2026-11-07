"""A GSM8K fetch that fails everywhere names the next step (#870)."""
import pytest

from examples import _gsm8k_domain as gsm


def _boom_pyarrow(split):
    raise ModuleNotFoundError("No module named 'pyarrow'")


def _boom_http(split):
    raise OSError("HTTP Error 502: Bad Gateway")


def test_all_transports_failing_names_pyarrow_mirror_and_sample(monkeypatch, tmp_path):
    monkeypatch.delenv(gsm.SAMPLE_ENV, raising=False)
    monkeypatch.setattr(gsm, "_CACHE", {})
    monkeypatch.setattr(gsm, "_cache_file", lambda split: str(tmp_path / f"{split}.jsonl"))
    monkeypatch.setattr(gsm, "_from_parquet", _boom_pyarrow)
    monkeypatch.setattr(gsm, "_from_datasets_server", _boom_http)
    with pytest.raises(RuntimeError) as info:
        gsm.load_split("train")
    msg = str(info.value)
    assert "could not load GSM8K train" in msg
    assert "pip install pyarrow" in msg
    assert "HF_ENDPOINT" in msg
    assert f"{gsm.SAMPLE_ENV}=1" in msg


def test_hint_omits_pyarrow_when_it_was_not_the_cause():
    hint = gsm._load_hint(["_from_parquet: OSError: timed out"])
    assert "pyarrow" not in hint
    assert gsm.SAMPLE_ENV in hint
