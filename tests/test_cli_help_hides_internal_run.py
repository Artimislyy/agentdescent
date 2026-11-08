"""``agentdescent --help`` must not show the internal ``run`` worker (#420).

``run --run-dir <dir>`` is what ``evolve --detach`` spawns. It was registered
with ``help=argparse.SUPPRESS``, which argparse does not honour for a
sub-parser: ``--help`` printed ``run  ==SUPPRESS==`` and every usage line
(printed on any argparse error) listed ``run`` next to ``evolve``.
"""

import os
import re
import subprocess
import sys

import pytest

from agentdescent import cli, runstore

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _verbs_in_braces(text):
    """The ``{a,b,c}`` sub-command list argparse prints, as a list."""
    m = re.search(r"\{([a-z_,-]+)\}", text)
    assert m, text
    return m.group(1).split(",")


def _subparsers_action():
    return next(a for a in cli.build_parser()._actions if a.dest == "cmd")


def test_help_has_no_suppress_placeholder():
    text = cli.build_parser().format_help()
    assert "SUPPRESS" not in text
    assert not re.search(r"^\s+run\s", text, re.M), text


def test_help_and_usage_do_not_list_run():
    parser = cli.build_parser()
    for text in (parser.format_help(), parser.format_usage()):
        verbs = _verbs_in_braces(text)
        assert "run" not in verbs
        assert "evolve" in verbs


def test_every_public_verb_is_still_listed_in_order():
    verbs = _verbs_in_braces(cli.build_parser().format_usage())
    public = [n for n in _subparsers_action().choices if n != "run"]
    assert verbs == public


def test_every_listed_verb_has_a_help_line():
    text = cli.build_parser().format_help()
    for verb in _verbs_in_braces(text):
        assert re.search(rf"^    {re.escape(verb)}\s+\S", text, re.M), verb


def test_the_usage_on_an_error_does_not_list_run(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main([])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "run" not in _verbs_in_braces(err)
    assert "SUPPRESS" not in err


def test_help_as_a_subprocess_has_no_placeholder():
    proc = subprocess.run([sys.executable, "-m", "agentdescent.cli", "--help"],
                          capture_output=True, text=True, cwd=ROOT)
    assert proc.returncode == 0
    assert "SUPPRESS" not in proc.stdout
    assert "run" not in _verbs_in_braces(proc.stdout)


def test_the_detached_worker_verb_still_parses():
    a = cli.build_parser().parse_args(["run", "--run-dir", "/tmp/x", "--budget", "1.5"])
    assert a.fn is cli.cmd_run
    assert a.run_dir == "/tmp/x" and a.budget == 1.5


def test_run_help_says_it_is_internal(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["run", "--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "internal" in out and "evolve" in out


def test_runstore_still_spawns_the_run_verb():
    # The detached worker's command line is what keeps `run` alive.
    src = open(runstore.__file__, encoding="utf-8").read()
    assert '"agentdescent.cli", "run", "--run-dir"' in src

def _unknown_verb(capsys, argv):
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == 2
    return capsys.readouterr()


def test_unknown_verb_error_does_not_list_run(capsys):
    """A typo must not advertise the internal ``run`` worker (#886)."""
    out, err = _unknown_verb(capsys, ["algoritms"])
    assert out == ""
    assert "'run'" not in err
    assert "invalid choice: 'algoritms'" in err
    assert "did you mean 'algorithms'?" in err


@pytest.mark.parametrize("verb", ["compile_skill", "COMPILE-SKILL"])
def test_unknown_verb_suggests_hyphen_or_case_fold(capsys, verb):
    _, err = _unknown_verb(capsys, [verb])
    assert "did you mean 'compile-skill'?" in err
    assert "'run'" not in err


def test_unknown_verb_json_hides_run_and_suggests(capsys):
    import json

    out, err = _unknown_verb(capsys, ["--json", "algoritms"])
    assert err == ""
    payload = json.loads(out)
    assert payload["ok"] is False
    assert "did you mean 'algorithms'?" in payload["error"]
    assert "'run'" not in payload["error"]
    assert "'run'" not in payload["usage"]


def test_nonsense_verb_has_no_guess_and_hides_run(capsys):
    _, err = _unknown_verb(capsys, ["no-such-verb"])
    assert "invalid choice: 'no-such-verb'" in err
    assert "did you mean" not in err
    assert "'run'" not in err
