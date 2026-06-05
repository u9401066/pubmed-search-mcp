"""Tests for institutional_fetch (Phase 1 direct + Phase 2 EZproxy)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from pubmed_search.infrastructure.sources import institutional_fetch as ifetch
from pubmed_search.infrastructure.sources.institutional_fetch import (
    AccessDiagnosis,
    EZProxyConfig,
    ProbeResult,
    _normalize_cookies,
    classify_content,
    diagnose_access,
    load_cookies,
    probe_direct,
    probe_ezproxy,
    rewrite_to_ezproxy,
    safe_url_preview,
)

# ---------------------------------------------------------------------------
# rewrite_to_ezproxy
# ---------------------------------------------------------------------------


class TestRewriteToEzproxy:
    def test_rewrites_sciencedirect(self):
        out = rewrite_to_ezproxy(
            "https://www.sciencedirect.com/science/article/pii/S0001",
            "ezproxy.lib.ntu.edu.tw",
        )
        assert out == ("https://www-sciencedirect-com.ezproxy.lib.ntu.edu.tw/science/article/pii/S0001")

    def test_preserves_query_and_path(self):
        out = rewrite_to_ezproxy(
            "https://link.springer.com/article/10.1007/x?foo=1",
            "ez.example.edu",
        )
        assert out is not None
        assert "link-springer-com.ez.example.edu" in out
        assert "foo=1" in out

    def test_strips_leading_dot_and_trailing_slash(self):
        out = rewrite_to_ezproxy("https://a.b.com/x", ".ez.example.edu/")
        assert out is not None
        assert "a-b-com.ez.example.edu" in out

    def test_returns_none_for_non_http(self):
        assert rewrite_to_ezproxy("ftp://example.com/x", "ez.example.edu") is None
        assert rewrite_to_ezproxy("not a url", "ez.example.edu") is None

    def test_returns_none_when_no_proxy_host(self):
        assert rewrite_to_ezproxy("https://x.com/", "") is None


# ---------------------------------------------------------------------------
# _normalize_cookies
# ---------------------------------------------------------------------------


class TestNormalizeCookies:
    def test_array_form(self):
        raw = [
            {"name": "ezproxy", "value": "abc", "domain": ".x.edu"},
            {"name": "JSESSIONID", "value": "xyz"},
            {"value": "no-name"},  # ignored
        ]
        assert _normalize_cookies(raw) == {"ezproxy": "abc", "JSESSIONID": "xyz"}

    def test_storage_state_form(self):
        raw = {"cookies": [{"name": "a", "value": "1"}]}
        assert _normalize_cookies(raw) == {"a": "1"}

    def test_flat_dict_form(self):
        assert _normalize_cookies({"a": "1", "b": 2}) == {"a": "1", "b": "2"}

    def test_garbage_returns_empty(self):
        assert _normalize_cookies(None) == {}
        assert _normalize_cookies("string") == {}


# ---------------------------------------------------------------------------
# load_cookies
# ---------------------------------------------------------------------------


class TestLoadCookies:
    def test_load_from_file(self, tmp_path):
        f = tmp_path / "cookies.json"
        f.write_text(json.dumps([{"name": "a", "value": "1"}]), encoding="utf-8")
        assert load_cookies(cookie_file=str(f)) == {"a": "1"}

    def test_load_from_string(self):
        assert load_cookies(cookie_string="a=1; b=2 ; c=") == {"a": "1", "b": "2", "c": ""}

    def test_file_takes_precedence_then_string_adds(self, tmp_path):
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"a": "from-file"}), encoding="utf-8")
        out = load_cookies(cookie_file=str(f), cookie_string="b=from-string")
        assert out == {"a": "from-file", "b": "from-string"}

    def test_missing_file_returns_empty(self):
        assert load_cookies(cookie_file="/nonexistent/path.json") == {}

    def test_invalid_json_returns_empty(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not json", encoding="utf-8")
        assert load_cookies(cookie_file=str(f)) == {}


# ---------------------------------------------------------------------------
# classify_content
# ---------------------------------------------------------------------------


class TestClassifyContent:
    def test_empty(self):
        assert classify_content("text/html", b"") == "empty"

    def test_pdf_by_content_type(self):
        assert classify_content("application/pdf", b"any") == "pdf"

    def test_pdf_by_magic_bytes(self):
        assert classify_content("application/octet-stream", b"%PDF-1.4\nfoo") == "pdf"

    def test_paywall(self):
        body = b"<html><body>" + b"x" * 100 + b"please purchase access to view" + b"</body></html>"
        assert classify_content("text/html", body) == "paywall"

    def test_login_required(self):
        body = b"<html>" + b"sign in via your institution" + b"</html>"
        assert classify_content("text/html", body) == "login_required"

    def test_paywall_beats_fulltext_signals(self):
        body = (
            b"<html><article>"
            + b"x" * 5000
            + b" full text content "
            + b"purchase access to read more"
            + b"</article></html>"
        )
        assert classify_content("text/html", body) == "paywall"

    def test_fulltext_requires_min_length(self):
        # Has fulltext phrase but body too short
        body = b"<html><article>short</article></html>"
        assert classify_content("text/html", body) == "unknown"

    def test_fulltext_html(self):
        body = b"<html><article>" + b"x" * 5000 + b" References</section></article></html>"
        assert classify_content("text/html", body) == "fulltext_html"

    def test_non_html_unknown(self):
        assert classify_content("application/json", b'{"a":1}') == "unknown"


# ---------------------------------------------------------------------------
# EZProxyConfig
# ---------------------------------------------------------------------------


class TestEZProxyConfig:
    def test_is_configured_false_by_default(self):
        cfg = EZProxyConfig()
        assert cfg.is_configured is False

    def test_is_configured_true_when_all_set(self):
        cfg = EZProxyConfig(
            proxy_host="ez.x.edu",
            cookie_file="/tmp/c.json",
            enabled=True,
        )
        assert cfg.is_configured is True

    def test_is_configured_requires_enabled(self):
        cfg = EZProxyConfig(proxy_host="ez.x.edu", cookie_string="a=1", enabled=False)
        assert cfg.is_configured is False

    def test_from_env_reads_settings(self):
        fake_settings = MagicMock()
        fake_settings.ezproxy_host = "ez.x.edu"
        fake_settings.ezproxy_cookie_file = "/tmp/c.json"
        fake_settings.ezproxy_cookie = ""
        fake_settings.ezproxy_enabled = True
        with patch.object(ifetch, "load_settings", return_value=fake_settings):
            cfg = EZProxyConfig.from_env()
        assert cfg.proxy_host == "ez.x.edu"
        assert cfg.enabled is True
        assert cfg.is_configured is True


# ---------------------------------------------------------------------------
# probe_direct  (mock _probe_url)
# ---------------------------------------------------------------------------


def _make_response(*, status: int = 200, body: bytes = b"", content_type: str = "text/html") -> httpx.Response:
    """Build a synthetic httpx.Response anchored to a real URL."""
    request = httpx.Request("GET", "https://publisher.example/article/1")
    return httpx.Response(
        status_code=status,
        headers={"content-type": content_type},
        content=body,
        request=request,
    )


class TestProbeDirect:
    async def test_no_doi_returns_error(self):
        result = await probe_direct("")
        assert result.attempted is True
        assert result.success is False
        assert result.error == "no DOI"

    async def test_fulltext_success(self):
        big_body = b"<html><article>" + b"x" * 5000 + b" References</section></article></html>"
        fake_resp = _make_response(status=200, body=big_body)

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            return fake_resp, [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await probe_direct("10.1000/test")

        assert result.attempted is True
        assert result.success is True
        assert result.content_class == "fulltext_html"
        assert result.status_code == 200
        assert "directly" in (result.advice or "").lower()

    async def test_paywall_failure_has_advice(self):
        body = b"<html>" + b"x" * 200 + b"purchase access to this article</html>"
        fake_resp = _make_response(status=200, body=body)

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            return fake_resp, [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await probe_direct("10.1000/test")

        assert result.success is False
        assert result.content_class == "paywall"
        assert "vpn" in (result.advice or "").lower() or "ezproxy" in (result.advice or "").lower()

    async def test_network_error_recorded(self):
        async def fake_probe(url, *, cookies=None, timeout=15.0):
            return None, [], "Timeout: too slow"

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await probe_direct("10.1000/test")

        assert result.success is False
        assert "Timeout" in (result.error or "")
        assert result.advice  # has remediation hint


# ---------------------------------------------------------------------------
# probe_ezproxy
# ---------------------------------------------------------------------------


class TestProbeEzproxy:
    async def test_not_configured(self):
        cfg = EZProxyConfig()  # disabled
        result = await probe_ezproxy("10.1000/x", config=cfg)
        assert result.attempted is False
        assert result.success is False
        assert "not configured" in (result.error or "").lower()

    async def test_missing_cookies(self, tmp_path):
        # Configured but cookie file is empty/garbage
        empty = tmp_path / "empty.json"
        empty.write_text("[]", encoding="utf-8")
        cfg = EZProxyConfig(
            proxy_host="ez.x.edu",
            cookie_file=str(empty),
            enabled=True,
        )

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            # DOI resolves to a publisher URL
            return _make_response(status=200, body=b"redirected"), [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await probe_ezproxy("10.1000/x", config=cfg)

        assert result.attempted is True
        assert result.success is False
        assert "cookies" in (result.error or "").lower()

    async def test_success_with_cookies(self, tmp_path):
        cookies_file = tmp_path / "c.json"
        cookies_file.write_text(
            json.dumps([{"name": "session", "value": "abc"}]),
            encoding="utf-8",
        )
        cfg = EZProxyConfig(
            proxy_host="ez.x.edu",
            cookie_file=str(cookies_file),
            enabled=True,
        )

        big_body = b"<html><article>" + b"x" * 5000 + b" References</section></article></html>"
        call_count = {"n": 0}

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # Step 1: DOI -> publisher URL (no cookies expected)
                return _make_response(status=200, body=b""), [url], None
            # Step 2: EZproxy URL with replayed cookies
            assert cookies and cookies.get("session") == "abc"
            return _make_response(status=200, body=big_body), [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await probe_ezproxy("10.1000/x", config=cfg)

        assert result.attempted is True
        assert result.success is True
        assert result.content_class == "fulltext_html"
        assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# diagnose_access
# ---------------------------------------------------------------------------


class TestDiagnoseAccess:
    async def test_no_doi_only_openurl(self):
        with patch(
            "pubmed_search.infrastructure.sources.openurl.get_openurl_link",
            return_value="https://library.x.edu/openurl?pmid=1",
        ):
            diag = await diagnose_access(pmid="12345", doi=None)

        assert isinstance(diag, AccessDiagnosis)
        assert diag.doi is None
        assert diag.openurl is not None
        assert diag.probes == []
        assert "No DOI" in diag.summary

    async def test_success_via_direct(self):
        good = ProbeResult(
            path="direct",
            attempted=True,
            success=True,
            status_code=200,
            content_class="fulltext_html",
        )
        ezfail = ProbeResult(path="ezproxy", attempted=False, error="EZproxy not configured")

        with (
            patch.object(ifetch, "probe_direct", AsyncMock(return_value=good)),
            patch.object(ifetch, "probe_ezproxy", AsyncMock(return_value=ezfail)),
            patch(
                "pubmed_search.infrastructure.sources.openurl.get_openurl_link",
                return_value=None,
            ),
        ):
            diag = await diagnose_access(doi="10.1000/x")

        assert diag.recommended_path == "direct"
        assert "direct" in diag.summary.lower()
        assert len(diag.probes) == 2

    async def test_all_fail_recommends_openurl(self):
        d = ProbeResult(path="direct", attempted=True, success=False, advice="paywall hit")
        e = ProbeResult(path="ezproxy", attempted=False, error="EZproxy not configured")

        with (
            patch.object(ifetch, "probe_direct", AsyncMock(return_value=d)),
            patch.object(ifetch, "probe_ezproxy", AsyncMock(return_value=e)),
            patch(
                "pubmed_search.infrastructure.sources.openurl.get_openurl_link",
                return_value="https://library.x.edu/openurl?doi=10.1000/x",
            ),
        ):
            diag = await diagnose_access(doi="10.1000/x")

        # ezproxy was not attempted, so fallback summary picks direct probe advice
        assert diag.recommended_path in {"openurl", "direct"}
        assert diag.openurl is not None

    async def test_respects_try_flags(self):
        with (
            patch.object(ifetch, "probe_direct", AsyncMock()) as md,
            patch.object(ifetch, "probe_ezproxy", AsyncMock()) as me,
            patch(
                "pubmed_search.infrastructure.sources.openurl.get_openurl_link",
                return_value=None,
            ),
        ):
            await diagnose_access(doi="10.1000/x", try_direct=False, try_ezproxy=False)

        md.assert_not_called()
        me.assert_not_called()


# ---------------------------------------------------------------------------
# safe_url_preview
# ---------------------------------------------------------------------------


class TestSafeUrlPreview:
    def test_empty(self):
        assert safe_url_preview(None) == ""
        assert safe_url_preview("") == ""

    def test_strips_control_chars(self):
        assert safe_url_preview("https://x.com/\x00\x07/y") == "https://x.com//y"

    def test_truncates(self):
        long = "https://x.com/" + "a" * 200
        out = safe_url_preview(long, max_len=50)
        assert len(out) == 50
        assert out.endswith("…")


# ---------------------------------------------------------------------------
# OpenURL fallback emits access_mode
# ---------------------------------------------------------------------------


class TestFallbackAccessMode:
    def test_pmc_is_open_access(self):
        from pubmed_search.infrastructure.sources.openurl import (
            get_fulltext_link_with_fallback,
        )

        result = get_fulltext_link_with_fallback(
            {"pmid": "1", "pmc_id": "PMC123", "doi": "10.1/x"},
            include_openurl=False,
        )
        assert result["access_mode"] == "open_access"
        # DOI gets pushed into alternatives with publisher_direct mode
        assert any(alt.get("access_mode") == "publisher_direct" for alt in result.get("alternatives", []))

    def test_doi_only_is_publisher_direct(self):
        from pubmed_search.infrastructure.sources.openurl import (
            get_fulltext_link_with_fallback,
        )

        result = get_fulltext_link_with_fallback(
            {"pmid": "1", "doi": "10.1/x"},
            include_openurl=False,
        )
        assert result["access_mode"] == "publisher_direct"


# ---------------------------------------------------------------------------
# fetch_direct / fetch_ezproxy (body-returning probes)
# ---------------------------------------------------------------------------


class TestFetchDirect:
    async def test_returns_body_on_success(self):
        body = b"<html><article>" + b"x" * 5000 + b" References</article></html>"
        fake_resp = _make_response(status=200, body=body)

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            return fake_resp, [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await ifetch.fetch_direct("10.1/x")

        assert result.success is True
        assert result.body == body
        assert result.content_type == "text/html"

    async def test_default_probe_direct_does_not_keep_body(self):
        body = b"<html><article>" + b"x" * 5000 + b" References</article></html>"
        fake_resp = _make_response(status=200, body=body)

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            return fake_resp, [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await probe_direct("10.1/x")

        # Diagnostic probe must never carry the body field
        assert result.body is None

    async def test_to_dict_excludes_body(self):
        body = b"<html><article>" + b"x" * 5000 + b" References</article></html>"
        fake_resp = _make_response(status=200, body=body)

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            return fake_resp, [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await ifetch.fetch_direct("10.1/x")

        as_dict = result.to_dict()
        assert "body" not in as_dict


class TestFetchEzproxy:
    async def test_returns_body_on_success(self, tmp_path):
        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text(json.dumps([{"name": "EZP", "value": "abc"}]))
        cfg = EZProxyConfig(
            proxy_host="ezp.example.edu",
            cookie_file=str(cookie_file),
            cookie_string="",
            enabled=True,
        )

        body = b"<html><article>" + b"x" * 5000 + b" References</article></html>"
        fake_resp = _make_response(status=200, body=body)

        async def fake_probe(url, *, cookies=None, timeout=15.0):
            return fake_resp, [url], None

        with patch.object(ifetch, "_probe_url", side_effect=fake_probe):
            result = await ifetch.fetch_ezproxy("10.1/x", config=cfg)

        assert result.success is True
        assert result.body == body


# ---------------------------------------------------------------------------
# InstitutionalFulltextClient
# ---------------------------------------------------------------------------


class TestInstitutionalFulltextClient:
    async def test_direct_success_returns_text(self):
        from pubmed_search.infrastructure.sources.institutional_fulltext import (
            InstitutionalFulltextClient,
        )

        body = b"<html><body><article>" + (b"Lorem ipsum dolor sit amet. " * 100) + b"</article></body></html>"
        probe = ProbeResult(
            path="direct",
            attempted=True,
            success=True,
            final_url="https://publisher.example/x",
            status_code=200,
            content_class="fulltext_html",
            body=body,
            content_type="text/html",
        )

        with patch(
            "pubmed_search.infrastructure.sources.institutional_fulltext.fetch_direct",
            AsyncMock(return_value=probe),
        ):
            client = InstitutionalFulltextClient(config=EZProxyConfig(proxy_host="", cookie_file="", cookie_string=""))
            outcome = await client.get_fulltext_by_doi("10.1/x")

        assert outcome.success is True
        assert outcome.source_used == "direct"
        assert outcome.text is not None
        assert "Lorem ipsum" in outcome.text

    async def test_direct_paywall_falls_through_when_ezproxy_unconfigured(self):
        from pubmed_search.infrastructure.sources.institutional_fulltext import (
            InstitutionalFulltextClient,
        )

        probe = ProbeResult(
            path="direct",
            attempted=True,
            success=False,
            content_class="paywall",
        )
        with patch(
            "pubmed_search.infrastructure.sources.institutional_fulltext.fetch_direct",
            AsyncMock(return_value=probe),
        ):
            client = InstitutionalFulltextClient(config=EZProxyConfig(proxy_host="", cookie_file="", cookie_string=""))
            outcome = await client.get_fulltext_by_doi("10.1/x")

        assert outcome.success is False

    async def test_direct_pdf_success_is_not_discarded(self):
        from pubmed_search.infrastructure.sources.institutional_fulltext import (
            InstitutionalFulltextClient,
        )

        probe = ProbeResult(
            path="direct",
            attempted=True,
            success=True,
            final_url="https://publisher.example/paper.pdf",
            status_code=200,
            content_class="pdf",
            body=b"%PDF-1.4 content",
            content_type="application/pdf",
        )
        with patch(
            "pubmed_search.infrastructure.sources.institutional_fulltext.fetch_direct",
            AsyncMock(return_value=probe),
        ):
            client = InstitutionalFulltextClient(config=EZProxyConfig(proxy_host="", cookie_file="", cookie_string=""))
            outcome = await client.get_fulltext_by_doi("10.1/x")

        assert outcome.success is True
        assert outcome.content_class == "pdf"
        assert outcome.final_url == "https://publisher.example/paper.pdf"
        assert outcome.source_used == "direct"

    async def test_no_doi_returns_failure(self):
        from pubmed_search.infrastructure.sources.institutional_fulltext import (
            InstitutionalFulltextClient,
        )

        client = InstitutionalFulltextClient(config=EZProxyConfig(proxy_host="", cookie_file="", cookie_string=""))
        outcome = await client.get_fulltext_by_doi("")
        assert outcome.success is False
        assert outcome.error == "no DOI"

    async def test_ezproxy_used_when_direct_fails_and_configured(self, tmp_path):
        from pubmed_search.infrastructure.sources.institutional_fulltext import (
            InstitutionalFulltextClient,
        )

        cookie_file = tmp_path / "cookies.json"
        cookie_file.write_text(json.dumps([{"name": "EZP", "value": "abc"}]))
        cfg = EZProxyConfig(
            proxy_host="ezp.example.edu",
            cookie_file=str(cookie_file),
            cookie_string="",
            enabled=True,
        )

        direct_probe = ProbeResult(path="direct", success=False, content_class="paywall")
        body = (
            b"<html><body><article>" + (b"Detailed methods and results section. " * 100) + b"</article></body></html>"
        )
        ezp_probe = ProbeResult(
            path="ezproxy",
            attempted=True,
            success=True,
            final_url="https://ezp.example.edu/x",
            status_code=200,
            content_class="fulltext_html",
            body=body,
            content_type="text/html",
        )

        with (
            patch(
                "pubmed_search.infrastructure.sources.institutional_fulltext.fetch_direct",
                AsyncMock(return_value=direct_probe),
            ),
            patch(
                "pubmed_search.infrastructure.sources.institutional_fulltext.fetch_ezproxy",
                AsyncMock(return_value=ezp_probe),
            ),
        ):
            client = InstitutionalFulltextClient(config=cfg)
            outcome = await client.get_fulltext_by_doi("10.1/x")

        assert outcome.success is True
        assert outcome.source_used == "ezproxy"
        assert outcome.text and "Detailed methods" in outcome.text


# ---------------------------------------------------------------------------
# HTML extractor
# ---------------------------------------------------------------------------


class TestExtractFulltext:
    def test_extracts_article_body(self):
        from pubmed_search.infrastructure.sources.institutional_extract import (
            extract_fulltext,
        )

        html = (
            b"<html><head><title>My Paper</title></head>"
            b"<body><article>" + (b"This is the article body. " * 200) + b"</article></body></html>"
        )
        result = extract_fulltext(html, "https://publisher.example/x")
        assert result is not None
        assert result["text"]
        assert len(result["text"]) >= 500

    def test_returns_none_for_paywall_stub(self):
        from pubmed_search.infrastructure.sources.institutional_extract import (
            extract_fulltext,
        )

        html = b"<html><body>Please log in.</body></html>"
        assert extract_fulltext(html, "https://publisher.example/x") is None

    def test_handles_empty_bytes(self):
        from pubmed_search.infrastructure.sources.institutional_extract import (
            extract_fulltext,
        )

        assert extract_fulltext(b"", "https://x") is None
