"""Unit tests for the deterministic Tier-1 checks (no network)."""

from veritas.checks import (
    _banned_terms, _max_sentences, _reading_level, _required_terms, _z3_constraint,
)


def test_banned_terms_catches_hit():
    v = _banned_terms("This bottle is cheap and the best ever.", ["cheap", "best ever"])
    assert not v.passed
    assert "cheap" in v.reason and "best ever" in v.reason


def test_banned_terms_clean():
    v = _banned_terms("Premium, durable, built for the trail.", ["cheap", "#1"])
    assert v.passed and v.score == 1.0


def test_banned_terms_word_boundary():
    # 'cheap' must not match inside 'cheaply-made-sounding' style substrings of other words
    v = _banned_terms("A cheapskate joke", ["cheap"])
    assert v.passed  # 'cheapskate' is not the word 'cheap'


def test_max_sentences_over_limit():
    copy = "Headline line\nOne. Two. Three. Four. Five."
    v = _max_sentences(copy, 2)
    assert not v.passed


def test_max_sentences_within_limit():
    copy = "Headline line\nOne sentence here. Two sentences here."
    v = _max_sentences(copy, 2)
    assert v.passed


def test_reading_level_simple_passes():
    v = _reading_level("The cat sat on the mat. The dog ran fast.", 60)
    assert v.passed


def test_reading_level_dense_fails():
    hard = ("Notwithstanding the aforementioned complexities, the utilization of "
            "multisyllabic terminology substantially diminishes comprehensibility.")
    v = _reading_level(hard, 60)
    assert not v.passed


def test_required_terms_missing_any():
    v = _required_terms("Buy now and feel great", all_terms=[], any_terms=["consult", "doctor"])
    assert not v.passed


def test_required_terms_present():
    v = _required_terms("Please consult your doctor first.", all_terms=[], any_terms=["consult"])
    assert v.passed


def test_required_terms_missing_all():
    v = _required_terms("No disclaimer here", all_terms=["not a substitute"], any_terms=[])
    assert not v.passed


_EXTRACT = {"capacity_ml": r"(\d+)\s*ml", "price_usd": r"\$(\d+)"}


def test_z3_formally_passes():
    v = _z3_constraint("A 750 ml steel bottle for $29.", _EXTRACT,
                       ["capacity_ml == 750", "price_usd == 29"])
    assert v.passed


def test_z3_proves_violation():
    v = _z3_constraint("A 500 ml steel bottle.", {"capacity_ml": r"(\d+)\s*ml"},
                       ["capacity_ml == 750"])
    assert not v.passed
    assert "500" in v.reason or "disproved" in v.reason.lower()


def test_z3_no_numbers_passes():
    v = _z3_constraint("A lovely durable bottle.", {"capacity_ml": r"(\d+)\s*ml"},
                       ["capacity_ml == 750"])
    assert v.passed  # nothing numeric to verify is not a violation
