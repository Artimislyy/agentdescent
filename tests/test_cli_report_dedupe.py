"""algorithms run must not print the same recipe tip twice (#848)."""

from agentdescent.cli import _print_init_report


def test_print_init_report_dedupes_identical_bodies(capsys):
    report = [
        ("warning", "use the OpenCode Coding recipe in docs/plugins.md"),
        ("note", "seeded library"),
        ("warning", "use the OpenCode Coding recipe in docs/plugins.md"),
        ("note", "seeded library"),
    ]
    printed = _print_init_report(report)
    out = capsys.readouterr().out
    assert out.count("use the OpenCode Coding recipe") == 1
    assert out.count("seeded library") == 1
    assert "use the OpenCode Coding recipe in docs/plugins.md" in printed


def test_build_parser_mentions_path_a():
    from agentdescent.cli import build_parser
    help_text = build_parser().format_help()
    assert "Path A" in help_text
