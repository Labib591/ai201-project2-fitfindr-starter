"""
tests/test_tools.py

Per-tool tests, with at least one test for each tool's failure mode.

Run from the project root with:
    pytest tests/

The search_listings tests are pure (no network). The suggest_outfit and
create_fit_card tests that hit the LLM are marked `llm` and can be skipped
offline with:
    pytest tests/ -m "not llm"
"""

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # Failure mode: nothing matches → empty list, NOT an exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_filter():
    # "M" should match listings whose size contains M (e.g. "M", "M/L"),
    # and every returned listing must satisfy the size filter.
    results = search_listings("vintage", size="M", max_price=100)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    results = search_listings("graphic tee", size=None, max_price=100)
    assert len(results) > 1
    # Top result should reference a graphic/band tee in its tags or title.
    top = results[0]
    text = (top["title"] + " " + " ".join(top["style_tags"])).lower()
    assert "graphic" in text or "tee" in text


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

@pytest.mark.llm
def test_suggest_outfit_with_wardrobe():
    new_item = search_listings("graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(new_item, get_example_wardrobe())
    assert isinstance(result, str)
    assert len(result.strip()) > 0


@pytest.mark.llm
def test_suggest_outfit_empty_wardrobe():
    # Failure mode: empty wardrobe → still returns a non-empty string,
    # does not crash.
    new_item = search_listings("graphic tee", size=None, max_price=50)[0]
    result = suggest_outfit(new_item, get_empty_wardrobe())
    assert isinstance(result, str)
    assert len(result.strip()) > 0


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

@pytest.mark.llm
def test_create_fit_card_returns_text():
    new_item = search_listings("graphic tee", size=None, max_price=50)[0]
    card = create_fit_card("Pair it with baggy jeans and chunky sneakers.", new_item)
    assert isinstance(card, str)
    assert len(card.strip()) > 0


def test_create_fit_card_empty_outfit():
    # Failure mode: empty/whitespace outfit → guard returns an error string
    # WITHOUT calling the LLM (so this test needs no API key).
    new_item = {"title": "Faded Band Tee", "price": 22.0, "platform": "depop"}
    card = create_fit_card("   ", new_item)
    assert isinstance(card, str)
    assert "missing" in card.lower()


@pytest.mark.llm
def test_create_fit_card_varies():
    # Higher temperature should produce different captions across runs.
    new_item = search_listings("graphic tee", size=None, max_price=50)[0]
    outfit = "Pair it with baggy jeans and chunky sneakers."
    a = create_fit_card(outfit, new_item)
    b = create_fit_card(outfit, new_item)
    assert a != b
