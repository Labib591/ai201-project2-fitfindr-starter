"""
agent.py

The FitFindr planning loop. Orchestrates the three tools in response to a
natural language user query, passing state between them via a session dict.

Complete tools.py and test each tool in isolation before implementing this file.

Usage (once implemented):
    from agent import run_agent
    from utils.data_loader import get_example_wardrobe

    result = run_agent(
        query="vintage graphic tee under $30, size M",
        wardrobe=get_example_wardrobe(),
    )
    print(result["fit_card"])
    print(result["error"])   # None on success
"""

import json
import re

from tools import search_listings, suggest_outfit, create_fit_card, _get_groq_client


# ── query parsing ─────────────────────────────────────────────────────────────

def _parse_query(query: str) -> dict:
    """
    Extract a description, optional size, and optional max_price from the raw
    user query using the LLM. Returns a dict:

        {"description": str, "size": str | None, "max_price": float | None}

    If the LLM call fails or returns unparseable output, falls back to using the
    whole query as the description with no size or price filter — the agent can
    still run a broad search rather than crashing.
    """
    fallback = {"description": query.strip(), "size": None, "max_price": None}

    prompt = (
        "Extract structured search parameters from this secondhand-clothing query. "
        'Respond with ONLY a JSON object of the form '
        '{"description": string, "size": string or null, "max_price": number or null}.\n'
        "- description: the item keywords only (drop size/price/wardrobe chatter).\n"
        "- size: a size like \"M\", \"US 8\", \"W30\" if stated, else null.\n"
        "- max_price: the numeric price ceiling if stated (e.g. 'under $30' -> 30), "
        "else null.\n\n"
        f"Query: {query}"
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system",
                    "content": "You extract structured data and reply with JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        raw = response.choices[0].message.content.strip()

        # The model may wrap JSON in code fences or prose — extract the object.
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return fallback
        parsed = json.loads(match.group(0))

        description = parsed.get("description") or query.strip()
        size = parsed.get("size") or None
        max_price = parsed.get("max_price")
        max_price = float(max_price) if max_price is not None else None

        return {"description": description, "size": size, "max_price": max_price}
    except Exception:
        return fallback


# ── session state ─────────────────────────────────────────────────────────────

def _new_session(query: str, wardrobe: dict) -> dict:
    """
    Initialize and return a fresh session dict for one user interaction.

    The session dict is the single source of truth for everything that happens
    during a run — it stores the original query, parsed parameters, tool results,
    and any error that caused early termination.

    You may add fields to this dict as needed for your implementation.
    """
    return {
        "query": query,              # original user query
        "parsed": {},                # extracted description / size / max_price
        "search_results": [],        # list of matching listing dicts
        "selected_item": None,       # top result, passed into suggest_outfit
        "wardrobe": wardrobe,        # user's wardrobe dict
        "outfit_suggestion": None,   # string returned by suggest_outfit
        "fit_card": None,            # string returned by create_fit_card
        "error": None,               # set if the interaction ended early
        "trace": [],                 # human-readable log of each planning step
    }


def _log(session: dict, line: str) -> None:
    """Append a line to the session trace (used to make state flow visible)."""
    session["trace"].append(line)


# ── planning loop ─────────────────────────────────────────────────────────────

def run_agent(query: str, wardrobe: dict) -> dict:
    """
    Main agent entry point. Runs the FitFindr planning loop for a single
    user interaction and returns the completed session dict.

    Args:
        query:    Natural language user request
                  (e.g., "vintage graphic tee under $30, size M")
        wardrobe: User's wardrobe dict — use get_example_wardrobe() or
                  get_empty_wardrobe() from utils/data_loader.py

    Returns:
        The session dict after the interaction completes. Check session["error"]
        first — if it is not None, the interaction ended early and the other
        output fields (outfit_suggestion, fit_card) will be None.

    TODO — implement this function using the planning loop you designed in planning.md:

        Step 1: Initialize the session with _new_session().

        Step 2: Parse the user's query to extract a description, size, and
                max_price. You can use regex, string splitting, or ask the LLM
                to parse it — document your choice in planning.md.
                Store the result in session["parsed"].

        Step 3: Call search_listings() with the parsed parameters.
                Store results in session["search_results"].
                If no results: set session["error"] to a helpful message and
                return the session early. Do NOT proceed to suggest_outfit
                with empty input.

        Step 4: Select the item to use (e.g., the top result).
                Store it in session["selected_item"].

        Step 5: Call suggest_outfit() with the selected item and wardrobe.
                Store the result in session["outfit_suggestion"].

        Step 6: Call create_fit_card() with the outfit suggestion and selected item.
                Store the result in session["fit_card"].

        Step 7: Return the session.

    Before writing code, complete the Planning Loop and State Management sections
    of planning.md — your implementation should match what you described there.
    """
    # Step 1: Initialize the session.
    session = _new_session(query, wardrobe)
    n_wardrobe = len(session["wardrobe"].get("items", []))
    _log(session, f'STEP 1 · Parse query\n  input : user query = "{query}"')

    # Step 2: Parse the query into description / size / max_price.
    session["parsed"] = _parse_query(query)
    parsed = session["parsed"]
    _log(
        session,
        "  tool  : _parse_query(query)\n"
        f"  WRITE state['parsed'] = description='{parsed['description']}', "
        f"size={parsed['size']!r}, max_price={parsed['max_price']!r}",
    )

    # Step 3: Search listings with the parsed parameters.
    _log(
        session,
        "\nSTEP 2 · Search listings\n"
        "  READ  state['parsed']  (from Step 1)\n"
        f"  tool  : search_listings(description='{parsed['description']}', "
        f"size={parsed['size']!r}, max_price={parsed['max_price']!r})",
    )
    session["search_results"] = search_listings(
        description=parsed["description"],
        size=parsed["size"],
        max_price=parsed["max_price"],
    )

    # Step 3 (branch): empty results → set error and return early.
    # Do NOT call suggest_outfit or create_fit_card with no item.
    if not session["search_results"]:
        size_txt = parsed["size"] if parsed["size"] else "any size"
        price_txt = f"${parsed['max_price']:.2f}" if parsed["max_price"] is not None else "any price"
        session["error"] = (
            f"No listings found for '{parsed['description']}' in {size_txt} under "
            f"{price_txt}. Try broadening your search — remove the size filter, "
            f"increase your budget, or use more general keywords."
        )
        _log(
            session,
            "  WRITE state['search_results'] = []  (0 matches)\n"
            "  BRANCH: empty results → set state['error'] and RETURN early.\n"
            "          suggest_outfit / create_fit_card are NOT called.",
        )
        return session

    _log(
        session,
        f"  WRITE state['search_results'] = {len(session['search_results'])} matches",
    )

    # Step 4: Select the top-scored result.
    session["selected_item"] = session["search_results"][0]
    item = session["selected_item"]
    _log(
        session,
        "\nSTEP 3 · Select top result\n"
        f"  WRITE state['selected_item'] = '{item['title']}' "
        f"(${item['price']}, {item['platform']})",
    )

    # Step 5: Suggest an outfit using the selected item and the wardrobe.
    _log(
        session,
        "\nSTEP 4 · Suggest outfit\n"
        "  READ  state['selected_item']  (the SAME item from Step 3 — no re-entry)\n"
        f"  tool  : suggest_outfit(new_item='{item['title']}', "
        f"wardrobe={n_wardrobe} items)",
    )
    session["outfit_suggestion"] = suggest_outfit(
        session["selected_item"], session["wardrobe"]
    )
    _log(session, "  WRITE state['outfit_suggestion'] = <outfit text>")

    # Step 6: Generate the shareable fit card from the outfit + selected item.
    _log(
        session,
        "\nSTEP 5 · Create fit card\n"
        "  READ  state['outfit_suggestion'] (Step 4) + state['selected_item'] (Step 3)\n"
        f"  tool  : create_fit_card(outfit=<Step 4 text>, new_item='{item['title']}')",
    )
    session["fit_card"] = create_fit_card(
        session["outfit_suggestion"], session["selected_item"]
    )
    _log(session, "  WRITE state['fit_card'] = <caption>")

    # Step 7: Return the completed session (error stays None on success).
    return session


# ── CLI test ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from utils.data_loader import get_example_wardrobe, get_empty_wardrobe

    print("=== Happy path: graphic tee ===\n")
    session = run_agent(
        query="looking for a vintage graphic tee under $30",
        wardrobe=get_example_wardrobe(),
    )
    print("\n".join(session["trace"]))          # visible state flow, step by step
    print("\n" + "-" * 60)
    if session["error"]:
        print(f"Error: {session['error']}")
    else:
        print(f"Found: {session['selected_item']['title']}")
        print(f"\nOutfit: {session['outfit_suggestion']}")
        print(f"\nFit card: {session['fit_card']}")

    print("\n\n=== No-results path ===\n")
    session2 = run_agent(
        query="designer ballgown size XXS under $5",
        wardrobe=get_example_wardrobe(),
    )
    print("\n".join(session2["trace"]))          # shows the early-exit branch
    print("\n" + "-" * 60)
    print(f"Error message: {session2['error']}")
