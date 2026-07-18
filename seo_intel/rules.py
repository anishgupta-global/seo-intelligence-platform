"""
Enrich layer #1 — the DETERMINISTIC rule engine. NEVER AI.
Each check is a pure function over stored snapshots: free, instant, testable,
auditable. This is ~90% of SEO monitoring and the heart of the Part 2 argument.
"""
from __future__ import annotations
from collections import defaultdict
from .models import Page, Issue

SEVERITY = {
    "noindex_on_indexable_page": 1.00,
    "page_broken_5xx": 0.95,
    "page_broken_4xx": 0.90,
    "sitemap_broken_url": 0.85,
    "broken_internal_link": 0.80,
    "canonical_to_non_200": 0.80,
    "missing_title": 0.70,
    "duplicate_content": 0.65,
    "redirect_chain": 0.55,
    "duplicate_title": 0.50,
    "missing_h1": 0.45,
    "missing_canonical": 0.40,
    "internal_redirect_link": 0.35,
    "thin_content": 0.35,
    "missing_meta_description": 0.30,
    "duplicate_meta_description": 0.30,
    "title_length": 0.25,
    "description_length": 0.25,
    "multiple_h1": 0.25,
    "image_missing_alt": 0.20,
    "missing_lang": 0.20,
    "missing_viewport": 0.20,
    "not_in_sitemap": 0.20,
}


def run_rules(pages: dict[str, Page], status_map: dict, sitemap_norm: set, settings) -> list[Issue]:
    issues: list[Issue] = []
    add = lambda c, u, d: issues.append(Issue(c, u, SEVERITY.get(c, 0.3), d))
    titles, descs, hashes = defaultdict(list), defaultdict(list), defaultdict(list)

    for url, pg in pages.items():
        if pg.status >= 500:
            add("page_broken_5xx", url, f"server error {pg.status}"); continue
        if pg.status >= 400:
            add("page_broken_4xx", url, f"client error {pg.status}"); continue
        if len(pg.redirect_chain) >= 2:
            add("redirect_chain", url, f"{len(pg.redirect_chain)} hops -> {pg.final_url}")
        if "html" not in (pg.content_type or ""):
            continue

        robots = " ".join(filter(None, [pg.meta_robots, pg.x_robots or ""]))
        if "noindex" in robots:
            add("noindex_on_indexable_page", url, f"200 but noindex ({robots.strip()})")

        if not pg.title:
            add("missing_title", url, "no <title>")
        else:
            titles[pg.title.strip()].append(url)
            if not (settings.title_min <= len(pg.title) <= settings.title_max):
                add("title_length", url, f"title {len(pg.title)} chars (guide {settings.title_min}-{settings.title_max})")

        if not pg.description:
            add("missing_meta_description", url, "no meta description")
        else:
            descs[pg.description.strip()].append(url)
            if not (settings.desc_min <= len(pg.description) <= settings.desc_max):
                add("description_length", url, f"description {len(pg.description)} chars (guide {settings.desc_min}-{settings.desc_max})")

        if len(pg.h1s) == 0:
            add("missing_h1", url, "no <h1>")
        elif len(pg.h1s) > 1:
            add("multiple_h1", url, f"{len(pg.h1s)} <h1> tags")

        if not pg.canonical:
            add("missing_canonical", url, "no rel=canonical")
        else:
            from .collect import normalize_url
            cs = status_map.get(normalize_url(pg.canonical))
            if cs is not None and (cs == 0 or cs >= 400):
                add("canonical_to_non_200", url, f"canonical -> {pg.canonical} (status {cs})")

        if pg.content_hash:
            hashes[pg.content_hash].append(url)
        if 0 < pg.word_count < settings.thin_words:
            add("thin_content", url, f"only {pg.word_count} words")
        if pg.img_no_alt:
            add("image_missing_alt", url, f"{pg.img_no_alt}/{pg.img_total} images missing alt")
        if not pg.lang:
            add("missing_lang", url, "<html> has no lang attribute")
        if not pg.has_viewport:
            add("missing_viewport", url, "no responsive viewport meta")

        seen_bad = set()
        for link in pg.links_internal:
            st = status_map.get(link)
            if st is not None and (st == 0 or st >= 400) and link not in seen_bad:
                seen_bad.add(link); add("broken_internal_link", url, f"links to {link} (status {st})")
            elif st in (301, 302, 307, 308) and link not in seen_bad:
                seen_bad.add(link); add("internal_redirect_link", url, f"links to redirecting {link} ({st})")

    if sitemap_norm:
        for su in sitemap_norm:
            st = status_map.get(su)
            if st is not None and (st == 0 or st >= 400):
                add("sitemap_broken_url", su, f"in sitemap but returns {st}")
        for url, pg in pages.items():
            if 200 <= pg.status < 300 and "html" in (pg.content_type or "") and url not in sitemap_norm:
                add("not_in_sitemap", url, "reachable page not in sitemap.xml")

    for title, urls in titles.items():
        if len(urls) > 1:
            for u in urls:
                add("duplicate_title", u, f'title "{title[:50]}" shared by {len(urls)} pages')
    for _, urls in descs.items():
        if len(urls) > 1:
            for u in urls:
                add("duplicate_meta_description", u, f"meta description shared by {len(urls)} pages")
    for _, urls in hashes.items():
        if len(urls) > 1:
            for u in urls:
                add("duplicate_content", u, f"identical body content on {len(urls)} pages")

    return issues
