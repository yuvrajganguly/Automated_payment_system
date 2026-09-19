"""The matcher behind every duplicate check (2026-09-19).

Three confusable-character typos reached live data in September 2026 and none
was noticed until a reconciliation weeks later: CBJCEVD0250 (J for I),
CBICEVDO286 (letter O for zero) and the rider id 67163_MN0W000471 (zero for
letter O). These are the checks that would have refused all three at the point
of entry.

The other half is names. Two men really are both called Bidhan Mondal, so the
tests below care as much about what does NOT match as about what does.
"""

from __future__ import annotations

import pytest

from payout.domain.duplicates import (
    EvIdProblem,
    check_ev_id,
    evidence,
    fold_id,
    identifiers,
    norm_account,
    norm_phone,
    same_name,
    same_person,
)

# The live fleet's shape: (ev_id, that model's id prefix).
FLEET = [
    ("CBICEVD0250", "CBICEVD"),
    ("CBICEVD0286", "CBICEVD"),
    ("KOL1234", "KOL"),
]


# ── EV ids ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ("bad", "because"),
    [
        ("CBJCEVD0250", "does not start with"),  # the real one, 12 Sep
        ("CBICEVDO286", "one character away"),  # the other real one, 12 Sep
        ("CBICEVD025O", "one character away"),  # zero typed as a letter
        ("CBICEVD02S0", "one character away"),  # S for 5
        ("KO11234", "does not start with"),  # L typed as ones
    ],
)
def test_a_confusable_character_is_refused_with_a_reason(bad, because):
    prefix = "KOL" if bad.upper().startswith(("KOL", "KO1")) else "CBICEVD"
    with pytest.raises(EvIdProblem) as e:
        check_ev_id(bad, prefix, FLEET)
    assert because in str(e.value)
    # The message has to name what it collided with, or a man in the field
    # cannot act on it.
    assert bad.upper() in str(e.value)


@pytest.mark.parametrize("good", ["CBICEVD0299", "CBICEVD9999", "CBICEVD0251"])
def test_a_genuinely_new_id_is_allowed(good):
    check_ev_id(good, "CBICEVD", FLEET)


def test_an_exact_repeat_is_left_to_the_unique_check():
    """ "already exists" is a different message from "looks like a typo", and
    claiming the second when the first is true would be a lie."""
    check_ev_id("CBICEVD0250", "CBICEVD", FLEET)


def test_no_prefix_configured_still_catches_the_confusables():
    """Raft Regular has no known prefix. That must not disable the check."""
    with pytest.raises(EvIdProblem):
        check_ev_id("CBICEVDO286", None, FLEET)


def test_a_blank_id_is_refused():
    with pytest.raises(EvIdProblem):
        check_ev_id("   ", "CBICEVD", FLEET)


def test_folding_leaves_the_prefix_letters_alone():
    """D and B fold to 0 and 8 in a tail, never in the prefix — otherwise
    every CBICEVD id would collide with every other one."""
    assert fold_id("CBICEVD0250").startswith("CB1CEVD")
    assert fold_id("CBICEVDD250", "CBICEVD") == fold_id("CBICEVD0250", "CBICEVD")


# ── names ────────────────────────────────────────────────────────────────────
def test_same_name_ignores_case_punctuation_and_order():
    assert same_name("BIDHAN MONDAL", "Bidhan Mondal")
    assert same_name("Ghosh, Susanta", "susanta ghosh")
    assert not same_name("Susanta Ghosh", "Sushanta Ghosh")  # drift is not sameness
    assert not same_name("", "Anyone")


def test_same_person_allows_drift_and_dropped_tokens():
    assert same_person("SUSANTA GHOSH", "Sushanta ghosh")
    assert same_person("Abhishek Tiwary", "Abhishek tiwari")
    assert same_person("Jeet", "Jeet Kumar Ghosh")


def test_same_person_does_not_match_on_a_shared_surname():
    """An earlier version carried a list of common surnames and matched on one
    alone, which made these two men the same man."""
    assert not same_person("Somnath Sardar", "MILON SARDAR")
    assert not same_person("Prosenjit A-1", "Prosenjit Das")
    assert not same_person("Akash Roy", "Biplab Halder")


# ── identifiers ──────────────────────────────────────────────────────────────
def test_phone_compares_by_last_ten_digits():
    assert norm_phone("+91 70036-64227") == norm_phone("07003664227")
    assert norm_phone("12345") == ""  # too short to be a phone number


def test_account_ignores_spacing_and_case():
    assert norm_account("47380100004378") == norm_account("4738 0100 004378")


def test_two_people_with_no_phone_do_not_share_one():
    """The bug this guards: empty strings kept as identifiers would make every
    half-filled record a duplicate of every other."""
    assert identifiers(phones=["", None], accounts=[""]) == set()
    assert identifiers(phones=["9000000001"]) == {("phone", "9000000001")}


def test_evidence_reads_as_a_sentence_fragment():
    shared = identifiers(phones=["9000000001"], aadhaar="1234 5678 9012")
    assert evidence(shared) == "aadhaar=123456789012, phone=9000000001"
