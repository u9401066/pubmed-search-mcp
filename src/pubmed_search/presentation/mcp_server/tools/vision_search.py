"""
Vision-based Literature Search Tools.

Experimental feature: Use images to search for related scientific literature.

Tool:
- prepare_figure_search: Analyze figure and extract search terms (5 search types)

Removed in v0.3.1:
- reverse_image_search_pubmed → Merged into prepare_figure_search (use search_type)

Workflow:
1. User provides image (URL or base64)
2. MCP returns image to Agent using ImageContent protocol
3. Agent uses vision capabilities to analyze the image
4. Agent extracts search terms and calls search tools
5. Returns literature related to the image content

Use cases:
- Scientific figure → Find papers with similar figures
- Medical image → Find related case reports or research
- Chart/graph → Find papers discussing similar data
- Chemical structure → Find papers about the compound
- Equipment photo → Find papers using similar methodology
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import logging
import re
from typing import Annotated, Literal

import httpx
from mcp.types import ImageContent, TextContent
from pydantic import BaseModel, ConfigDict, Field

from pubmed_search.infrastructure.http.safe_outbound import (
    SafeFetchPolicy,
    SafeOutboundError,
    fetch_public_url,
)

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 10 * 1024 * 1024
_MAX_BASE64_CHARS = ((_MAX_IMAGE_BYTES + 2) // 3) * 4
_IMAGE_MIME_ALIASES = {"image/jpg": "image/jpeg"}
_SUPPORTED_IMAGE_MIMES = frozenset({"image/gif", "image/jpeg", "image/png", "image/webp"})


class InlineImageSource(BaseModel):
    """A bounded inline image payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["base64"]
    data: Annotated[str, Field(strict=True, min_length=1, max_length=_MAX_BASE64_CHARS + 64)]


class URLImageSource(BaseModel):
    """A bounded public image URL."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["url"]
    url: Annotated[str, Field(strict=True, min_length=1, max_length=8192)]


FigureSource = Annotated[InlineImageSource | URLImageSource, Field(discriminator="kind")]
FigureContext = Annotated[str, Field(strict=True, max_length=4000)]
FigureSearchType = Literal["comprehensive", "methodology", "results", "structure", "medical"]


# ============================================================================
# Image Utilities
# ============================================================================


def is_valid_url(url: str) -> bool:
    """Check basic URL syntax; network-address safety is checked asynchronously."""
    try:
        result = httpx.URL(url)
        if result.scheme not in ("http", "https") or not result.host:
            return False
        if result.username or result.password or result.fragment:
            return False
        expected_port = 443 if result.scheme == "https" else 80
        if result.port is not None and result.port != expected_port:
            return False
        try:
            literal = ipaddress.ip_address(result.host)
        except ValueError:
            return True
        return literal.is_global
    except (TypeError, ValueError, httpx.InvalidURL):
        return False


def _detect_image_mime(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _validate_image_bytes(data: bytes, declared_mime: str | None = None) -> str:
    if not data:
        raise ValueError("Image data is empty")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError(f"Image exceeds the {_MAX_IMAGE_BYTES}-byte limit")
    detected = _detect_image_mime(data)
    if detected is None:
        raise ValueError("Image signature is not a supported PNG, JPEG, GIF, or WebP format")
    if declared_mime:
        normalized = _IMAGE_MIME_ALIASES.get(declared_mime.lower(), declared_mime.lower())
        if normalized not in _SUPPORTED_IMAGE_MIMES:
            raise ValueError("Image MIME type is not supported")
        if normalized != detected:
            raise ValueError("Image MIME type does not match its file signature")
    return detected


def _decode_base64_image(encoded: str, declared_mime: str | None = None) -> tuple[str, str]:
    if len(encoded) > _MAX_BASE64_CHARS:
        raise ValueError(f"Image exceeds the {_MAX_IMAGE_BYTES}-byte limit")
    try:
        decoded = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Image contains invalid base64 data") from exc
    detected = _validate_image_bytes(decoded, declared_mime)
    return detected, base64.b64encode(decoded).decode("ascii")


def is_base64_image(data: str) -> bool:
    """Return whether input is a bounded image with a supported file signature."""
    try:
        if data.startswith("data:image/"):
            parse_data_uri(data)
        else:
            _decode_base64_image(data)
    except (TypeError, ValueError):
        return False
    return True


def parse_data_uri(data_uri: str) -> tuple[str, str]:
    """
    Parse a data URI into mime type and base64 data.

    Format: data:image/png;base64,iVBORw0KGgo...

    Returns:
        Tuple of (mime_type, base64_data)
    """
    if len(data_uri) > _MAX_BASE64_CHARS + 64:
        raise ValueError(f"Image exceeds the {_MAX_IMAGE_BYTES}-byte limit")
    match = re.fullmatch(r"data:(image/[A-Za-z0-9.+-]+);base64,([A-Za-z0-9+/]*={0,2})", data_uri)
    if match is None:
        raise ValueError("Invalid data URI format")
    return _decode_base64_image(match.group(2), match.group(1))


async def fetch_image_as_base64(url: str, timeout: float = 30.0) -> tuple[str, str]:
    """
    Fetch an image from URL and return as base64.

    Args:
        url: Image URL
        timeout: Request timeout in seconds

    Returns:
        Tuple of (mime_type, base64_data)

    Raises:
        ValueError: If URL is invalid or image cannot be fetched
    """
    if not is_valid_url(url):
        raise ValueError("Invalid URL for image")

    fetched = await fetch_public_url(
        url,
        policy=SafeFetchPolicy(
            max_bytes=_MAX_IMAGE_BYTES,
            total_timeout=timeout,
            max_redirects=5,
        ),
        headers={"Accept": "image/png,image/jpeg,image/gif,image/webp"},
    )
    response = fetched.response
    response.raise_for_status()

    content_type = response.headers.get("content-type", "")
    if ";" in content_type:
        content_type = content_type.split(";")[0].strip()
    if not content_type:
        raise ValueError("Image response is missing its MIME type")
    detected_mime = _validate_image_bytes(response.content, content_type)
    image_data = base64.b64encode(response.content).decode("ascii")
    return detected_mime, image_data


# ============================================================================
# MCP Tools for Vision Search
# ============================================================================


def register_vision_tools(mcp):
    """Register vision-based search tools with the MCP server."""

    @mcp.tool()  # type: ignore[misc, untyped-decorator]
    async def prepare_figure_search(
        source: FigureSource,
        context: FigureContext | None = None,
        search_type: FigureSearchType = "comprehensive",
    ) -> list[TextContent | ImageContent]:
        """
        Analyze a scientific figure or image for literature search.

        ═══════════════════════════════════════════════════════════════════════
        🔬 VISION-TO-LITERATURE SEARCH (Experimental)
        ═══════════════════════════════════════════════════════════════════════

        This tool enables searching for scientific literature based on images.

        WORKFLOW (the host agent performs the analysis and search):
        ─────────────────────────────────────────────────────────
        1. Provide an image (URL or base64-encoded)
        2. This tool returns the image using MCP ImageContent protocol
        3. YOU (the Agent) analyze the image using your vision capabilities
        4. Extract relevant ENGLISH search terms from the image
        5. Call `search_biomedical_images()` or `unified_search()` with extracted
           terms when literature retrieval is within the user-requested scope
        6. Return both the analysis and search results to the user

        ⚠️ IMPORTANT RULES:
        ────────────────
        - ALL search queries must be in ENGLISH (Open-i requirement)
        - This tool returns an image and guidance; it does not invoke a vision model
        - The host agent controls any subsequent search within its permissions
        - If the image shows a medical condition, extract the medical term in English

        SEARCH TYPES:
        ─────────────
        - "comprehensive": General analysis, extract all relevant terms (default)
        - "methodology": Focus on methods, equipment, techniques shown
        - "results": Focus on data, graphs, statistical findings
        - "structure": Focus on molecular/chemical structures
        - "medical": Focus on clinical/medical imaging findings

        USE CASES:
        ──────────
        - 📊 Scientific figures → Find papers with similar data/charts
        - 🔬 Microscopy images → Find related research
        - 🧬 Molecular structures → Find papers about the compound
        - 📈 Graphs/plots → Find papers with similar analyses
        - 🏥 Medical images → Find case reports or clinical studies
        - ⚗️ Lab equipment → Find methodology papers

        IMPORTANT:
        ──────────
        Image observations are search hypotheses that require source verification.
        Follow the user-requested scope and the host agent's execution rules.
        Use English medical terminology in all search queries.

        Args:
            source: Exactly one typed image source:
                    {"kind": "base64", "data": "data:image/png;base64,..."}
                    or {"kind": "url", "url": "https://example.org/figure.png"}.
            context: Optional context about what to look for in the image
            search_type: Type of analysis focus (comprehensive/methodology/results/structure/medical)

        Returns:
            List containing:
            - ImageContent: The image for you to analyze
            - TextContent: Instructions for next steps

        Example:
            prepare_figure_search(source={"kind": "url", "url": "https://example.com/figure1.png"})
            prepare_figure_search(
                source={"kind": "base64", "data": "data:image/png;base64,iVBORw0..."}
            )
        """
        results: list[TextContent | ImageContent] = []

        try:
            # Get image data
            if isinstance(source, URLImageSource):
                logger.info("Fetching image from a validated remote URL")
                mime_type, image_data = await fetch_image_as_base64(source.url)
            else:
                image = source.data
                if image.startswith("data:image/"):
                    # Parse data URI
                    mime_type, image_data = parse_data_uri(image)
                else:
                    mime_type, image_data = _decode_base64_image(image)

            # Add the image content for Agent to analyze
            results.append(
                ImageContent(
                    type="image",
                    data=image_data,
                    mime_type=mime_type,
                )
            )

            # Type-specific analysis prompts
            prompts = {
                "comprehensive": """
🔬 **Comprehensive Figure Analysis**

Analyze this scientific figure and extract:
1. **Main subject/topic** (e.g., cell biology, pharmacology, neuroscience)
2. **Key concepts** shown (e.g., signaling pathways, drug effects)
3. **Methods visible** (e.g., Western blot, microscopy, flow cytometry)
4. **Organisms/samples** (e.g., human cells, mouse model, in vitro)

Suggest 3-5 search queries ranked by specificity.
""",
                "methodology": """
⚗️ **Methodology Focus Analysis**

Focus on the experimental methods shown:
1. **Technique used** (e.g., PCR, ELISA, chromatography)
2. **Equipment visible** (e.g., microscope type, analyzer model)
3. **Sample preparation** visible
4. **Experimental design** implications

Suggest MeSH terms for methods and techniques.
""",
                "results": """
📊 **Results/Data Analysis**

Focus on the data presentation:
1. **Type of data** (e.g., expression levels, survival curves, dose-response)
2. **Statistical patterns** (e.g., significant differences, correlations)
3. **Measurements/units** shown
4. **Comparisons made** (e.g., treatment vs control, time points)

Suggest queries to find papers with similar findings.
""",
                "structure": """
🧬 **Molecular Structure Analysis**

Focus on chemical/molecular structures:
1. **Compound type** (e.g., small molecule, protein, nucleic acid)
2. **Functional groups** visible
3. **Known drug class** if applicable
4. **Binding sites/interactions** shown

Search for: compound name, CAS number, or structural class.
""",
                "medical": """
🏥 **Medical Image Analysis**

Focus on clinical findings:
1. **Imaging modality** (e.g., CT, MRI, X-ray, ultrasound)
2. **Anatomical region** shown
3. **Pathological findings** visible
4. **Disease indicators** if any

Suggest clinical search terms and relevant MeSH headings.
""",
            }

            # Get appropriate prompt (default to comprehensive)
            prompt = prompts[search_type]

            # Build instruction text
            instruction_text = (
                prompt
                + "\n\n_Use the extracted terms as search hypotheses. When literature retrieval is requested, continue with `search_biomedical_images()` or `unified_search()` under the host agent's permissions._"
            )

            if context:
                instruction_text += f"\n\n**User Context**: {context}"

            results.append(TextContent(type="text", text=instruction_text))

            return results

        except httpx.HTTPStatusError as e:
            return [
                TextContent(
                    type="text",
                    text=f"❌ **Error fetching image**: HTTP {e.response.status_code}\n\n💡 Check if the URL is accessible.",
                )
            ]
        except (SafeOutboundError, ValueError) as exc:
            logger.warning("Figure source validation failed (%s)", type(exc).__name__)
            return [TextContent(type="text", text="❌ **Error**: Image source is invalid or unavailable")]
        except Exception as exc:
            logger.warning("Figure analysis handoff failed (%s)", type(exc).__name__)
            return [TextContent(type="text", text="❌ **Error**: Figure analysis handoff failed")]

    # reverse_image_search_pubmed removed in v0.3.1 - merged into prepare_figure_search with search_type param

    logger.info("Registered 1 vision search tool: prepare_figure_search")
