"""Unit tests for the deterministic Tier-1 checks (no network)."""

from veritas.checks import _banned_terms, _max_sentences


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
