import asyncio
import json
from typing import Any, Awaitable, Callable, Dict, List, Optional
from urllib.parse import quote_plus

import httpx

EmitFn = Callable[[str, str, str, Optional[Dict[str, Any]]], Awaitable[None]]

SEEDS = [
    "dna diet",
    "nutrigenomics",
    "23andme diet",
    "personalized meal plan",
    "genetic nutrition",
    "meal plan subscription",
    "dna nutrition",
    "nutrigenomic meal plan",
]

NOISE_TOKENS = ("cats", "dog", "joke", "egypt", "philippines", "india", "uk", "canada", "australia", "bangalore", "hyderabad", "singapore", "dubai", "pronunciation", "jobs", "salary", "course", "degree", "pdf free", "creatine", "protein powder")

HIGH_VALUE_TOKENS = {
    "dna": 18,
    "23andme": 18,
    "nutrigenomic": 22,
    "nutrigenomics": 22,
    "genetic": 15,
    "genetics": 15,
    "meal": 16,
    "meals": 14,
    "plan": 14,
    "planner": 14,
    "planning": 14,
    "diet": 12,
    "nutrition": 14,
    "weekly": 12,
    "personalized": 12,
    "upload": 15,
    "raw": 14,
    "subscription": 14,
    "service": 10,
    "app": 10,
}


def _classify_keyword(kw: str, seed: str) -> Dict[str, Any]:
    low = kw.lower()
    score = 34
    for tok, pts in HIGH_VALUE_TOKENS.items():
        if tok in low:
            score += pts
    score = min(98, score)

    if any(w in low for w in ("app", "best", "subscription", "cost", "price", "service", "planner", "planning", "upload", "review")):
        intent = "Commercial"
        angle = "Product-led comparison / landing section highlighting $34.97/mo weekly updates"
    elif any(w in low for w in ("how", "what", "why", "research", "definition", "vs", "does", "science", "example")):
        intent = "Informational"
        angle = "Educational nutrigenomics guide linking to GeneMeal weekly meal planner"
    else:
        intent = "Solution-Aware"
        angle = "How existing DNA files power real-time weekly meal plans (no test kit needed)"

    return {
        "keyword": kw,
        "seed_term": seed,
        "source": "google_autocomplete",
        "intent": intent,
        "relevance_score": score,
        "suggested_angle": angle,
    }


async def discover_keywords(emit: EmitFn) -> List[Dict[str, Any]]:
    discovered: Dict[str, Dict[str, Any]] = {}
    await emit("info", "keywords", f"Querying Google Autocomplete politely across {len(SEEDS)} nutrigenomic seeds ...", {})

    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; GeneMealSEOBot/1.0)"},
    ) as client:
        for seed in SEEDS:
            url = f"https://suggestqueries.google.com/complete/search?client=firefox&q={quote_plus(seed)}"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    payload = json.loads(resp.text)
                    suggestions = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
                    kept = 0
                    for s in suggestions:
                        kw = str(s).strip().lower()
                        if not kw or len(kw) < 4:
                            continue
                        if any(bad in kw for bad in NOISE_TOKENS):
                            continue
                        if kw not in discovered:
                            discovered[kw] = _classify_keyword(kw, seed)
                            kept += 1
                    await emit(
                        "success",
                        "keywords",
                        f"Autocomplete '{seed}' -> {len(suggestions)} raw, {kept} relevant signals",
                        {"seed": seed, "count": kept},
                    )
                else:
                    await emit("warn", "keywords", f"Autocomplete '{seed}' returned HTTP {resp.status_code}", {})
            except Exception as exc:
                await emit("warn", "keywords", f"Autocomplete '{seed}' skipped ({exc})", {})
            await asyncio.sleep(0.25)

    # Always include core on-page topic gaps anchored to GeneMeal positioning
    onpage_gaps = [
        {
            "keyword": "weekly nutrigenomic meal plan subscription",
            "seed_term": "core-positioning",
            "source": "onpage_gap",
            "intent": "Commercial",
            "relevance_score": 99,
            "suggested_angle": "Primary homepage & pricing differentiator ($34.97/mo weekly updates)",
        },
        {
            "keyword": "use existing 23andme or ancestry dna for meal planning",
            "seed_term": "core-positioning",
            "source": "onpage_gap",
            "intent": "Commercial",
            "relevance_score": 96,
            "suggested_angle": "Explain BYO-DNA workflow — GeneMeal is software, not a DNA test kit",
        },
        {
            "keyword": "real-time adaptive meal plan from genetics",
            "seed_term": "core-positioning",
            "source": "onpage_gap",
            "intent": "Solution-Aware",
            "relevance_score": 94,
            "suggested_angle": "Show why weekly updates beat static one-time PDF reports",
        },
    ]
    for gap in onpage_gaps:
        discovered.setdefault(gap["keyword"], gap)

    results = sorted(discovered.values(), key=lambda x: x["relevance_score"], reverse=True)
    await emit("success", "keywords", f"Keyword pipeline ready: {len(results)} unique opportunities stored.", {"total": len(results)})
    return results


def build_blog_drafts(keywords: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    top_kw = next((k["keyword"] for k in keywords if "23andme" in k["keyword"] or "raw" in k["keyword"]), "use existing 23andme or ancestry dna for meal planning")
    stress_kw = next((k["keyword"] for k in keywords if "stress" in k["keyword"]), "nutrigenomics stress and everyday meal planning")
    weekly_kw = next((k["keyword"] for k in keywords if "weekly" in k["keyword"] or "subscription" in k["keyword"]), "weekly nutrigenomic meal plan subscription")
    pers_kw = next((k["keyword"] for k in keywords if "personalized meal plan" in k["keyword"]), "personalized meal planning service")

    positioning = (
        "Positioning guardrails: GeneMeal is a real-time meal-planning subscription ($34.97/mo) with weekly "
        "nutrigenomic meal plan updates. Explicitly state it is NOT a DNA test kit and NOT medical advice."
    )

    return [
        {
            "title": "Already Have a DNA File? Turn It Into Weekly Meal Plans (Without Buying Another Test)",
            "slug": "existing-dna-file-to-weekly-meal-plans",
            "target_keyword": top_kw,
            "meta_description": (
                "Put your existing DNA data to work with GeneMeal: a $34.97/mo real-time meal-planning subscription "
                "delivering weekly nutrigenomic updates. Not a DNA test or medical advice."
            ),
            "outline": [
                "H2: Why Static DNA PDFs Gather Dust in Your Inbox",
                "H2: How BYO-DNA Meal Planning Works (No New Swab Kit Required)",
                "H2: What Changes Each Week in a Real-Time Nutrigenomic Meal Plan",
                "H2: Clear Boundaries — Nutritional Meal Planning vs. Medical Advice",
                "H2: Getting Started for $34.97/mo (Cancel Anytime)",
            ],
            "positioning_notes": positioning,
        },
        {
            "title": "Static Genetic Diet Reports vs. Weekly Nutrigenomic Meal Plan Updates",
            "slug": "static-genetic-reports-vs-weekly-meal-plan-updates",
            "target_keyword": weekly_kw,
            "meta_description": (
                "Compare one-off genetic diet PDFs with a live $34.97/mo meal-planning subscription that refreshes "
                "nutrigenomic menus every week. Not a DNA test or medical diagnosis."
            ),
            "outline": [
                "H2: The Problem With One-Time Macro & Trait Checklists",
                "H2: Why Real-Time Weekly Iteration Improves Kitchen Follow-Through",
                "H2: Inside a Week of GeneMeal Recipes & Grocery Alignment",
                "H2: Transparent $34.97/mo Subscription Pricing Breakdown",
            ],
            "positioning_notes": positioning,
        },
        {
            "title": "Stress, Cortisol, and Everyday Food Choices: A Practical Nutrigenomic Guide",
            "slug": "stress-diet-practical-nutrigenomic-meal-planning",
            "target_keyword": stress_kw,
            "meta_description": (
                "Understand how stress-related nutrition research connects to everyday weekly meal prep. "
                "Explore GeneMeal's $34.97/mo meal-planning subscription (not medical advice)."
            ),
            "outline": [
                "H2: How Stress Shifts Appetite, Cravings, and Meal Timing",
                "H2: What Nutrigenomic Studies Explore Around Stress & Nutrients",
                "H2: Turning Research Into Repeatable Weekday Dinners",
                "H2: Disclaimer: Educational Meal Planning, Not Clinical Treatment",
            ],
            "positioning_notes": positioning,
        },
        {
            "title": "What a $34.97/Month Nutrigenomic Meal-Planning Subscription Actually Includes",
            "slug": "what-3497-monthly-nutrigenomic-meal-subscription-includes",
            "target_keyword": "meal plan subscription",
            "meta_description": (
                "See what you get with GeneMeal at $34.97/mo: weekly updated meal plans shaped by nutrigenomics, "
                "built from your existing DNA file. No test kit sold; not medical advice."
            ),
            "outline": [
                "H2: Built for Actionable Groceries, Not Lab Jargon",
                "H2: Weekly Refresh Cadence & Real-Time Preference Adjustments",
                "H2: Privacy & Scope: You Bring Your Data, We Plan the Meals",
                "H2: Is GeneMeal Right for You? Checklist Before Subscribing",
            ],
            "positioning_notes": positioning,
        },
        {
            "title": "5 Questions to Ask Before Choosing Any DNA-Informed Meal Planner",
            "slug": "questions-before-choosing-dna-meal-planner",
            "target_keyword": pers_kw,
            "meta_description": (
                "Evaluate any DNA-informed meal planner on weekly updates, pricing transparency ($34.97/mo), "
                "data ownership, and non-medical boundaries before you subscribe."
            ),
            "outline": [
                "H2: 1. Do You Have to Buy a New DNA Kit, or Can You Use Existing Data?",
                "H2: 2. Does the Menu Update Weekly in Real Time?",
                "H2: 3. Are Medical Claims Kept Strictly Out of Scope?",
                "H2: 4. Is Subscription Pricing Clear Upfront ($34.97/mo)?",
                "H2: 5. How Fast Can You Turn Traits Into a Shopping List?",
            ],
            "positioning_notes": positioning,
        },
    ]


GENERIC_NOISE = (
    "cats", "dog", "joke", "pronunciation", "jobs", "salary", "course", "degree",
    "pdf free", "lyrics", "weather", "horoscope",
)


def seeds_from_pages(pages: List[Dict[str, Any]], host: str, limit: int = 8) -> List[str]:
    """Build conservative autocomplete seeds from measured titles/H1s and the hostname."""
    from collections import Counter
    import re

    stop = {
        "the", "and", "for", "with", "from", "that", "this", "your", "you", "are", "was",
        "our", "www", "com", "net", "org", "http", "https", "home", "page", "official",
        "a", "an", "of", "to", "in", "on", "at", "by", "or", "is",
    }
    counts: Counter[str] = Counter()
    phrases: List[str] = []
    brand = (host or "").split(".")[0].replace("-", " ").strip()
    if brand and len(brand) >= 3:
        phrases.append(brand)

    for p in pages or []:
        for field in (p.get("title") or "", p.get("h1_text") or ""):
            clean = re.sub(r"[\|–—\-:].*$", " ", field)
            clean = re.sub(r"[^a-zA-Z0-9\s]", " ", clean)
            words = [w.lower() for w in clean.split() if len(w) > 2 and w.lower() not in stop]
            if 1 < len(words) <= 6:
                phrases.append(" ".join(words[:5]))
            for w in words:
                counts[w] += 1

    # Prefer multi-word phrases, then top tokens paired with the brand.
    unique: List[str] = []
    for phrase in phrases:
        if phrase and phrase not in unique:
            unique.append(phrase)
    for token, _n in counts.most_common(8):
        if brand and token != brand:
            combo = f"{token} {brand}"
            if combo not in unique:
                unique.append(combo)
        if token not in unique:
            unique.append(token)
    return unique[:limit]


async def discover_keywords_generic(seeds: List[str], emit: EmitFn, brand: str = "") -> List[Dict[str, Any]]:
    discovered: Dict[str, Dict[str, Any]] = {}
    seeds = [s.strip().lower() for s in seeds if s and len(s.strip()) >= 3][:8]
    if not seeds:
        seeds = [brand.lower()] if brand else []
    await emit("info", "keywords", f"Querying Google Autocomplete politely across {len(seeds)} on-page seeds ...", {})

    async with httpx.AsyncClient(
        timeout=10.0,
        headers={"User-Agent": "Mozilla/5.0 (compatible; GeneMealSEOBot/1.0)"},
    ) as client:
        for seed in seeds:
            url = f"https://suggestqueries.google.com/complete/search?client=firefox&q={quote_plus(seed)}"
            try:
                resp = await client.get(url)
                if resp.status_code == 200:
                    payload = json.loads(resp.text)
                    suggestions = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
                    kept = 0
                    for s in suggestions:
                        kw = str(s).strip().lower()
                        if not kw or len(kw) < 4:
                            continue
                        if any(bad in kw for bad in GENERIC_NOISE):
                            continue
                        if kw not in discovered:
                            intent = (
                                "Informational"
                                if any(w in kw for w in ("how", "what", "why", "definition", "meaning", "vs"))
                                else ("Commercial" if any(w in kw for w in ("buy", "price", "pricing", "service", "software", "app")) else "Solution-Aware")
                            )
                            discovered[kw] = {
                                "keyword": kw,
                                "seed_term": seed,
                                "source": "google_autocomplete",
                                "intent": intent,
                                "relevance_score": min(95, 40 + 8 * sum(1 for t in seed.split() if t in kw)),
                                "suggested_angle": (
                                    "Turn this query into an on-page heading or FAQ using the site's existing wording. "
                                    "Do not invent statistics, rankings, or pricing."
                                ),
                            }
                            kept += 1
                    await emit(
                        "success",
                        "keywords",
                        f"Autocomplete '{seed}' -> {len(suggestions)} raw, {kept} relevant signals",
                        {"seed": seed, "count": kept},
                    )
                else:
                    await emit("warn", "keywords", f"Autocomplete '{seed}' returned HTTP {resp.status_code}", {})
            except Exception as exc:
                await emit("warn", "keywords", f"Autocomplete '{seed}' skipped ({exc})", {})
            await asyncio.sleep(0.25)

    results = sorted(discovered.values(), key=lambda x: x["relevance_score"], reverse=True)
    await emit("success", "keywords", f"Keyword pipeline ready: {len(results)} unique opportunities stored.", {"total": len(results)})
    return results
