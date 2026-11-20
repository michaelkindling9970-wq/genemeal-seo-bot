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
