"""
Vision-based Literature Search Tools.

Experimental feature: Use images to search for related scientific literature.

Tool:
- analyze_figure_for_search: Analyze figure and extract search terms (5 search types)

Removed in v0.3.1:
- reverse_image_search_pubmed → Merged into analyze_figure_for_search (use search_type)

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

import base64
import logging
import re
from typing import Optional, Union
from urllib.parse import urlparse

import httpx
from mcp.types import ImageContent, TextContent

logger = logging.getLogger(__name__)


# ============================================================================
# Image Utilities
# ============================================================================


def is_valid_url(url: str) -> bool:
    """Check if string is a valid HTTP(S) URL."""
    try:
        result = urlparse(url)
        return result.scheme in ("http", "https") and bool(result.netloc)
    except Exception:
        return False


def is_base64_image(data: str) -> bool:
    """Check if string appears to be base64-encoded image data."""
    # Check for data URI format
    if data.startswith("data:image/"):
        return True
    # Check for raw base64 (must be reasonably long and valid chars)
    if len(data) > 100:
        try:
            # Try to decode first 100 chars
            base64.b64decode(data[:100], validate=True)
            return True
        except Exception:
            pass
    return False


def parse_data_uri(data_uri: str) -> tuple[str, str]:
    """
    Parse a data URI into mime type and base64 data.

    Format: data:image/png;base64,iVBORw0KGgo...

    Returns:
        Tuple of (mime_type, base64_data)
    """
    match = re.match(r"data:(image/[^;]+);base64,(.+)", data_uri)
    if match:
        return match.group(1), match.group(2)
    raise ValueError("Invalid data URI format")


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
        raise ValueError(f"Invalid URL: {url}")

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

        # Determine mime type
        content_type = response.headers.get("content-type", "image/jpeg")
        if ";" in content_type:
            content_type = content_type.split(";")[0].strip()

        # Validate it's an image
        if not content_type.startswith("image/"):
            raise ValueError(f"URL does not point to an image: {content_type}")

        # Encode to base64
        image_data = base64.b64encode(response.content).decode("utf-8")

        return content_type, image_data


# ============================================================================
# MCP Tools for Vision Search
# ============================================================================


def register_vision_tools(mcp):
    """Register vision-based search tools with the MCP server."""

    @mcp.tool()
    async def analyze_figure_for_search(
        image: Optional[str] = None,
        url: Optional[str] = None,
        context: Optional[str] = None,
        search_type: str = "comprehensive",
    ) -> list[Union[TextContent, ImageContent]]:
        """
        Analyze a scientific figure or image for literature search.

        ═══════════════════════════════════════════════════════════════════════
        🔬 VISION-TO-LITERATURE SEARCH (Experimental)
        ═══════════════════════════════════════════════════════════════════════

        This tool enables searching for scientific literature based on images.

        WORKFLOW:
        ─────────
        1. Provide an image (URL or base64-encoded)
        2. This tool returns the image using MCP ImageContent protocol
        3. YOU (the Agent) analyze the image using your vision capabilities
        4. Extract relevant search terms from the image
        5. Call `unified_search()` or `generate_search_queries()` with those terms

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
        After analyzing the image, suggest search terms and ask the user
        if they want to proceed with the literature search.

        Args:
            image: Base64-encoded image data OR data URI (data:image/png;base64,...)
            url: URL of the image to analyze
            context: Optional context about what to look for in the image
            search_type: Type of analysis focus (comprehensive/methodology/results/structure/medical)

        Returns:
            List containing:
            - ImageContent: The image for you to analyze
            - TextContent: Instructions for next steps

        Example:
            analyze_figure_for_search(url="https://example.com/figure1.png")
            analyze_figure_for_search(url="https://...", search_type="medical")
            analyze_figure_for_search(image="data:image/png;base64,iVBORw0...")
        """
        results: list[Union[TextContent, ImageContent]] = []

        # Validate input - need either image or url
        if not image and not url:
            return [
                TextContent(
                    type="text",
                    text=(
                        "❌ **Error**: Please provide either `image` (base64) or `url`\n\n"
                        "📝 **Examples**:\n"
                        '- `analyze_figure_for_search(url="https://example.com/figure.png")`\n'
                        '- `analyze_figure_for_search(url="...", search_type="medical")`\n'
                        '- `analyze_figure_for_search(image="data:image/png;base64,...")`'
                    ),
                )
            ]

        try:
            # Get image data
            if url:
                logger.info(f"Fetching image from URL: {url}")
                mime_type, image_data = await fetch_image_as_base64(url)
            elif image:
                if image.startswith("data:image/"):
                    # Parse data URI
                    mime_type, image_data = parse_data_uri(image)
                elif is_base64_image(image):
                    # Raw base64 - assume JPEG
                    mime_type = "image/jpeg"
                    image_data = image
                else:
                    return [
                        TextContent(
                            type="text",
                            text=(
                                "❌ **Error**: Invalid image format\n\n"
                                "💡 **Supported formats**:\n"
                                "- Data URI: `data:image/png;base64,iVBORw0...`\n"
                                "- Raw base64 string\n"
                                "- Image URL"
                            ),
                        )
                    ]

            # Add the image content for Agent to analyze
            results.append(
                ImageContent(
                    type="image",
                    data=image_data,
                    mimeType=mime_type,
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
            normalized_type = search_type.lower().strip()
            prompt = prompts.get(normalized_type, prompts["comprehensive"])

            # Build instruction text
            instruction_text = prompt + "\n\n_After analysis, I'll search PubMed for related literature._"

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
        except Exception as e:
            logger.exception("Error in analyze_figure_for_search")
            return [TextContent(type="text", text=f"❌ **Error**: {str(e)}")]

    # reverse_image_search_pubmed removed in v0.3.1 - merged into analyze_figure_for_search with search_type param

    logger.info("Registered 1 vision search tool: analyze_figure_for_search")
