# FitFindr 🛍️

FitFindr is a multi-tool AI agent that helps you find secondhand clothing and figure out how to wear it. You describe what you're looking for in plain English; the agent searches a mock listings dataset, suggests an outfit built around your existing wardrobe, and writes a shareable Instagram-style caption for the look — recovering gracefully whenever a tool returns nothing useful.

```
User: "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers."

→ Found:    Y2K Baby Tee — Butterfly Print · $18.00 · depop · excellent condition
→ Outfit:   Pair the Y2K Baby Tee with your baggy straight-leg jeans and chunky white
            sneakers for a casual streetwear look. Tuck the front for shape, or layer
            your vintage black denim jacket over it for some edge.
→ Fit card: just scored this y2k butterfly tee for $18 on depop and i'm obsessed 🦋
            paired it with my baggy jeans and chunky sneakers — the fit wrote itself.
```

---

## Setup

```bash
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file in the project root (free key at [console.groq.com](https://console.groq.com)):

```
GROQ_API_KEY=your_key_here
```

## Running

```bash
python app.py
```

Open the URL printed in your terminal (usually `http://localhost:7860`, but **check the terminal output** — the port can differ). Type a query, pick a wardrobe (example or empty), and hit **Find it**.

You can also drive the agent without the UI:

```bash
python agent.py          # runs the built-in happy-path + no-results demos
pytest tests/            # runs the tool test suite (10 tests)
pytest tests/ -m "not llm"   # tool tests that don't call the LLM (offline)
```

> **Windows note:** if you print agent output to the terminal and see a `UnicodeEncodeError` on an emoji, set `PYTHONIOENCODING=utf-8` first. This is a Windows console limitation, not an agent bug — the browser UI renders emoji fine either way.

---

## Architecture at a Glance

```
        User query (natural language)
                  │
                  ▼
        run_agent(query, wardrobe)
                  │
   ┌──────────────┴───────────────────────────────────────────┐
   │  Planning loop — single pass, one branch point            │
   │                                                           │
   │  1. _parse_query()  → { description, size, max_price }    │
   │  2. search_listings(...)                                  │
   │        │ results == []  ──► set session["error"]  ──► RETURN (early exit)
   │        │ results != []                                    │
   │  3. selected_item = results[0]                            │
   │  4. suggest_outfit(selected_item, wardrobe)               │
   │  5. create_fit_card(outfit_suggestion, selected_item)     │
   │  6. RETURN session                                        │
   └───────────────────────────────────────────────────────────┘
                  │
                  ▼
        Gradio maps session → 3 panels (listing · outfit · fit card)
```

All state lives in one `session` dict that is mutated in place as the loop runs. See [planning.md](planning.md) for the full spec and the detailed agent diagram.

---

## Tool Inventory

The agent orchestrates three tools, all defined in [tools.py](tools.py).

### 1. `search_listings(description, size, max_price) → list[dict]`

**Purpose:** Find listings matching the user's request, ranked by how well they fit the description.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `description` | `str` | Item keywords, e.g. `"vintage graphic tee"`. Scored against each listing's title, description, and style_tags. |
| `size` | `str \| None` | Size filter, e.g. `"M"`. Case-insensitive substring match (`"M"` matches `"S/M"` and `"M/L"`). `None` skips size filtering. |
| `max_price` | `float \| None` | Inclusive price ceiling. `None` skips price filtering. |

**Returns:** A list of listing dicts sorted by relevance score, highest first. Each dict has `id`, `title`, `description`, `category`, `style_tags` (list), `size`, `condition`, `price` (float), `colors` (list), `brand` (str or None), `platform`. **Returns an empty list — never raises — when nothing matches.**

**How scoring works:** the description is tokenized into keywords (stop words dropped); each listing earns one point per keyword found in its combined title + description + style_tags text, plus a bonus when the full description phrase appears verbatim. Listings scoring zero are discarded.

### 2. `suggest_outfit(new_item, wardrobe) → str`

**Purpose:** Suggest one or two complete outfits built around the found item.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `new_item` | `dict` | A listing dict (the item the user is considering). |
| `wardrobe` | `dict` | A wardrobe dict with an `items` key — a list of wardrobe item dicts (`id`, `name`, `category`, `colors`, `style_tags`, `notes`). May be empty. |

**Returns:** A non-empty string of outfit suggestions. With a populated wardrobe it names specific pieces ("pair with your baggy straight-leg jeans"); with an empty wardrobe it gives general styling advice instead. Calls Groq `llama-3.3-70b-versatile` at temperature 0.7.

### 3. `create_fit_card(outfit, new_item) → str`

**Purpose:** Turn the outfit into a short, shareable OOTD caption.

| Parameter | Type | Meaning |
|-----------|------|---------|
| `outfit` | `str` | The outfit suggestion string from `suggest_outfit()`. |
| `new_item` | `dict` | The listing dict — its `title`, `price`, and `platform` are woven into the caption. |

**Returns:** A 2–4 sentence casual caption that mentions the item name, price, and platform once each. Calls the LLM at **temperature 0.9** so the same input produces meaningfully different captions across runs.

---

## How the Planning Loop Works

The loop lives in `run_agent()` in [agent.py](agent.py). It is a **single-pass pipeline with one decision point** — it does not call all three tools unconditionally, and it does not loop back.

1. **Parse the query.** `_parse_query()` sends the raw query to the LLM (temperature 0.0) and asks for JSON: `{description, size, max_price}`. The result is stored in `session["parsed"]`. If the LLM output can't be parsed as JSON, it falls back to using the whole query as the description with no filters — a broad search rather than a crash.

2. **Search.** `search_listings()` runs with the parsed parameters; results go into `session["search_results"]`.

3. **The branch point.** If `search_results` is empty, the agent sets `session["error"]` to an actionable message and **returns immediately** — `suggest_outfit` and `create_fit_card` are never called. This is the decision that makes it a real planning loop rather than a fixed script: the agent responds to what the search returns. If results exist, it sets `session["selected_item"] = search_results[0]` (the top-ranked item) and continues.

4. **Suggest.** `suggest_outfit()` runs with the selected item and the wardrobe; the result goes into `session["outfit_suggestion"]`.

5. **Caption.** `create_fit_card()` runs with the outfit suggestion and the selected item; the result goes into `session["fit_card"]`.

6. **Return** the completed session (`error` stays `None` on success).

**Why the branch matters:** the same code path produces two visibly different behaviors. A query like *"vintage graphic tee under $30"* runs all three tools and ends with a fit card. A query like *"designer ballgown size XXS under $5"* stops after step 3 with an error and `fit_card == None`. The agent's behavior is driven by the data, not hardcoded.

---

## State Management

All state for one interaction lives in a single `session` dict, created by `_new_session(query, wardrobe)` and **mutated in place** as the loop runs. No globals are used; each tool reads from and writes to the same in-memory object:

| Key | Written by | Read by |
|-----|-----------|---------|
| `parsed` | `_parse_query` (step 1) | `search_listings` (step 2) |
| `search_results` | `search_listings` (step 2) | branch check + item selection (step 3) |
| `selected_item` | item selection (step 3) | `suggest_outfit` (4) **and** `create_fit_card` (5) |
| `wardrobe` | `_new_session` | `suggest_outfit` (4) |
| `outfit_suggestion` | `suggest_outfit` (4) | `create_fit_card` (5) |
| `fit_card` | `create_fit_card` (5) | the UI |
| `error` | the branch (step 3) | the UI (decides what to display) |

Because state is passed **by reference**, the item found in step 2 flows into step 4 untouched — the user never re-enters it. This was verified by identity: `session["selected_item"] is <the exact dict passed into suggest_outfit>` returns `True`, as does the same check for `create_fit_card`. Each new Gradio submission starts a fresh session, so there is no state bleed between requests.

---

## Error Handling

Every tool owns its failure mode and returns a usable value rather than raising or returning nothing.

| Tool | Failure mode | What the agent does |
|------|--------------|---------------------|
| `search_listings` | No listing matches the filters | Returns `[]`. The planning loop catches this, sets `session["error"]`, and stops before the other tools run. |
| `suggest_outfit` | Wardrobe is empty (or the LLM call errors) | Empty wardrobe → general styling advice. LLM error → caught, returns a fallback string. Always returns a non-empty string. |
| `create_fit_card` | Outfit string is empty/whitespace (or the LLM call errors) | Empty outfit → guard returns an error string **without calling the LLM**. LLM error → returns a fallback caption containing the item details. |

**Concrete example from testing** — the no-results path, triggered deliberately:

```bash
$ python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
[]

$ python agent.py
=== No-results path ===
Error message: No listings found for 'designer ballgown' in XXS under $5.00. Try
broadening your search — remove the size filter, increase your budget, or use more
general keywords.
```

The error is **specific and actionable** — it names what was searched and lists three concrete things to try — and `session["fit_card"]` stays `None`, confirming the downstream tools were never reached.

**Empty wardrobe**, triggered directly:

```bash
$ python -c "from tools import search_listings, suggest_outfit; from utils.data_loader import get_empty_wardrobe; r = search_listings('vintage graphic tee', None, 50); print(suggest_outfit(r[0], get_empty_wardrobe()))"
This Y2K Baby Tee pairs well with high-waisted jeans or a flowy skirt for a casual,
nostalgic look. Adding sneakers or sandals can enhance the laid-back vibe...
```

**Empty outfit string**, triggered directly:

```bash
$ python -c "from tools import search_listings, create_fit_card; r = search_listings('vintage graphic tee', None, 50); print(create_fit_card('', r[0]))"
Outfit details are missing — cannot generate a fit card without a complete look.
```

All three produce informative strings — no exceptions, no empty output.

---

## Testing

Tests live in [tests/test_tools.py](tests/test_tools.py) and cover each tool plus every failure mode:

```bash
pytest tests/              # all 10 tests
pytest tests/ -m "not llm" # only the offline (non-LLM) tests
```

- **search_listings:** returns results, empty-result case (`== []`), price filter, size filter, relevance ordering.
- **suggest_outfit:** populated wardrobe, empty wardrobe.
- **create_fit_card:** returns text, empty-outfit guard, output varies across runs (confirms the temperature is high enough).

Tests that make a live Groq call are marked `llm` so the pure-logic tests can run without network or an API key.

---

## How AI Tools Were Used

I used Claude (via Claude Code) as the implementation assistant, driven by the spec sections in [planning.md](planning.md). Two specific instances:

**1. Implementing `search_listings`.** I gave Claude the Tool 1 spec block from planning.md (parameter names/types, the scoring approach, and the "return `[]`, never raise" failure mode) along with the `load_listings()` docstring. It produced a working filter-and-score function. **What I changed:** the first version did a naive whole-string substring match for the description, which meant a multi-word query like "vintage graphic tee" only matched listings containing that exact phrase. I overrode it to tokenize the description into keywords, drop stop words, and score by per-keyword overlap with a bonus for a full-phrase match — so partial matches still surface and results rank sensibly. I verified the final version against the three test queries (results / empty / price filter) before trusting it.

**2. Implementing the planning loop + query parser.** I gave Claude the full agent diagram and the Planning Loop and State Management sections from planning.md, plus the scaffolded `run_agent()` and `_new_session()`. It produced the loop following the seven steps. **What I changed/added:** the spec mentioned LLM-based query parsing but I made the parser more defensive than the first draft — it now extracts the JSON object with a regex (the model sometimes wraps JSON in prose or code fences) and falls back to a broad description-only search if parsing fails, rather than letting a malformed response break the run. I also verified by identity that `selected_item` is the *same object* passed into both downstream tools (not a copy), to prove state actually flows rather than being re-derived.

---

## Project Structure

```
ai201-project2-fitfindr-starter/
├── agent.py                  # run_agent() planning loop + _parse_query()
├── tools.py                  # the three tools (search / suggest / fit card)
├── app.py                    # Gradio UI + handle_query()
├── planning.md               # full spec, agent diagram, AI tool plan
├── data/
│   ├── listings.json         # 40 mock secondhand listings
│   └── wardrobe_schema.json  # wardrobe format + example/empty wardrobes
├── utils/
│   └── data_loader.py        # load_listings(), get_example_wardrobe(), ...
├── tests/
│   └── test_tools.py         # per-tool tests incl. every failure mode
└── requirements.txt
```

---

## Spec Reflection

Writing the spec before any code paid off most in the planning loop. Because [planning.md](planning.md) already described the branch point as an explicit early return ("if `search_results` is empty, set the error and return — do not call the next tools"), the implementation was a direct translation rather than a design exercise, and the agent's data-driven behavior fell out for free.

The spec changed in two places during the build. First, I added an **LLM query-parsing step** that the original tool list didn't call out — without it the agent couldn't turn "under $30" into `max_price=30.0`, so parsing earned its own step (step 1) and its own fallback. Second, the **scoring logic for `search_listings`** got more detailed than "filter by keywords": real queries are multi-word, so I specified per-keyword scoring with a phrase bonus to get sensible ranking instead of brittle exact-phrase matching.

The biggest lesson: the parts of the spec I wrote *vaguely* are the parts that needed rework, and the parts I wrote *precisely* (the branch, the session keys, each failure message) translated straight into code. A specific spec produced specific code; the one place I hand-waved — "parse the query somehow" — is exactly where I had to stop and design mid-build.
