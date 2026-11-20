from seo_bot.analyzer import suggest_ctr_rewrite, _suggest_ctr_rewrite_genemeal, is_genemeal_target


def _page(**kwargs):
    base = {
        "url": "https://example.com/",
        "path": "/",
        "title": "",
        "meta_description": "",
        "h1_text": "Example Domain",
    }
    base.update(kwargs)
    return base


def test_genemeal_rewrites_unchanged():
    assert is_genemeal_target("https://genemeal.onrender.com/")
    page = _page(
        url="https://genemeal.onrender.com/",
        path="/",
        title="Nutrigenomics Meal Plans from Your DNA | GeneMeal",
        meta_description="x" * 40,
        h1_text="Nutrigenomics meal plans",
    )
    rw = suggest_ctr_rewrite(page, "https://genemeal.onrender.com")
    assert rw is not None
    assert rw["suggested_title"] == "GeneMeal: Weekly Nutrigenomic Meal Plans ($34.97/mo)"
    assert "$34.97/month" in rw["suggested_meta"]
    # Same helper used by the original path
    assert _suggest_ctr_rewrite_genemeal(page)["suggested_title"] == rw["suggested_title"]


def test_generic_fills_missing_title_and_meta_within_limits():
    page = _page(title="", meta_description="", h1_text="Example Domain")
    rw = suggest_ctr_rewrite(page, "https://example.com")
    assert rw is not None
    assert 30 <= len(rw["suggested_title"]) <= 62
    assert 110 <= len(rw["suggested_meta"]) <= 160
    assert "Example" in rw["suggested_title"] or "Example Domain" in rw["suggested_title"]
    # No invented stats / prices
    assert "$" not in rw["suggested_title"]
    assert "$" not in rw["suggested_meta"]
    assert "100%" not in rw["suggested_meta"]
    assert "#1" not in rw["suggested_title"]


def test_generic_trims_overlong_title_and_meta():
    long_title = "Comprehensive Guide to Understanding Example Domain Documentation " * 3
    long_meta = "This is a very long meta description that repeats the heading and would be truncated in a search snippet. " * 4
    page = _page(path="/about", title=long_title, meta_description=long_meta, h1_text="About")
    rw = suggest_ctr_rewrite(page, "https://example.com/about")
    assert rw is not None
    assert len(rw["suggested_title"]) <= 62
    assert len(rw["suggested_meta"]) <= 160
    # Trimmed from the original wording, not replaced with promotional claims
    assert "Example" in rw["suggested_title"] or "Comprehensive" in rw["suggested_title"]
    assert "100%" not in rw["suggested_meta"]
    assert "$34.97" not in rw["suggested_title"]


def test_generic_does_not_invent_numeric_claims():
    page = _page(path="/pricing", title="Pricing", meta_description="Our pricing page.", h1_text="Pricing")
    rw = suggest_ctr_rewrite(page, "https://example.com/pricing")
    assert rw is not None
    blob = rw["suggested_title"] + " " + rw["suggested_meta"]
    assert "$" not in blob
    assert "guaranteed" not in blob.lower()
    assert "world's best" not in blob.lower()


from seo_bot.analyzer import analyze_crawl
from seo_bot.keywords import _classify_keyword


def _crawl(pages, target="https://genemeal.onrender.com"):
    return {
        "target_url": target,
        "robots_found": True,
        "sitemap_found": True,
        "status_cache": {p["url"]: 200 for p in pages},
        "disallowed_skipped_count": 0,
        "sitemap_urls": [p["url"] for p in pages],
        "pages": pages,
    }


def _raw(path, title, meta, og_title=None, h1="Heading"):
    og = og_title if og_title is not None else title
    html = f"""
    <html><head>
      <title>{title}</title>
      <meta name="description" content="{meta}">
      <link rel="canonical" href="https://genemeal.onrender.com{path}">
      <meta property="og:title" content="{og}">
      <meta property="og:description" content="{meta}">
      <meta property="og:image" content="https://genemeal.onrender.com/static/og.png">
      <meta name="twitter:card" content="summary_large_image">
      <script type="application/ld+json">{{"@type":"WebSite"}}</script>
    </head><body><h1>{h1}</h1><h2>Section</h2><p>{"word " * 80}</p></body></html>
    """
    return {
        "url": f"https://genemeal.onrender.com{path}",
        "path": path,
        "status_code": 200,
        "html": html,
        "internal_links": [],
        "in_sitemap": True,
        "response_ms": 40,
        "content_bytes": len(html),
        "title": title,
        "meta_description": meta,
        "h1_text": h1,
    }


def test_legal_pages_get_genemeal_rewrite_suggestions():
    privacy = _suggest_ctr_rewrite_genemeal(_page(
        url="https://genemeal.onrender.com/privacy",
        path="/privacy",
        title="Privacy Policy — GeneMeal",
        meta_description="How GeneMeal collects, encrypts, uses and deletes your DNA file, marker notes and billing records.",
    ))
    assert privacy is not None
    assert privacy["suggested_title"] == "Privacy Policy | How GeneMeal Handles Your Data"
    assert "Not a DNA test or medical advice" in privacy["suggested_meta"]
    assert 30 <= len(privacy["suggested_title"]) <= 60
    assert 110 <= len(privacy["suggested_meta"]) <= 155

    unsub = _suggest_ctr_rewrite_genemeal(_page(
        url="https://genemeal.onrender.com/unsubscribe",
        path="/unsubscribe",
        title="Unsubscribe — GeneMeal",
        meta_description="x" * 194,
    ))
    assert unsub is not None
    assert "DNA" not in unsub["suggested_title"]
    assert "Cancel" in unsub["suggested_title"] or "Unsubscribe" in unsub["suggested_title"]
    assert 110 <= len(unsub["suggested_meta"]) <= 155


def test_legal_meta_recommendation_avoids_subscription_hook():
    pages = [_raw(
        "/privacy",
        "Privacy Policy — GeneMeal",
        "How GeneMeal collects, encrypts, uses and deletes your DNA file, marker notes and billing records.",
        og_title="Privacy Policy — GeneMeal",
    )]
    result = analyze_crawl(_crawl(pages))
    recs = " ".join(i["recommendation"] for i in result["issues"] if "privacy" in i["page_url"])
    assert recs
    assert "$34.97" not in recs
    assert "subscription hook" in recs.lower() or "legal" in recs.lower()


def test_generic_site_missing_meta_does_not_mention_genemeal_price():
    html = "<html><head><title>About Example Domain Services Today</title></head><body><h1>About</h1><p>Hi</p></body></html>"
    pages = [{
        "url": "https://example.com/about",
        "path": "/about",
        "status_code": 200,
        "html": html,
        "internal_links": [],
        "in_sitemap": True,
        "response_ms": 20,
        "content_bytes": len(html),
        "title": "About Example Domain Services Today",
        "meta_description": "",
        "h1_text": "About",
    }]
    result = analyze_crawl(_crawl(pages, target="https://example.com"))
    recs = " ".join(i["recommendation"] for i in result["issues"])
    assert "$34.97" not in recs
    assert "nutrigenomic" not in recs.lower()
    assert "DNA" not in recs


def test_og_title_mismatch_is_flagged():
    pages = [_raw(
        "/pricing",
        "GeneMeal Pricing: $34.97/mo Nutrigenomic Meal Plans",
        "Simple $34.97/month meal-planning subscription with fresh weekly nutrigenomic meal plan updates. Cancel anytime. Not a DNA test or medical advice.",
        og_title="Pricing — Nutrigenomics Meal Plans | GeneMeal",
    )]
    result = analyze_crawl(_crawl(pages))
    titles = [i["title"] for i in result["issues"]]
    assert any("og:title does not match" in t for t in titles)


def test_default_keyword_angle_avoids_dna_test_framing():
    row = _classify_keyword("personalized meal plan", "personalized meal plan")
    assert "not a DNA test" in row["suggested_angle"]
    assert "DNA files power" not in row["suggested_angle"]
