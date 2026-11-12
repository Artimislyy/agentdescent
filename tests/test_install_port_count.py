"""Keep the install guide's dry-run claim in sync with the port catalogue.

The catalogue in ``docs/self-evolution-examples.md`` is the record: every port is
one row under one ``###`` heading, and those headings are the group names. The
install FAQ states the same ports as a dry-run split (which ones touch no dataset,
which ones build a policy first), so the two pages can disagree while each looks
internally consistent -- that is how the FAQ came to say "the eight ... the
fourteen" (8 + 14 = 22) with Genesis in neither half.
"""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

# Every catalogue section, in page order. The heading is the group name the docs
# are allowed to use; a new port lands a row under one of these, never a new count
# written into prose somewhere else.
GROUPS = (
    "### The eight benchmark-faithful ports",
    "### The MethodPolicy microports and analogues",
    "### Added since: Dynamic Cheatsheet, the ACE precursor",
    "### Genesis, at the standard seams",
)

_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
    8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve",
    13: "thirteen", 14: "fourteen", 15: "fifteen", 16: "sixteen",
    17: "seventeen", 18: "eighteen", 19: "nineteen", 20: "twenty",
    21: "twenty-one", 22: "twenty-two", 23: "twenty-three",
}


def _section(catalogue: str, heading: str) -> str:
    """One catalogue section, from its heading up to the next ``###``."""
    start = catalogue.index(heading)
    following = re.search(r"^### ", catalogue[start + len(heading):], re.MULTILINE)
    end = start + len(heading) + following.start() if following else len(catalogue)
    return catalogue[start:end]


def _algorithm_rows(section: str) -> int:
    """Count named algorithm rows in one catalogue section."""
    return sum(line.startswith("| **") for line in section.splitlines())


def _group_sizes() -> dict[str, int]:
    """Every catalogue group, in page order, and how many ports it holds."""
    catalogue = (ROOT / "docs" / "self-evolution-examples.md").read_text()
    return {heading: _algorithm_rows(_section(catalogue, heading))
            for heading in GROUPS}


def _faq_paragraph() -> str:
    """The install FAQ paragraph that classifies the ports by dry-run behaviour."""
    install = (ROOT / "docs" / "install.md").read_text()
    at = install.index("algorithm ports print")
    # The paragraph is one long line on this page; take the line it sits on.
    start = install.rfind("\n", 0, at) + 1
    end = install.find("\n", at)
    return install[start:end if end != -1 else len(install)]


def test_install_guide_names_the_current_number_of_dry_run_ports():
    install = (ROOT / "docs" / "install.md").read_text()

    total = sum(_group_sizes().values())
    assert total == 23
    assert f"All {total} algorithm ports print" in install
    assert "All nineteen" not in install


def test_install_faq_split_reconciles_with_the_catalogue():
    """The FAQ names every catalogue group, and its counts cover all 23 ports.

    Genesis is the port that is easy to lose: its fidelity class is a
    mechanism microport, but its runner is a bespoke ``strategy=``, so it is in
    neither of the two obvious halves. Naming it is the difference between 22
    and 23, so the guard asks for the group names rather than for a total.
    """
    sizes = _group_sizes()
    paragraph = _faq_paragraph()
    total = sum(sizes.values())

    faithful = sizes["### The eight benchmark-faithful ports"]
    microports = sizes["### The MethodPolicy microports and analogues"]
    cheatsheet = sizes["### Added since: Dynamic Cheatsheet, the ACE precursor"]
    genesis = sizes["### Genesis, at the standard seams"]

    # Each group is named in the catalogue's own words, carrying its own count.
    # The page writes `MethodPolicy` as inline HTML, so compare one normalised
    # form: this is about which groups are named, not which markup renders them.
    lowered = paragraph.replace("<code>", "`").replace("</code>", "`").lower()
    assert f"{_WORDS[faithful]} benchmark-faithful ports" in lowered
    assert f"{_WORDS[microports]} `methodpolicy` microports" in lowered
    assert "dynamic cheatsheet" in lowered
    assert "genesis" in lowered

    # The four groups are the whole catalogue, so a FAQ naming all four has put
    # every port somewhere and cannot leave one in no group.
    assert faithful + microports + cheatsheet + genesis == total == 23

    # No catalogue group has fourteen ports. A "fourteen" here is the old
    # 8 + 14 = 22 split growing back: a count that matches no heading.
    assert "fourteen" not in paragraph, (
        "the FAQ states a group of fourteen ports; the catalogue groups are "
        f"{sorted(sizes.values())} -- name the groups, do not re-derive a total")
