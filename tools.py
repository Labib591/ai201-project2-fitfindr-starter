"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # 1. Filter by price ceiling and size (when provided).
    candidates = []
    for item in listings:
        if max_price is not None and item["price"] > max_price:
            continue
        if size is not None and size.strip().lower() not in item["size"].lower():
            continue
        candidates.append(item)

    # 2. Score remaining listings by keyword overlap with the description.
    #    Keywords are matched against the title, description, and style_tags.
    stop_words = {"a", "an", "the", "and", "or", "for", "of", "in", "to", "with"}
    keywords = [
        word
        for word in "".join(
            c if c.isalnum() or c.isspace() else " " for c in description.lower()
        ).split()
        if word not in stop_words and len(word) > 1
    ]

    scored = []
    for item in candidates:
        searchable = " ".join(
            [item["title"], item["description"], " ".join(item["style_tags"])]
        ).lower()
        score = sum(1 for word in keywords if word in searchable)
        # Bonus when the full description phrase appears verbatim (strong match).
        if description.strip().lower() in searchable:
            score += 2
        if score > 0:
            scored.append((score, item))

    # 3. Sort by score (highest first) and return only the listing dicts.
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_summary = (
        f"{new_item['title']} "
        f"(style: {', '.join(new_item.get('style_tags', []))}; "
        f"colors: {', '.join(new_item.get('colors', []))}; "
        f"condition: {new_item.get('condition', 'unknown')})"
    )

    items = wardrobe.get("items", []) if wardrobe else []

    if not items:
        # Empty wardrobe: ask for general styling advice, not named pieces.
        user_prompt = (
            f"A user is considering buying this secondhand item:\n{item_summary}\n\n"
            "They have not entered any wardrobe yet. Suggest one or two complete "
            "outfit ideas in general terms — what kinds of pieces (bottoms, shoes, "
            "layers) pair well with it and what overall vibe it suits. Do not invent "
            "specific items they own. Keep it to 2-4 sentences, practical and concrete."
        )
    else:
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it['category']}; "
            f"{', '.join(it.get('style_tags', []))})"
            for it in items
        )
        user_prompt = (
            f"A user is considering buying this secondhand item:\n{item_summary}\n\n"
            f"Here is their current wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest one or two complete outfit combinations that pair the new item "
            "with specific pieces from their wardrobe (refer to the pieces by name). "
            "Include a small styling tip (tuck, roll, layer). Keep it to 2-4 sentences."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a thoughtful secondhand-fashion stylist. You give "
                        "concise, wearable outfit suggestions."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return (
            "Could not generate outfit suggestions right now. Try describing your "
            "wardrobe manually or retry the request."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard against an empty or whitespace-only outfit string.
    if not outfit or not outfit.strip():
        return (
            "Outfit details are missing — cannot generate a fit card without a "
            "complete look."
        )

    title = new_item.get("title", "this piece")
    price = new_item.get("price", "?")
    platform = new_item.get("platform", "secondhand")

    user_prompt = (
        f"Write a short, shareable Instagram/TikTok caption for this thrifted look.\n\n"
        f"Item: {title}\n"
        f"Price: ${price}\n"
        f"Platform: {platform}\n"
        f"Outfit: {outfit}\n\n"
        "Rules:\n"
        "- 2 to 4 sentences, casual and authentic like a real OOTD post (not a "
        "product description).\n"
        "- Mention the item name, the price, and the platform naturally, once each.\n"
        "- Capture the outfit vibe in specific terms.\n"
        "- Lowercase-heavy, conversational, a little personality. An emoji or two is "
        "fine. Return only the caption."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You write casual, authentic outfit-of-the-day captions for "
                        "thrifted finds."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.9,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return (
            f"Could not generate a fit card right now. Here's the item: {title} for "
            f"${price} on {platform}."
        )
