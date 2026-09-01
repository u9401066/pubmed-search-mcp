"""
Tests for vision-based search tools.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from pubmed_search.infrastructure.http.safe_outbound import SafeFetchResult
from pubmed_search.presentation.mcp_server.tools.vision_search import (
    InlineImageSource,
    fetch_image_as_base64,
    is_base64_image,
    is_valid_url,
    parse_data_uri,
    register_vision_tools,
)


class TestURLValidation:
    """Tests for URL validation."""

    async def test_valid_https_url(self):
        assert is_valid_url("https://example.com/image.png") is True

    async def test_valid_http_url(self):
        assert is_valid_url("http://example.com/image.jpg") is True

    async def test_invalid_ftp_url(self):
        assert is_valid_url("ftp://example.com/file") is False

    async def test_invalid_not_url(self):
        assert is_valid_url("not-a-url") is False

    async def test_invalid_empty(self):
        assert is_valid_url("") is False


class TestBase64Detection:
    """Tests for base64 image detection."""

    async def test_data_uri(self):
        data_uri = "data:image/png;base64,iVBORw0KGgo="
        assert is_base64_image(data_uri) is True

    async def test_raw_base64_long(self):
        raw = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 100).decode()
        assert is_base64_image(raw) is True

    async def test_non_image_base64_is_rejected(self):
        raw = base64.b64encode(b"x" * 100).decode()
        assert is_base64_image(raw) is False

    async def test_short_string(self):
        assert is_base64_image("abc") is False

    async def test_invalid_base64(self):
        assert is_base64_image("!@#$%^&*()") is False


class TestDataURIParsing:
    """Tests for data URI parsing."""

    async def test_parse_png(self):
        data_uri = "data:image/png;base64,iVBORw0KGgo="
        mime, data = parse_data_uri(data_uri)
        assert mime == "image/png"
        assert data == "iVBORw0KGgo="

    async def test_parse_jpeg(self):
        data_uri = "data:image/jpeg;base64,/9j/4AAQ"
        mime, data = parse_data_uri(data_uri)
        assert mime == "image/jpeg"
        assert data == "/9j/4AAQ"

    async def test_invalid_format(self):
        with pytest.raises(ValueError):
            parse_data_uri("not-a-data-uri")


class TestFetchImage:
    """Tests for image fetching."""

    @pytest.mark.asyncio
    async def test_fetch_valid_image(self):
        """Test fetching a valid image URL."""
        request = httpx.Request("GET", "https://example.com/image.png")
        response = httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"\x89PNG\r\n\x1a\n",
            request=request,
        )

        with patch(
            "pubmed_search.presentation.mcp_server.tools.vision_search.fetch_public_url",
            AsyncMock(return_value=SafeFetchResult(response=response, redirect_chain=("https://example.com/…",))),
        ):
            mime, data = await fetch_image_as_base64("https://example.com/image.png")

            assert mime == "image/png"
            assert len(data) > 0

    @pytest.mark.asyncio
    async def test_invalid_url(self):
        """Test with invalid URL."""
        with pytest.raises(ValueError, match="Invalid URL"):
            await fetch_image_as_base64("not-a-url")

    @pytest.mark.asyncio
    async def test_mime_must_match_magic_bytes(self):
        request = httpx.Request("GET", "https://example.com/image.png")
        response = httpx.Response(
            200,
            headers={"content-type": "image/png"},
            content=b"\xff\xd8\xff\xe0fake-jpeg",
            request=request,
        )

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.vision_search.fetch_public_url",
                AsyncMock(return_value=SafeFetchResult(response=response, redirect_chain=())),
            ),
            pytest.raises(ValueError, match="does not match"),
        ):
            await fetch_image_as_base64("https://example.com/image.png")

    @pytest.mark.asyncio
    async def test_response_requires_image_mime(self):
        request = httpx.Request("GET", "https://example.com/image.png")
        response = httpx.Response(200, content=b"\x89PNG\r\n\x1a\n", request=request)

        with (
            patch(
                "pubmed_search.presentation.mcp_server.tools.vision_search.fetch_public_url",
                AsyncMock(return_value=SafeFetchResult(response=response, redirect_chain=())),
            ),
            pytest.raises(ValueError, match="MIME"),
        ):
            await fetch_image_as_base64("https://example.com/image.png")


class TestVisionToolsRegistration:
    """Tests for tool registration."""

    async def test_register_tools(self):
        """Test that vision tools can be registered."""
        mock_mcp = MagicMock()
        mock_mcp.tool = MagicMock(return_value=lambda f: f)

        register_vision_tools(mock_mcp)

        # Should register 1 tool (reverse_image_search_pubmed merged in v0.3.1)
        assert mock_mcp.tool.call_count == 1


class TestAnalyzeFigureForSearch:
    """Tests for prepare_figure_search tool."""

    @pytest.mark.asyncio
    async def test_no_input_error(self):
        """Test error when no image provided."""
        mock_mcp = MagicMock()
        tools = {}

        def capture_tool():
            def decorator(func):
                tools[func.__name__] = func
                return func

            return decorator

        mock_mcp.tool = capture_tool
        register_vision_tools(mock_mcp)

        with pytest.raises(TypeError, match="source"):
            await tools["prepare_figure_search"]()

    @pytest.mark.asyncio
    async def test_with_data_uri(self):
        """Test with valid data URI."""
        mock_mcp = MagicMock()
        tools = {}

        def capture_tool():
            def decorator(func):
                tools[func.__name__] = func
                return func

            return decorator

        mock_mcp.tool = capture_tool
        register_vision_tools(mock_mcp)

        # Valid 1x1 PNG
        data_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

        result = await tools["prepare_figure_search"](source=InlineImageSource(kind="base64", data=data_uri))

        # Should return ImageContent + TextContent
        assert len(result) == 2
        assert result[0].type == "image"
        assert result[1].type == "text"
        assert "Figure Analysis" in result[1].text
