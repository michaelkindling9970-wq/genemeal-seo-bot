import json
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse
from bs4 import BeautifulSoup


def _extract_json_ld_types(soup: BeautifulSoup) -> List[str]:
    types: List[str] = []
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (tag.string or tag.get_text() or "").strip()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop(0)
            if isinstance(item, dict):
                t = item.get("@type")
                if isinstance(t, str):
                    types.append(t)
                elif isinstance(t, list):
                    types.extend([str(x) for x in t])
                if "@graph" in item and isinstance(item["@graph"], list):
                    stack.extend(item["@graph"])
    return list(dict.fromkeys(types))


def _visible_word_count(soup: BeautifulSoup) -> int:
    clone = BeautifulSoup(str(soup), "html.parser")
    for el in clone(["script", "style", "noscript", "svg"]):
        el.decompose()
    text = clone.get_text(" ", strip=True)
    words = re.findall(r"\b\w+\b", text)
    return len(words)


def _suggest_ctr_rewrite_genemeal(page: Dict[str, Any]) -> Dict[str, Any] | None:
    path = page["path"]
    cur_title = page["title"] or "(missing)"
    cur_meta = page["meta_description"] or "(missing)"

    if path == "/":
        sug_title = "GeneMeal: Weekly Nutrigenomic Meal Plans ($34.97/mo)"
        sug_meta = (
            "Real-time meal-planning subscription with weekly nutrigenomic updates tailored to your DNA file. "
            "$34.97/mo, cancel anytime. Not a DNA test or medical advice."
        )
        rationale = (
            "Leads with transparent $34.97/mo subscription pricing, clarifies weekly nutrigenomic updates, "
            "and explicitly distinguishes GeneMeal from a DNA test kit to qualify high-intent clicks."
        )
        impact = "High"
    elif path == "/pricing":
        sug_title = "GeneMeal Pricing: $34.97/mo Weekly DNA Meal Plan Subscription"
        sug_meta = (
            "Simple $34.97/month meal-planning subscription with fresh weekly nutrigenomic meal plan updates "
            "from your existing DNA file. No test kit sold. Not medical advice."
        )
        rationale = (
            "Puts the exact $34.97/mo price and weekly refresh value directly in the SERP title and snippet "
            "to boost commercial click-throughs on pricing queries."
        )
        impact = "High"
    elif path.startswith("/research/"):
        topic = page["h1_text"] or page["title"] or "Nutrigenomics Research"
        clean_topic = re.sub(r"\s*[—|-]\s*GeneMeal.*$", "", topic).strip()
        sug_title = f"{clean_topic[:42]} | GeneMeal Research"
        sug_meta = (
            f"Explore how nutrigenomic research informs {clean_topic.lower()} and weekly meal planning. "
            "Educational guide from GeneMeal ($34.97/mo meal subscription; not medical advice)."
        )
        rationale = (
            "Aligns editorial research snippet with actionable meal-planning intent while maintaining "
            "clear non-medical-advice positioning and brand recognition."
        )
        impact = "Medium"
    elif path == "/about":
        sug_title = "About GeneMeal | Real-Time Nutrigenomic Meal Planning"
        sug_meta = (
            "How GeneMeal turns your existing DNA data into weekly updated, real-time meal plans for "
            "$34.97/mo. Software meal planner only—not a DNA test or medical advice."
        )
        rationale = (
            "Clarifies product positioning immediately in search results so visitors understand GeneMeal "
            "is an ongoing meal-planning subscription rather than a diagnostic or test-kit vendor."
        )
        impact = "Medium"
    elif path == "/contact":
        sug_title = "Contact GeneMeal Support | Meal Plan Subscription Help"
        sug_meta = (
            "Questions about your GeneMeal $34.97/mo weekly nutrigenomic meal plan subscription? "
            "Reach our support team quickly for account, billing, or plan assistance."
        )
        rationale = "Adds clear support intent and concise 145-char meta description for branded support searches."
        impact = "Low"
    else:
        return None

    # Only emit if different from current or current has length/missing issues
    if cur_title == sug_title and cur_meta == sug_meta:
        return None

    return {
        "page_url": page["url"],
        "path": path,
        "current_title": cur_title,
        "suggested_title": sug_title,
        "current_meta": cur_meta,
        "suggested_meta": sug_meta,
        "rationale": rationale,
        "expected_ctr_impact": impact,
    }



TITLE_MIN, TITLE_MAX = 30, 62
META_MIN, META_MAX = 110, 160
TITLE_AIM = 58
META_AIM = 155
_INVENTED_CLAIM_RE = re.compile(
    r"(#1|n[o°]\s*1|number one|world.?s best|guaranteed|100%|\b\d{2,}%\s*off|\b\$\d)",
    re.I,
)


def is_genemeal_target(target_url: str) -> bool:
    host = urlparse(target_url or "").hostname or ""
    host = host.rstrip(".").lower().removeprefix("www.")
    return host == "genemeal.onrender.com"


def _brand_from_host(host: str) -> str:
    host = (host or "").rstrip(".").lower().removeprefix("www.")
    label = host.split(".")[0] if host else "Site"
    return label.replace("-", " ").replace("_", " ").title() or "Site"


def _path_label(path: str) -> str:
    path = (path or "/").strip("/")
    if not path:
        return "Home"
    slug = path.split("/")[-1].replace("-", " ").replace("_", " ").strip()
    return slug.title() if slug else "Home"


def _trim_chars(text: str, max_len: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rsplit(" ", 1)[0].rstrip(" ,;:.-")
    if len(cut) < max(12, int(max_len * 0.55)):
        cut = text[:max_len].rstrip()
    return cut


def _generic_title(page: Dict[str, Any], brand: str) -> str:
    raw = (page.get("title") or "").strip()
    h1 = (page.get("h1_text") or "").strip()
    path = page.get("path") or "/"
    base = raw or h1 or _path_label(path) or brand
    base = re.sub(r"\s+", " ", base).strip()
    if len(base) > TITLE_MAX:
        return _trim_chars(base, TITLE_AIM)
    if len(base) < TITLE_MIN:
        pieces = [base]
        if brand and brand.lower() not in base.lower():
            pieces.append(brand)
        label = _path_label(path)
        if path not in ("", "/") and label.lower() not in " ".join(pieces).lower():
            pieces.append(label)
        # Join deterministically without inventing claims or numbers.
        candidate = " | ".join([p for p in pieces if p])
        if len(candidate) < TITLE_MIN and h1 and h1.lower() not in candidate.lower():
            candidate = f"{h1} | {candidate}" if candidate else h1
        if len(candidate) < TITLE_MIN:
            candidate = f"{candidate} | {brand} website".strip(" |")
        if len(candidate) < TITLE_MIN:
            candidate = f"{candidate} | {_path_label(path)} page title"
        return _trim_chars(candidate, TITLE_MAX)
    return base


def _generic_meta(page: Dict[str, Any], brand: str, title: str) -> str:
    raw = (page.get("meta_description") or "").strip()
    h1 = (page.get("h1_text") or "").strip()
    path = page.get("path") or "/"
    topic = h1 or title or _path_label(path) or brand
    if raw and META_MIN <= len(raw) <= META_MAX:
        return raw
    if raw and len(raw) > META_MAX:
        return _trim_chars(raw, META_AIM)
    parts = []
    if raw:
        parts.append(raw.rstrip(" ."))
    else:
        parts.append(topic.rstrip(" ."))
    if brand and brand.lower() not in " ".join(parts).lower():
        parts.append(f"Published by {brand}")
    label = _path_label(path)
    blob = ". ".join(parts) + "."
    if len(blob) < META_MIN:
        extra = (
            f" This {_path_label(path).lower()} page uses the site's own heading"
            f"{f' ({h1})' if h1 else ''} and on-page copy as the basis for a clearer snippet."
        )
        blob = blob.rstrip(".") + "." + extra
    return _trim_chars(blob, META_AIM)


def _suggest_ctr_rewrite_generic(page: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    host = urlparse(page.get("url") or "").hostname or ""
    brand = _brand_from_host(host)
    cur_title = (page.get("title") or "").strip() or "(missing)"
    cur_meta = (page.get("meta_description") or "").strip() or "(missing)"
    sug_title = _generic_title(page, brand)
    sug_meta = _generic_meta(page, brand, sug_title if sug_title else cur_title)

    # Never introduce promotional numbers or ranking claims that were not on the page.
    source = " ".join([cur_title if cur_title != "(missing)" else "", cur_meta if cur_meta != "(missing)" else "", page.get("h1_text") or ""])
    for candidate_name, candidate in (("title", sug_title), ("meta", sug_meta)):
        if _INVENTED_CLAIM_RE.search(candidate) and not _INVENTED_CLAIM_RE.search(source):
            # Strip the invented fragment by falling back to a trimmed source string.
            if candidate_name == "title":
                sug_title = _trim_chars(page.get("h1_text") or brand, TITLE_MAX)
            else:
                sug_meta = _trim_chars(
                    (page.get("meta_description") or page.get("h1_text") or f"Page information from {brand}."),
                    META_AIM,
                )

    if cur_title == sug_title and cur_meta == sug_meta:
        return None

    reasons = []
    if cur_title == "(missing)":
        reasons.append("the current title tag is missing")
    elif not (TITLE_MIN <= len(page.get("title") or "") <= TITLE_MAX):
        reasons.append(f"the current title is {len(page.get('title') or '')} characters (aim {TITLE_MIN}–{TITLE_MAX})")
    if cur_meta == "(missing)":
        reasons.append("the current meta description is missing")
    elif not (META_MIN <= len(page.get("meta_description") or "") <= META_MAX):
        reasons.append(
            f"the current meta description is {len(page.get('meta_description') or '')} characters (aim {META_MIN}–{META_MAX})"
        )
    if not reasons:
        reasons.append("a tighter snippet can use the visible heading and site name without adding unsubstantiated claims")

    title_gap = cur_title == "(missing)" or not (TITLE_MIN <= len(page.get("title") or "") <= TITLE_MAX)
    meta_gap = cur_meta == "(missing)" or not (META_MIN <= len(page.get("meta_description") or "") <= META_MAX)
    impact = "High" if (cur_title == "(missing)" or cur_meta == "(missing)") else ("Medium" if title_gap or meta_gap else "Low")

    return {
        "page_url": page.get("url") or "",
        "path": page.get("path") or "/",
        "current_title": cur_title,
        "suggested_title": sug_title,
        "current_meta": cur_meta,
        "suggested_meta": sug_meta,
        "rationale": "Suggested from the page's existing title, H1, and meta: " + "; ".join(reasons) + ".",
        "expected_ctr_impact": impact,
    }


def suggest_ctr_rewrite(page: Dict[str, Any], target_url: str = "") -> Optional[Dict[str, Any]]:
    if is_genemeal_target(target_url) or is_genemeal_target(page.get("url") or ""):
        return _suggest_ctr_rewrite_genemeal(page)
    return _suggest_ctr_rewrite_generic(page)


def analyze_crawl(crawl_data: Dict[str, Any]) -> Dict[str, Any]:
    robots_found = crawl_data["robots_found"]
    sitemap_found = crawl_data["sitemap_found"]
    status_cache = crawl_data["status_cache"]

    audited_pages: List[Dict[str, Any]] = []
    all_issues: List[Dict[str, Any]] = []
    rewrites: List[Dict[str, Any]] = []

    if not robots_found:
        all_issues.append(
            {
                "page_url": crawl_data["target_url"] + "/robots.txt",
                "severity": "high",
                "category": "Technical",
                "title": "robots.txt missing or unreachable",
                "detail": "Search crawlers could not retrieve a valid robots.txt file.",
                "recommendation": "Serve a valid /robots.txt with Sitemap directive and explicit Allow/Disallow rules.",
            }
        )

    if not sitemap_found:
        all_issues.append(
            {
                "page_url": crawl_data["target_url"] + "/sitemap.xml",
                "severity": "high",
                "category": "Technical",
                "title": "sitemap.xml missing or invalid",
                "detail": "No valid XML sitemap was found to guide search engine discovery.",
                "recommendation": "Publish /sitemap.xml listing all canonical indexable public URLs.",
            }
        )

    seen_titles: Dict[str, str] = {}
    seen_metas: Dict[str, str] = {}

    for raw in crawl_data["pages"]:
        url = raw["url"]
        path = raw["path"]
        status_code = raw["status_code"]
        html = raw.get("html", "")
        soup = BeautifulSoup(html, "html.parser") if html else BeautifulSoup("", "html.parser")

        title_tag = soup.find("title")
        title = (title_tag.get_text(" ", strip=True) if title_tag else "").strip()
        title_len = len(title)

        meta_desc_tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        meta_desc = (meta_desc_tag.get("content", "") if meta_desc_tag else "").strip()
        meta_desc_len = len(meta_desc)

        h1_tags = soup.find_all("h1")
        h1_count = len(h1_tags)
        h1_text = (h1_tags[0].get_text(" ", strip=True) if h1_tags else "").strip()
        h2_count = len(soup.find_all("h2"))

        canon_tag = soup.find("link", attrs={"rel": lambda v: v and "canonical" in [x.lower() for x in (v if isinstance(v, list) else [v])]})
        canonical_url = (canon_tag.get("href", "") if canon_tag else "").strip()

        def _meta_prop(prop: str) -> str:
            t = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
            return (t.get("content", "") if t else "").strip()

        og_title = _meta_prop("og:title")
        og_description = _meta_prop("og:description")
        og_image = _meta_prop("og:image")
        twitter_card = _meta_prop("twitter:card")
        json_ld_types = _extract_json_ld_types(soup)

        imgs = soup.find_all("img")
        images_total = len(imgs)
        images_missing_alt = sum(1 for im in imgs if not (im.get("alt") or "").strip())

        word_count = _visible_word_count(soup) if html else 0
        internal_links = raw.get("internal_links", [])
        broken_links = [l for l in internal_links if status_cache.get(l, 200) >= 400 or status_cache.get(l, 200) == 0]
        broken_links_count = len(broken_links)

        page_issues: List[Dict[str, Any]] = []

        def add_issue(severity: str, category: str, title_msg: str, detail: str, rec: str) -> None:
            iss = {
                "page_url": url,
                "severity": severity,
                "category": category,
                "title": title_msg,
                "detail": detail,
                "recommendation": rec,
            }
            page_issues.append(iss)
            all_issues.append(iss)

        # Scoring: CTR Readiness (30)
        ctr_score = 0.0
        if status_code == 200:
            if title:
                ctr_score += 6
                if 30 <= title_len <= 62:
                    ctr_score += 6
                else:
                    ctr_score += 3
                    add_issue(
                        "medium",
                        "CTR & Snippets",
                        f"Title length outside ideal SERP range ({title_len} chars) on {path}",
                        f"Current title \"{title}\" is {title_len} characters (ideal 30–62 chars to avoid truncation).",
                        "Tighten or expand the <title> to 45–60 characters with primary keyword + value hook.",
                    )
                if title in seen_titles:
                    add_issue(
                        "high",
                        "CTR & Snippets",
                        f"Duplicate <title> tag on {path}",
                        f"Shares identical title with {seen_titles[title]}.",
                        "Write a unique <title> reflecting this page's specific search intent.",
                    )
                else:
                    seen_titles[title] = path
            else:
                add_issue(
                    "critical",
                    "CTR & Snippets",
                    f"Missing <title> tag on {path}",
                    "Pages without a <title> fail to display a controlled headline in search results.",
                    "Add a unique, keyword-focused <title> tag (45–60 characters).",
                )

            if meta_desc:
                ctr_score += 6
                if 110 <= meta_desc_len <= 165:
                    ctr_score += 6
                else:
                    ctr_score += 3
                    add_issue(
                        "medium",
                        "CTR & Snippets",
                        f"Meta description length suboptimal ({meta_desc_len} chars) on {path}",
                        f"Current description is {meta_desc_len} chars; Google typically displays ~140–160 chars.",
                        "Rewrite meta description to 135–158 chars with a clear $34.97/mo subscription hook.",
                    )
                if meta_desc in seen_metas:
                    add_issue(
                        "medium",
                        "CTR & Snippets",
                        f"Duplicate meta description on {path}",
                        f"Matches meta description used on {seen_metas[meta_desc]}.",
                        "Craft a distinct meta description for each indexable URL.",
                    )
                else:
                    seen_metas[meta_desc] = path
            else:
                add_issue(
                    "high",
                    "CTR & Snippets",
                    f"Missing meta description on {path}",
                    "No <meta name='description'> found; search engines will auto-generate a snippet.",
                    "Add a persuasive 140–158 character meta description highlighting weekly nutrigenomic meal plans.",
                )

            social_pts = 0.0
            if og_title:
                social_pts += 1.5
            if og_description:
                social_pts += 1.5
            if og_image:
                social_pts += 1.5
            if twitter_card:
                social_pts += 1.5
            ctr_score += social_pts
            if social_pts < 6.0:
                missing_og = [
                    name
                    for name, val in [
                        ("og:title", og_title),
                        ("og:description", og_description),
                        ("og:image", og_image),
                        ("twitter:card", twitter_card),
                    ]
                    if not val
                ]
                add_issue(
                    "low",
                    "Social & OG",
                    f"Incomplete Open Graph / Twitter tags on {path}",
                    f"Missing tags: {', '.join(missing_og)}.",
                    "Add full Open Graph and Twitter summary_large_image tags for richer social & X shares.",
                )
        else:
            add_issue(
                "critical",
                "Technical",
                f"Non-200 HTTP status ({status_code}) on {path}",
                f"Crawler received HTTP {status_code} when requesting {url}.",
                "Ensure public indexable pages return HTTP 200 or redirect cleanly with 301.",
            )

        # Scoring: Technical (25)
        tech_score = 0.0
        if status_code == 200:
            tech_score += 8
        if canonical_url:
            tech_score += 7
        else:
            add_issue(
                "high",
                "Technical",
                f"Missing canonical link tag on {path}",
                "No <link rel='canonical'> tag detected in <head>.",
                f"Add <link rel='canonical' href='{url}'> to consolidate ranking signals.",
            )
        if robots_found and sitemap_found:
            if raw["in_sitemap"]:
                tech_score += 6
            else:
                tech_score += 3
                add_issue(
                    "low",
                    "Technical",
                    f"Crawled page {path} not listed in sitemap.xml",
                    f"{url} is indexable (200 OK) but absent from sitemap.xml.",
                    "Include all canonical indexable public URLs in /sitemap.xml.",
                )
        elif robots_found or sitemap_found:
            tech_score += 3

        if broken_links_count == 0:
            tech_score += 4
        else:
            add_issue(
                "high",
                "Technical",
                f"{broken_links_count} broken internal link(s) on {path}",
                f"Broken targets: {', '.join(broken_links[:4])}.",
                "Update or remove broken internal links so crawl budget and UX stay clean.",
            )

        # Scoring: Content (20)
        content_score = 0.0
        if h1_count == 1:
            content_score += 8
        elif h1_count == 0:
            add_issue(
                "high",
                "Content",
                f"Missing <h1> heading on {path}",
                "No primary <h1> heading found on the page.",
                "Add a single descriptive <h1> matching the page's primary topic.",
            )
        else:
            content_score += 4
            add_issue(
                "medium",
                "Content",
                f"Multiple <h1> tags ({h1_count}) on {path}",
                "Multiple H1 elements dilute primary topic hierarchy.",
                "Keep one primary <h1> per page and demote secondary headings to <h2>.",
            )

        if word_count >= 180:
            content_score += 7
        elif word_count >= 60:
            content_score += 4
            if path in ("/", "/pricing") or path.startswith("/research/"):
                add_issue(
                    "medium",
                    "Content",
                    f"Thin copy ({word_count} words) on {path}",
                    f"Only {word_count} indexable words detected; search engines prefer deeper topical context.",
                    "Expand with concise FAQ, positioning clarity ($34.97/mo weekly updates), and semantic subheadings.",
                )
        else:
            add_issue(
                "medium",
                "Content",
                f"Very thin content ({word_count} words) on {path}",
                "Minimal indexable text reduces keyword relevance.",
                "Add helpful copy explaining the page's value and clear next steps.",
            )

        if h2_count >= 1:
            content_score += 5
        else:
            add_issue(
                "low",
                "Content",
                f"No <h2> subheadings found on {path}",
                "Subheadings improve scannability and featured-snippet eligibility.",
                "Structure body sections with clear <h2> headings.",
            )

        # Scoring: Schema (15)
        schema_score = 0.0
        if json_ld_types:
            schema_score += 10
            rich_types = {"Product", "Offer", "SoftwareApplication", "Article", "BlogPosting", "FAQPage", "WebSite", "Organization"}
            if any(t in rich_types for t in json_ld_types):
                schema_score += 5
            else:
                schema_score += 2
        else:
            add_issue(
                "medium",
                "Structured Data",
                f"No JSON-LD structured data on {path}",
                "Missing application/ld+json schema limits rich result eligibility (pricing, FAQ, breadcrumbs).",
                "Add Schema.org JSON-LD (WebSite, SoftwareApplication/Offer at $34.97/mo, or FAQPage).",
            )

        # Scoring: Performance & Accessibility (10)
        perf_score = 0.0
        ms = raw["response_ms"]
        if ms < 650:
            perf_score += 5
        elif ms < 1500:
            perf_score += 3
        elif ms < 3000:
            perf_score += 1
        else:
            add_issue(
                "medium",
                "Performance",
                f"Slow TTFB/response ({ms:.0f} ms) on {path}",
                f"Page took {ms:.0f} ms to respond.",
                "Cache public HTML responses or reduce server work before first byte.",
            )

        if images_total == 0 or images_missing_alt == 0:
            perf_score += 5
        else:
            ratio = (images_total - images_missing_alt) / max(images_total, 1)
            perf_score += round(5 * ratio, 1)
            add_issue(
                "medium",
                "Accessibility",
                f"{images_missing_alt}/{images_total} image(s) missing alt text on {path}",
                "Missing alt attributes hurt image search indexing and screen-reader accessibility.",
                "Add descriptive alt text to every informative image.",
            )

        total_score = round(min(100.0, ctr_score + tech_score + content_score + schema_score + perf_score), 1)
        cat_scores = {
            "ctr_readiness": round(ctr_score, 1),
            "technical": round(tech_score, 1),
            "content": round(content_score, 1),
            "schema": round(schema_score, 1),
            "performance": round(perf_score, 1),
        }

        page_record = {
            "url": url,
            "path": path,
            "status_code": status_code,
            "response_ms": raw["response_ms"],
            "content_bytes": raw["content_bytes"],
            "word_count": word_count,
            "title": title,
            "title_len": title_len,
            "meta_description": meta_desc,
            "meta_desc_len": meta_desc_len,
            "h1_count": h1_count,
            "h1_text": h1_text,
            "canonical_url": canonical_url,
            "og_title": og_title,
            "og_description": og_description,
            "og_image": og_image,
            "twitter_card": twitter_card,
            "json_ld_types": json_ld_types,
            "images_total": images_total,
            "images_missing_alt": images_missing_alt,
            "internal_links_count": len(internal_links),
            "broken_links_count": broken_links_count,
            "in_sitemap": raw["in_sitemap"],
            "page_score": total_score,
            "category_scores": cat_scores,
            "issues": page_issues,
        }
        audited_pages.append(page_record)

        rw = suggest_ctr_rewrite(page_record, crawl_data.get("target_url") or "")
        if rw:
            rewrites.append(rw)

    # Sort issues by severity
    sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    all_issues.sort(key=lambda x: (sev_order.get(x["severity"], 9), x["page_url"]))

    if audited_pages:
        # Weight homepage & pricing slightly higher than legal pages
        weights = []
        for p in audited_pages:
            w = 2.5 if p["path"] == "/" else (2.0 if p["path"] in ("/pricing", "/about") or p["path"].startswith("/research/") else 1.0)
            weights.append(w)
        overall_score = sum(p["page_score"] * w for p, w in zip(audited_pages, weights)) / sum(weights)
        avg_ms = sum(p["response_ms"] for p in audited_pages) / len(audited_pages)
        total_bytes = sum(p["content_bytes"] for p in audited_pages)
    else:
        overall_score = 0.0
        avg_ms = 0.0
        total_bytes = 0

    sev_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for iss in all_issues:
        s = iss["severity"]
        if s in sev_counts:
            sev_counts[s] += 1

    # Aggregate category averages
    cat_avgs = {}
    if audited_pages:
        for k, max_pts in [("ctr_readiness", 30), ("technical", 25), ("content", 20), ("schema", 15), ("performance", 10)]:
            pct = sum(p["category_scores"][k] for p in audited_pages) / (len(audited_pages) * max_pts) * 100.0
            cat_avgs[k] = round(pct, 1)

    summary = {
        "severity_counts": sev_counts,
        "category_percentages": cat_avgs,
        "disallowed_skipped_count": crawl_data.get("disallowed_skipped_count", 0),
        "pages_with_schema": sum(1 for p in audited_pages if p["json_ld_types"]),
        "pages_missing_meta": sum(1 for p in audited_pages if not p["meta_description"]),
    }

    return {
        "pages": audited_pages,
        "issues": all_issues,
        "rewrites": rewrites,
        "overall_score": round(overall_score, 1),
        "avg_response_ms": round(avg_ms, 1),
        "total_bytes": total_bytes,
        "summary": summary,
    }
