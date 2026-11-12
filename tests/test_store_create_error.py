"""An uncreatable run store is an input error, not a traceback (#907)."""

import errno
import json
import os

import pytest

from agentdescent import cli, runstore
from agentdescent.runstore import RunStoreError


def test_store_path_is_a_file(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(RunStoreError, match="not a directory"):
        runstore.create({"kind": "x"}, store=str(f))


def test_makedirs_oserror_becomes_runstore_error(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError(errno.EROFS, "Read-only file system")
    monkeypatch.setattr(runstore.os, "makedirs", boom)
    with pytest.raises(RunStoreError, match="Read-only file system") as ei:
        runstore.create({"kind": "x"}, store=str(tmp_path / "runs"))
    assert "cannot create run store" in str(ei.value)


def test_run_dir_oserror_becomes_runstore_error(tmp_path, monkeypatch):
    real = os.makedirs
    base = str(tmp_path / "runs")

    def picky(path, *a, **k):
        if os.path.abspath(path) != os.path.abspath(base):
            raise OSError(errno.ENOSPC, "No space left on device")
        return real(path, *a, **k)
    monkeypatch.setattr(runstore.os, "makedirs", picky)
    with pytest.raises(RunStoreError, match="cannot create run directory"):
        runstore.create({"kind": "x"}, store=base)


@pytest.mark.parametrize("json_flag", [False, True])
def test_demo_with_bad_store_exits_2(tmp_path, capsys, json_flag):
    f = tmp_path / "afile"
    f.write_text("x")
    argv = ["--store", str(f), "demo"] + (["--json"] if json_flag else [])
    rc = cli.main(argv)
    assert rc == 2
    out, err = capsys.readouterr()
    assert "Traceback" not in out + err
    if json_flag:
        doc = json.loads(out)
        assert doc["ok"] is False
        assert "cannot create run store" in doc["error"]
    else:
        lines = [ln for ln in err.splitlines() if ln.strip()]
        assert lines == [f"error: cannot create run store {f}: not a directory"]
