"""
Open-i (NLM) Image Search Client

Provides biomedical image search via the Open-i API.
Open-i is the National Library of Medicine's open-access
biomedical image search engine.

API Documentation: https://openi.nlm.nih.gov/faq
Image Search API Reference: docs/IMAGE_SEARCH_API.md

Limitations:
- Index frozen at ~2020 (no newer content)
- Image type filter ('it' param) is REQUIRED by API (as of 2026-02)
  Valid values: "xg" (X-ray/radiology), "mc" (Microscopy), "ph" (Photo), "gl" (Graphics)
  Default: "xg" (broadest coverage)
- Fixed ~10 results per page unless 'n' param specified
- m parameter is offset, not limit
- Response latency: 2-9 seconds
"""

import json
import logging
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from pubmed_search.domain.entities.image import ImageResult, ImageSource

logger = logging.getLogger(__name__)

# API endpoints
OPENI_BASE_URL = "https://openi.nlm.nih.gov"
OPENI_API_URL = f"{OPENI_BASE_URL}/api/search"


class OpenIClient:
    """
    Open-i (NLM) biomedical image search client.

    Uses urllib.request + _make_request() pattern consistent with
    OpenAlexClient, EuropePMCClient, COREClient, etc.

    Usage:
        client = OpenIClient()
        images, total = client.search("chest pneumonia", image_type="xg")
    """

    # Valid image type filters (tested 2026-02)
    # "xg" gives broadest coverage (~1.5M results), includes all radiology images
    VALID_IMAGE_TYPES = {"xg", "mc", "ph", "gl"}
    DEFAULT_IMAGE_TYPE = "xg"  # Required by API — fallback when user doesn't specify
    VALID_COLLECTIONS = {"pmc", "mpx", "iu"}
    PAGE_SIZE = 10  # Fixed results per page

    def __init__(self, timeout: float = 15.0):
        """
        Initialize Open-i client.

        Args:
            timeout: Request timeout in seconds (Open-i is slow: 2-9s)
        """
        self._timeout = timeout
        self._last_request_time = 0.0
        self._min_interval = 1.0  # Be polite — Open-i is a free service
        self._user_agent = "PubMedSearchMCP/0.3.0"

    def _rate_limit(self) -> None:
        """Simple rate limiting between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def _make_request(self, url: str) -> dict[str, Any] | None:
        """
        Make HTTP GET request with proper headers.

        Args:
            url: Full request URL

        Returns:
            Parsed JSON response or None on error
        """
        self._rate_limit()

        request = urllib.request.Request(url)
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", self._user_agent)

        try:
            # nosec B310: URL is constructed from hardcoded OPENI_BASE_URL (https)
            with urllib.request.urlopen(
                request, timeout=self._timeout
            ) as response:  # nosec B310
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.error(f"Open-i HTTP error {e.code}: {e.reason}")
            return None
        except urllib.error.URLError as e:
            logger.error(f"Open-i URL error: {e.reason}")
            return None
        except TimeoutError:
            logger.error("Open-i request timed out")
            return None
        except Exception as e:
            logger.error(f"Open-i request failed: {e}")
            return None

    def search(
        self,
        query: str,
        image_type: str | None = None,
        collection: str | None = None,
        max_results: int = 10,
    ) -> tuple[list[ImageResult], int]:
        """
        Search for biomedical images.

        Args:
            query: Search query (e.g., "chest pneumonia CT")
            image_type: Image type filter ("xg"=X-ray, "mc"=Microscopy, "ph"=Photo, "gl"=Graphics)
                        Defaults to "xg" if not specified (required by API).
            collection: Collection filter ("pmc", "mpx"=MedPix, "iu"=Indiana, None=all)
            max_results: Maximum number of results to return.
                Internally calculates pages needed: ceil(max_results / PAGE_SIZE).

        Returns:
            Tuple of (list of ImageResult, total_count)

        Note:
            Pagination stops when:
            1. max_results images have been collected
            2. A page returns fewer than PAGE_SIZE results (last page)
            3. Offset exceeds total count
        """
        if not query or not query.strip():
            return [], 0

        # Validate image_type
        if image_type and image_type not in self.VALID_IMAGE_TYPES:
            logger.warning(
                f"Invalid image_type '{image_type}', "
                f"only {self.VALID_IMAGE_TYPES} are effective. Using default."
            )
            image_type = self.DEFAULT_IMAGE_TYPE

        # API requires 'it' parameter (as of 2026-02)
        if not image_type:
            image_type = self.DEFAULT_IMAGE_TYPE

        # Validate collection
        if collection and collection not in self.VALID_COLLECTIONS:
            logger.warning(
                f"Invalid collection '{collection}', "
                f"only {self.VALID_COLLECTIONS} are valid. Ignoring filter."
            )
            collection = None

        # Calculate pages needed
        pages_needed = math.ceil(max_results / self.PAGE_SIZE)
        all_images: list[ImageResult] = []
        total_count = 0

        for page in range(pages_needed):
            offset = page * self.PAGE_SIZE + 1  # Open-i offset is 1-based

            # Build URL
            params: dict[str, str] = {
                "q": query,
                "m": str(offset),
                "it": image_type,  # Required by API
                "n": str(min(max_results - len(all_images), self.PAGE_SIZE)),
            }
            if collection:
                params["coll"] = collection

            url = f"{OPENI_API_URL}?{urllib.parse.urlencode(params)}"
            logger.debug(f"Open-i search: {url}")

            data = self._make_request(url)
            if data is None:
                logger.warning(f"Open-i search failed at page {page + 1}")
                break

            # Extract total on first page
            if page == 0:
                total_count = data.get("total", 0)
                if total_count == 0:
                    return [], 0

            # Parse results
            items = data.get("list", [])
            for item in items:
                if len(all_images) >= max_results:
                    break
                try:
                    image = self._map_to_image_result(item)
                    all_images.append(image)
                except Exception as e:
                    logger.warning(f"Failed to parse Open-i result: {e}")
                    continue

            # Stop conditions
            if len(all_images) >= max_results:
                break
            if len(items) < self.PAGE_SIZE:
                # Last page — no more results
                break
            if offset + self.PAGE_SIZE > total_count:
                break

        return all_images, total_count

    @staticmethod
    def _map_to_image_result(item: dict[str, Any]) -> ImageResult:
        """
        Map Open-i API response item to Domain entity.

        This is the Infrastructure mapper — conversion logic stays
        in Infrastructure, not in Domain.

        Args:
            item: Single result from Open-i API response .list[]

        Returns:
            ImageResult domain entity
        """
        # Image URLs — relative paths need base URL prefix
        img_large = item.get("imgLarge", "")
        img_thumb = item.get("imgThumb", "")

        # Caption from nested image object
        image_obj = item.get("image", {})
        caption = ""
        if isinstance(image_obj, dict):
            caption = image_obj.get("caption", "")

        return ImageResult(
            image_url=(
                f"{OPENI_BASE_URL}{img_large}" if img_large else ""
            ),
            thumbnail_url=(
                f"{OPENI_BASE_URL}{img_thumb}" if img_thumb else None
            ),
            caption=caption,
            label="",
            source=ImageSource.OPENI,
            source_id=item.get("uid", ""),
            pmid=item.get("pmid") or None,
            pmcid=item.get("pmcid") or None,
            doi=None,  # Open-i does not return DOI
            article_title=item.get("title", ""),
            journal=item.get("journal_title", ""),
            authors=item.get("authors", ""),
            pub_year=None,  # Open-i does not return year directly
            image_type=None,  # API does not include type in response
            mesh_terms=OpenIClient._extract_mesh(item),
            collection=None,  # Could infer from query but not reliable
        )

    @staticmethod
    def _extract_mesh(item: dict[str, Any]) -> list[str]:
        """
        Extract MeSH terms from Open-i response.

        API returns: {"MeSH": {"major": [...], "minor": [...]}}
        Flattened into a single list.

        Args:
            item: Single result from Open-i API response

        Returns:
            Flat list of MeSH terms (major + minor)
        """
        mesh = item.get("MeSH", {})
        if not isinstance(mesh, dict):
            return []
        major = mesh.get("major", [])
        minor = mesh.get("minor", [])
        if not isinstance(major, list):
            major = []
        if not isinstance(minor, list):
            minor = []
        return list(major) + list(minor)
