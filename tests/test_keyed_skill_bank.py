"""KeyedSkillBank rename (#821)."""
from examples._method_policy import KeyedSkillBank, SkillLibrary


def test_keyed_skill_bank_is_the_public_name():
    assert SkillLibrary is KeyedSkillBank

def test_keyed_skill_bank_rejects_unknown_key():
    bank = KeyedSkillBank(categories=["craft"], value_validator=lambda s: s.strip())
    d = bank.to_diff({}, "other: do thing", "w", 0, "a")
    assert d is None
    assert bank.invalid_proposals == 1
    d = bank.to_diff({}, "craft: mine wood", "w", 0, "a")
    assert d is not None and d.ops == {"craft": "mine wood"}
