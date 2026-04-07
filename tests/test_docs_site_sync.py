from __future__ import annotations

import json

from scripts.build_docs_site import EMBEDDED_CONTENT_FILE, OUTPUT_DIR, PAGES, _render_page, _route_map


def _load_embedded_pages() -> dict[str, str]:
    prefix = "window.DOC_PAGE_CONTENT = "
    raw = EMBEDDED_CONTENT_FILE.read_text(encoding="utf-8")
    assert raw.startswith(prefix)

    payload = raw.removeprefix(prefix).strip()
    payload = payload.removesuffix(";")

    return json.loads(payload)


def test_overview_pages_match_generated_sources() -> None:
    route_map = _route_map()
    embedded_pages = _load_embedded_pages()

    for slug, title, source_path in PAGES[:2]:
        expected = _render_page(slug, title, source_path, route_map)
        generated = (OUTPUT_DIR / f"{slug}.md").read_text(encoding="utf-8")

        assert generated == expected
        assert embedded_pages[slug] == expected
