# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## What FitFindr Does

FitFindr is a multi-tool AI agent that takes a natural language query from the user (describing a secondhand clothing item they want to find) and orchestrates three tools in sequence: first searching mock listings for matches, then generating outfit suggestions based on the user's existing wardrobe, then producing a shareable Instagram-style caption for the final look. If the search returns no results, the agent stops immediately and tells the user what to adjust — it never calls suggest_outfit or create_fit_card with empty or missing data.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Scans the full mock listings dataset and returns items that match the user's description keywords, fit within a maximum price, and are available in the requested size. It scores each listing by how many keywords from the description appear in the listing's title, description, and style_tags, then returns the top matches sorted by relevance score.

**Input parameters:**
- `description` (str): A natural-language description of the item the user wants (e.g., "vintage graphic tee"). Used to compute keyword relevance scores against listing title, description, and style_tags.
- `size` (str | None): Size string the listing must match (e.g., "M", "S/M", "W28"). Matching is case-insensitive and substring-based — "M" will match "S/M" and "M" but not "XL". Pass None to skip size filtering.
- `max_price` (float | None): The upper price limit (inclusive). Only listings with price <= max_price are kept. Pass None to skip price filtering.

**What it returns:**
A list of listing dicts sorted by relevance score (highest first). Each dict contains:
- `id` (str): Unique listing identifier (e.g., "lst_001")
- `title` (str): Short item name (e.g., "Vintage Levi's 501 Jeans — Medium Wash")
- `description` (str): Longer text description of the item
- `category` (str): One of: tops, bottoms, outerwear, shoes, accessories
- `style_tags` (list[str]): Style descriptors (e.g., ["vintage", "grunge", "streetwear"])
- `size` (str): Size label as listed (e.g., "M", "W30 L30", "XL (oversized)")
- `condition` (str): One of: excellent, good, fair
- `price` (float): Listed price in USD
- `colors` (list[str]): Colors present in the item
- `brand` (str | None): Brand name, or None if unbranded
- `platform` (str): One of: depop, thredUp, poshmark

Returns an empty list (not an exception) if no listings pass all filters or have a relevance score > 0.

**What happens if it fails or returns nothing:**
The agent sets `session["error"]` to: "No listings found for '[description]' in size [size] under $[max_price]. Try broadening your search — remove the size filter, increase your budget, or use more general keywords." Then it returns the session immediately without calling suggest_outfit or create_fit_card. The Gradio UI displays the error message in a dedicated error text box.

---

### Tool 2: suggest_outfit

**What it does:**
Takes the top listing from search_listings (the item the user is considering buying) and the user's current wardrobe, then calls the Groq LLM to generate 1–2 specific outfit combinations. If the wardrobe is empty, it generates general styling advice for the item (what types of pieces pair well, what aesthetic it suits) rather than referencing named wardrobe pieces.

**Input parameters:**
- `new_item` (dict): A single listing dict (the item found by search_listings). The prompt will reference its title, style_tags, colors, and condition.
- `wardrobe` (dict): A wardrobe dict with an `items` key containing a list of wardrobe item dicts. Each item has: id (str), name (str), category (str), colors (list[str]), style_tags (list[str]), notes (str | None). May have an empty items list.

**What it returns:**
A non-empty string with outfit suggestions. For a populated wardrobe, each suggestion names specific wardrobe pieces (e.g., "Pair with your baggy straight-leg jeans and chunky white sneakers"). For an empty wardrobe, suggestions are general (e.g., "This pairs well with wide-leg trousers or carpenter jeans and chunky sneakers").

**What happens if it fails or returns nothing:**
If the LLM call raises an exception, the tool catches it and returns the string: "Could not generate outfit suggestions right now. Try describing your wardrobe manually or retry the request." The agent stores this fallback string in `session["outfit_suggestion"]` and still proceeds to create_fit_card so the user gets at least a fit card, even if the outfit suggestion is minimal.

---

### Tool 3: create_fit_card

**What it does:**
Takes the outfit suggestion string and the listing dict for the purchased item, then calls the Groq LLM (at higher temperature for variety) to produce a 2–4 sentence Instagram/TikTok-style caption. The caption references the item's title, price, and platform naturally once each, and captures the outfit vibe in specific rather than generic terms.

**Input parameters:**
- `outfit` (str): The outfit suggestion string returned by suggest_outfit(). Must be a non-empty string.
- `new_item` (dict): The listing dict for the thrifted item. The prompt uses new_item["title"], new_item["price"], and new_item["platform"] to ground the caption in real details.

**What it returns:**
A 2–4 sentence string written as a casual OOTD caption — lowercase-heavy, conversational, with the item name, price, and platform woven in naturally. The LLM temperature is set to 0.9 so the output differs meaningfully for different inputs.

**What happens if it fails or returns nothing:**
If `outfit` is empty or whitespace-only, the tool immediately returns: "Outfit details are missing — cannot generate a fit card without a complete look." without calling the LLM. If the LLM call raises an exception, the tool catches it and returns: "Could not generate a fit card right now. Here's the item: [title] for $[price] on [platform]." — giving the user something useful even in failure.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**

The planning loop runs as a linear state machine with one early-exit branch. It does not re-evaluate which tool to call after each step — it follows a fixed order, but it validates intermediate results before proceeding. Here is the exact conditional logic:

1. **Parse the query.** Call the Groq LLM with a short system prompt asking it to extract `description` (str), `size` (str | None), and `max_price` (float | None) from the user's query as JSON. Parse the response and store it in `session["parsed"]`. If the LLM response cannot be parsed as valid JSON, fall back to using the entire query as the description with size=None and max_price=None.

2. **Call search_listings.** Use `session["parsed"]["description"]`, `session["parsed"]["size"]`, and `session["parsed"]["max_price"]` as arguments. Store the returned list in `session["search_results"]`.

3. **Check search results.** If `session["search_results"]` is empty (length == 0): set `session["error"]` to a descriptive message (see Tool 1 failure mode above) and **return the session immediately** — do not call suggest_outfit or create_fit_card.

4. **Select top result.** Set `session["selected_item"] = session["search_results"][0]`. (No branching — the top-scored item is always chosen automatically.)

5. **Call suggest_outfit.** Use `session["selected_item"]` and `session["wardrobe"]` as arguments. Store the returned string in `session["outfit_suggestion"]`. Do not branch on the content of the outfit string — even the fallback error string is passed forward.

6. **Call create_fit_card.** Use `session["outfit_suggestion"]` and `session["selected_item"]` as arguments. Store the returned string in `session["fit_card"]`.

7. **Return the session.** At this point `session["error"]` is None (success path), and `session["fit_card"]` contains the final output.

The agent never loops back — it is a single-pass pipeline. The only decision point is step 3: empty search results terminate early; any other result continues forward.

---

## State Management

**How does information from one tool get passed to the next?**

All state lives in a single Python dict called `session`, initialized by `_new_session(query, wardrobe)` at the start of each call to `run_agent()`. The dict is mutated in place as the agent progresses:

- `session["parsed"]` — filled by the LLM query parser in step 1; read by search_listings in step 2.
- `session["search_results"]` — filled by search_listings in step 2; used to populate selected_item in step 4.
- `session["selected_item"]` — set to `search_results[0]` in step 4; passed to both suggest_outfit (step 5) and create_fit_card (step 6).
- `session["wardrobe"]` — passed in at initialization; read by suggest_outfit in step 5.
- `session["outfit_suggestion"]` — filled by suggest_outfit in step 5; passed to create_fit_card in step 6.
- `session["fit_card"]` — filled by create_fit_card in step 6; displayed to the user.
- `session["error"]` — set only when the interaction ends early (step 3); checked by the Gradio app to decide what to display.

No global variables are used. The session dict is passed by reference through the single `run_agent` call, so all tools access the same in-memory object. Between Gradio sessions, each new user submission calls `run_agent` fresh — there is no shared state across requests.

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No listings match the query (empty list returned) | Agent sets session["error"] to: "No listings found for '[description]' in size [size] under $[max_price]. Try broadening your search — remove the size filter, increase your budget, or use more general keywords like 'graphic tee' instead of 'vintage band tee 90s'." Then returns the session without calling the next two tools. |
| suggest_outfit | Wardrobe items list is empty | Tool calls the LLM with a prompt for general styling advice (what categories of items pair well, what aesthetic the new_item fits) instead of referencing named wardrobe pieces. Returns a non-empty string — the agent always proceeds to create_fit_card. |
| create_fit_card | outfit string is empty or whitespace-only | Tool guards at the top of the function: returns the string "Outfit details are missing — cannot generate a fit card without a complete look." without calling the LLM. If the LLM call itself fails (network error, etc.), returns "Could not generate a fit card right now. Here's the item: [title] for $[price] on [platform]." |

---

## Architecture

```
User query (natural language string)
    │
    ▼
run_agent(query, wardrobe)
    │
    ├─ Step 1: LLM Query Parser
    │       │  Input: raw query string
    │       │  Output: { description, size, max_price }
    │       ▼
    │   session["parsed"] = { description, size, max_price }
    │       │
    ├─ Step 2: search_listings(description, size, max_price)
    │       │  Input:  session["parsed"]
    │       │  Scans listings.json, scores by keyword overlap,
    │       │  filters by size and price, sorts by score
    │       ▼
    │   session["search_results"] = [ listing_dict, ... ]
    │       │
    ├─ Step 3: Check results
    │       │
    │       ├── results == [] ──► session["error"] = "No listings found..."
    │       │                          │
    │       │                          └──► RETURN session (early exit)
    │       │
    │       └── results != [] ──► session["selected_item"] = results[0]
    │                               │
    ├─ Step 4: suggest_outfit(selected_item, wardrobe)
    │       │  Input:  session["selected_item"], session["wardrobe"]
    │       │
    │       ├── wardrobe["items"] == [] ──► LLM: general styling advice
    │       │
    │       └── wardrobe["items"] != [] ──► LLM: specific outfit combos
    │                                            using named wardrobe pieces
    │       ▼
    │   session["outfit_suggestion"] = "Pair with your baggy jeans..."
    │       │
    ├─ Step 5: create_fit_card(outfit_suggestion, selected_item)
    │       │  Input: session["outfit_suggestion"], session["selected_item"]
    │       │
    │       ├── outfit == "" ──► return error string (no LLM call)
    │       │
    │       └── outfit != "" ──► LLM (temp=0.9): Instagram-style caption
    │       ▼
    │   session["fit_card"] = "thrifted this faded band tee off depop..."
    │       │
    └─ Step 6: RETURN session
                  │
                  ▼
            Gradio UI displays:
              - Found item: session["selected_item"]["title"] + price + platform
              - Outfit:     session["outfit_suggestion"]
              - Fit card:   session["fit_card"]
              - Error:      session["error"] (if not None, shown instead of above)
```

---

## AI Tool Plan

**Milestone 3 — Individual tool implementations:**

**Tool 1 — search_listings:**
I'll give Claude the Tool 1 spec block from this planning.md (inputs, return value, failure mode, and the scoring logic described in the TODO comments in tools.py) along with the `load_listings()` docstring from utils/data_loader.py. I'll ask it to implement the function in tools.py using load_listings(), filtering by size (case-insensitive substring) and max_price, scoring by keyword overlap with title + description + style_tags, and returning an empty list (not raising) when nothing matches. I'll verify by running three test queries manually: (1) a query that should return 3+ results, (2) a query with a strict size that filters most out, and (3) a query that matches nothing — checking the return value is [] not an exception.

**Tool 2 — suggest_outfit:**
I'll give Claude the Tool 2 spec block from this planning.md plus the wardrobe_schema.json structure, and ask it to implement suggest_outfit() in tools.py using the Groq client already set up in the file. I'll instruct it to branch on `len(wardrobe["items"]) == 0` and write two different system/user prompts: one for general styling advice and one that formats the wardrobe items list and asks for specific outfit combos. I'll verify by running it with the example wardrobe (should name specific pieces) and with get_empty_wardrobe() (should give general advice, not crash or return "").

**Tool 3 — create_fit_card:**
I'll give Claude the Tool 3 spec block from this planning.md and ask it to implement create_fit_card() in tools.py. Key constraints to include in the prompt: guard at top of function for empty outfit string, use temperature=0.9 in the Groq call, the caption must be 2–4 sentences and mention title/price/platform exactly once each. I'll verify by running it three times with the same input and checking that the output varies meaningfully, and once with an empty outfit string to confirm the guard returns the error message.

**Milestone 4 — Planning loop and state management:**

I'll give Claude the full Architecture diagram from this planning.md and the Planning Loop section (with all 7 steps and their conditions), along with the scaffolded `run_agent()` function in agent.py (including the `_new_session()` dict structure). I'll ask it to implement `run_agent()` following the diagram exactly: LLM-based query parsing in step 1 (returning JSON with description/size/max_price), the early-exit branch in step 3, and linear state passing through the session dict. I'll verify by running the two test cases already in the `if __name__ == "__main__"` block at the bottom of agent.py: the happy path (should print a fit card) and the no-results path (should print only an error message).

---

## A Complete Interaction (Step by Step)

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 1 — Parse the query:**
The agent sends the query to the Groq LLM and asks it to extract structured parameters as JSON. The LLM returns: `{"description": "vintage graphic tee", "size": null, "max_price": 30.0}`. The agent stores this in `session["parsed"]`. (No size was specified, so size is null and size filtering will be skipped.)

**Step 2 — Search listings:**
The agent calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. The function loads all listings, drops any with price > 30.0, and scores the remaining ones by keyword overlap — "vintage" and "graphic tee" are matched against title, description, and style_tags. Listings with style_tags like ["vintage", "graphic tee", "y2k"] score highest. The function returns a sorted list of 2–4 matching listings. The agent stores this in `session["search_results"]`.

**Step 3 — Select the top item:**
Results are non-empty, so the agent skips the error branch. It sets `session["selected_item"] = session["search_results"][0]`. For example: `{"id": "lst_002", "title": "Y2K Baby Tee — Butterfly Print", "price": 18.0, "platform": "depop", "style_tags": ["y2k", "vintage", "graphic tee"], "colors": ["white", "pink", "purple"], ...}`.

**Step 4 — Suggest outfit:**
The agent calls `suggest_outfit(new_item=session["selected_item"], wardrobe=session["wardrobe"])`. The wardrobe has items (baggy jeans, chunky white sneakers, etc.), so the LLM receives a formatted list of those pieces and is asked to suggest 1–2 outfits using the Y2K Baby Tee. The LLM returns: "Pair this butterfly tee with your baggy straight-leg jeans and chunky white sneakers for a clean Y2K streetwear look — tuck the front of the tee slightly for shape. For a second option, layer your black cropped zip hoodie over it, open, with the same jeans." The agent stores this in `session["outfit_suggestion"]`.

**Step 5 — Create fit card:**
The agent calls `create_fit_card(outfit=session["outfit_suggestion"], new_item=session["selected_item"])`. The LLM generates a casual caption at temperature=0.9. Example output: "found this y2k butterfly tee on depop for $18 and it was literally made for my baggy jeans era 🦋 tucked the front, threw on my chunky sneakers and honestly the fit wrote itself. full look is in my stories if you wanna see it." The agent stores this in `session["fit_card"]`.

**Final output to user:**
The Gradio UI displays three sections:
- **Found item:** "Y2K Baby Tee — Butterfly Print — $18.00 on depop (excellent condition)"
- **Outfit suggestion:** "Pair this butterfly tee with your baggy straight-leg jeans and chunky white sneakers for a clean Y2K streetwear look..."
- **Fit card:** "found this y2k butterfly tee on depop for $18 and it was literally made for my baggy jeans era 🦋..."

**Error path example:**
If the user had searched "designer ballgown size XXS under $5", search_listings returns []. The agent sets `session["error"]` to "No listings found for 'designer ballgown' in size XXS under $5.00. Try broadening your search — remove the size filter, increase your budget, or use more general keywords." and returns immediately. The Gradio UI shows only the error message, and suggest_outfit and create_fit_card are never called.
