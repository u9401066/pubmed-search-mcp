"""
Open-i (NLM) Image Search Client

Provides biomedical image search via the Open-i API.
Open-i is the National Library of Medicine's open-access
biomedical image search engine.

API Documentation: https://openi.nlm.nih.gov/faq
Swagger Spec: https://openi.nlm.nih.gov/v2/api-docs
Image Search API Reference: docs/IMAGE_SEARCH_API.md

Limitations:
- Index frozen at ~2020 (no newer content)
- Image type filter ('it' param) optional
  Valid values: "xg","xm","x","u","ph","p","mc","m","g","c"
  Default: None (all types)
- Query param name is 'query' (NOT 'q')
- m = Start Index (1-based), n = End Index (default 10)
  e.g. m=1&n=10 → results 1-10, m=11&n=20 → results 11-20
- Collection 'coll' values: pmc, cxr, usc, hmd, mpx
- Response latency: 2-9 seconds

Full API Parameters (13 total):
- query: Search query string
- m: Start index (1-based)
- n: End index
- it: Image type filter
- coll: Collection filter
- favor: Sort/rank by (r=relevance, d=date, etc.)
- at: Article type filter (cr=case report, etc.)
- sub: Subject subset filter
- lic: License filter (by, bync, byncnd, byncsa)
- sp: Medical specialty filter
- fields: Search in specific fields
- vid: Video only (0/1)
- hmp: HMD publication type filter
"""

from __future__ import annotations

import logging
import math
import urllib.parse
from typing import Any

from pubmed_search.application.image_search.source_adapters import (
    ImageProviderIssue,
    ImageProviderResponseError,
    ImageProviderSearchResult,
)
from pubmed_search.domain.entities.image import ImageResult, ImageSource
from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

# API endpoints
OPENI_BASE_URL = "https://openi.nlm.nih.gov"
OPENI_API_URL = f"{OPENI_BASE_URL}/api/search"


class _OpenIResponseSchemaError(ValueError):
    """Internal marker for a malformed Open-i payload without retaining it."""


class OpenIClient(BaseAPIClient):
    """
    Open-i (NLM) biomedical image search client.

    Supports ALL 13 API parameters from Swagger spec.

    Usage:
        client = OpenIClient()
        outcome = client.search("chest pneumonia", image_type="xg")
        outcome = client.search("surgery", sort_by="d", video_only=True)
    """

    # ═══════════════════════════════════════════════════════════════════════════
    # API Parameter Enums (from Swagger spec https://openi.nlm.nih.gov/v2/api-docs)
    # ═══════════════════════════════════════════════════════════════════════════

    # Image Type (it) - 8 positive filters + 2 exclusion filters
    VALID_IMAGE_TYPES = {"xg", "xm", "x", "u", "ph", "p", "mc", "m", "g", "c"}
    IMAGE_TYPE_LABELS = {
        # Positive filters
        "c": "CT Scan",
        "g": "Graphics",
        "m": "MRI",
        "mc": "Microscopy",
        "p": "PET",
        "ph": "Photographs",
        "u": "Ultrasound",
        "x": "X-ray",
        # Exclusion filters
        "xg": "Exclude Graphics",
        "xm": "Exclude Multipanel",
    }
    DEFAULT_IMAGE_TYPE = None  # None = all types (API does not require 'it')

    # Collection (coll)
    VALID_COLLECTIONS = {"pmc", "cxr", "usc", "hmd", "mpx"}
    COLLECTION_LABELS = {
        "pmc": "PubMed Central",
        "cxr": "Chest X-ray Collection",
        "usc": "USC Collection",
        "hmd": "History of Medicine",
        "mpx": "MedPix Teaching Images",
    }

    # Sort/Rank By (favor)
    VALID_SORT_BY = {"r", "o", "d", "e", "g", "oc", "pr", "pg", "t"}
    SORT_BY_LABELS = {
        "r": "Relevance",
        "o": "Oldest first",
        "d": "Date (newest first)",
        "e": "Education",
        "g": "Graphics",
        "oc": "Open access citation",
        "pr": "Problem",
        "pg": "PubMed/Google",
        "t": "Title",
    }

    # Article Type (at)
    VALID_ARTICLE_TYPES = {
        "ab",
        "bk",
        "bf",
        "cr",
        "dp",
        "di",
        "ed",
        "ib",
        "in",
        "lt",
        "mr",
        "ma",
        "ne",
        "ob",
        "pr",
        "or",
        "re",
        "ra",
        "rw",
        "sr",
        "rr",
        "os",
        "hs",
        "ot",
    }
    ARTICLE_TYPE_LABELS = {
        "ab": "Abstract",
        "bk": "Book",
        "bf": "Brief communication",
        "cr": "Case Report",
        "dp": "Data paper",
        "di": "Discussion",
        "ed": "Editorial",
        "ib": "Image/Video",
        "in": "Interview",
        "lt": "Letter",
        "mr": "Meta-analysis review",
        "ma": "Meeting abstract",
        "ne": "News",
        "ob": "Obituary",
        "pr": "Protocol",
        "or": "Original research",
        "re": "Review",
        "ra": "Research article",
        "rw": "Retraction/Withdrawal",
        "sr": "Systematic review",
        "rr": "Rapid report",
        "os": "Observational study",
        "hs": "Historical study",
        "ot": "Other",
    }

    # Subject Subset (sub)
    VALID_SUBSETS = {"b", "c", "e", "s", "x"}
    SUBSET_LABELS = {
        "b": "Behavioral Sciences",
        "c": "Cancer",
        "e": "Ethics",
        "s": "Surgery",
        "x": "Toxicology",
    }

    # License (lic) - Creative Commons variants
    VALID_LICENSES = {"by", "bync", "byncnd", "byncsa"}
    LICENSE_LABELS = {
        "by": "CC-BY",
        "bync": "CC-BY-NC",
        "byncnd": "CC-BY-NC-ND",
        "byncsa": "CC-BY-NC-SA",
    }

    # Medical Specialty (sp)
    VALID_SPECIALTIES = {
        "b",
        "bc",
        "c",
        "ca",
        "cc",
        "d",
        "de",
        "dt",
        "e",
        "en",
        "f",
        "eh",
        "g",
        "ge",
        "gr",
        "gy",
        "h",
        "i",
        "id",
        "im",
        "n",
        "ne",
        "nu",
        "o",
        "or",
        "ot",
        "p",
        "py",
        "pu",
        "r",
        "s",
        "t",
        "u",
        "v",
        "vi",
    }
    SPECIALTY_LABELS = {
        "b": "Behavioral Sciences",
        "bc": "Biochemistry",
        "c": "Cardiology",
        "ca": "Cancer",
        "cc": "Critical Care",
        "d": "Dermatology",
        "de": "Dentistry",
        "dt": "Diet/Nutrition",
        "e": "Endocrinology",
        "en": "ENT (Otolaryngology)",
        "f": "Family Medicine",
        "eh": "Environmental Health",
        "g": "Gastroenterology",
        "ge": "Genetics",
        "gr": "Geriatrics",
        "gy": "Gynecology",
        "h": "Hematology",
        "i": "Immunology",
        "id": "Infectious Disease",
        "im": "Internal Medicine",
        "n": "Nephrology",
        "ne": "Neurology",
        "nu": "Nursing",
        "o": "Ophthalmology",
        "or": "Orthopedics",
        "ot": "Other",
        "p": "Pediatrics",
        "py": "Psychiatry",
        "pu": "Pulmonology",
        "r": "Radiology",
        "s": "Surgery",
        "t": "Toxicology",
        "u": "Urology",
        "v": "Vascular",
        "vi": "Virology",
    }

    # Search Fields (fields)
    VALID_SEARCH_FIELDS = {"t", "m", "ab", "msh", "c", "a"}
    SEARCH_FIELD_LABELS = {
        "t": "Title",
        "m": "MeSH terms",
        "ab": "Abstract",
        "msh": "MeSH heading",
        "c": "Caption",
        "a": "Author",
    }

    # HMD Publication Type (hmp) - for History of Medicine collection
    VALID_HMP_TYPES = {
        "ad",
        "ar",
        "at",
        "bi",
        "br",
        "cr",
        "ca",
        "ch",
        "cg",
        "cd",
        "dr",
        "ep",
        "ex",
        "hr",
        "hu",
        "lt",
        "mp",
        "nw",
        "pn",
        "ph",
        "pi",
        "po",
        "pt",
        "pc",
        "ps",
    }

    PAGE_SIZE = 10  # Default results per page (m=1, n=10)

    _service_name = "Open-i"

    def __init__(self, timeout: float = 15.0):
        """
        Initialize Open-i client.

        Args:
            timeout: Request timeout in seconds (Open-i is slow: 2-9s)
        """
        super().__init__(
            timeout=timeout,
            min_interval=1.0,
            headers={
                "User-Agent": "PubMedSearchMCP/0.3.0",
                "Accept": "application/json",
            },
        )

    async def search(
        self,
        query: str,
        image_type: str | None = None,
        collection: str | None = None,
        max_results: int = 10,
        # New parameters (v0.3.4)
        sort_by: str | None = None,
        article_type: str | None = None,
        specialty: str | None = None,
        license_type: str | None = None,
        subset: str | None = None,
        search_fields: str | None = None,
        video_only: bool = False,
        hmp_type: str | None = None,
    ) -> ImageProviderSearchResult:
        """
        Search for biomedical images with full API support.

        Args:
            query: Search query (e.g., "chest pneumonia CT")
            image_type: Image type filter per API spec:
                        Positive: "c"=CT, "g"=Graphics, "m"=MRI,
                        "mc"=Microscopy, "p"=PET, "ph"=Photographs,
                        "u"=Ultrasound, "x"=X-ray.
                        Exclusion: "xg"=Exclude Graphics, "xm"=Exclude Multipanel.
                        None = all types (default).
            collection: Collection filter ("pmc", "cxr", "usc", "hmd", "mpx", None=all)
            max_results: Maximum number of results to return.
                Internally calculates pages needed: ceil(max_results / PAGE_SIZE).
            sort_by: Sort/rank results by (favor parameter):
                     "r"=relevance, "d"=date (newest), "o"=oldest,
                     "t"=title, "e"=education, "g"=graphics.
                     None = default relevance.
            article_type: Article type filter (at parameter):
                          "cr"=case report, "or"=original research,
                          "re"=review, "sr"=systematic review, etc.
            specialty: Medical specialty filter (sp parameter):
                       "r"=radiology, "c"=cardiology, "ne"=neurology,
                       "pu"=pulmonology, "d"=dermatology, etc.
            license_type: License filter (lic parameter):
                          "by"=CC-BY, "bync"=CC-BY-NC,
                          "byncnd"=CC-BY-NC-ND, "byncsa"=CC-BY-NC-SA.
            subset: Subject subset filter (sub parameter):
                    "b"=behavioral, "c"=cancer, "e"=ethics,
                    "s"=surgery, "x"=toxicology.
            search_fields: Search in specific fields (fields parameter):
                          "t"=title, "m"=MeSH, "ab"=abstract,
                          "c"=caption, "a"=author.
            video_only: If True, only return video content (vid=1).
            hmp_type: HMD publication type filter (hmp parameter).
                      Only effective with collection="hmd".

        Returns:
            Strict provider result with typed success, empty, or partial status.

        Note:
            Pagination stops when:
            1. max_results images have been collected
            2. A page returns fewer than PAGE_SIZE results (last page)
            3. Offset exceeds total count
        """
        if not query or not query.strip():
            raise ValueError("Open-i query must not be empty")
        if len(query.strip()) > 500:
            raise ValueError("Open-i query exceeds 500 characters")
        if isinstance(max_results, bool) or not isinstance(max_results, int) or not 1 <= max_results <= 50:
            raise ValueError("Open-i max_results must be an integer from 1 to 50")

        # Validate image_type
        if image_type and image_type not in self.VALID_IMAGE_TYPES:
            raise ValueError(f"Invalid Open-i image_type: {image_type}")

        # Validate collection
        if collection and collection not in self.VALID_COLLECTIONS:
            raise ValueError(f"Invalid Open-i collection: {collection}")

        # Validate sort_by
        if sort_by and sort_by not in self.VALID_SORT_BY:
            raise ValueError(f"Invalid Open-i sort_by: {sort_by}")

        # Validate article_type
        if article_type and article_type not in self.VALID_ARTICLE_TYPES:
            raise ValueError(f"Invalid Open-i article_type: {article_type}")

        # Validate specialty
        if specialty and specialty not in self.VALID_SPECIALTIES:
            raise ValueError(f"Invalid Open-i specialty: {specialty}")

        # Validate license_type
        if license_type and license_type not in self.VALID_LICENSES:
            raise ValueError(f"Invalid Open-i license_type: {license_type}")

        # Validate subset
        if subset and subset not in self.VALID_SUBSETS:
            raise ValueError(f"Invalid Open-i subset: {subset}")

        # Validate search_fields
        if search_fields and search_fields not in self.VALID_SEARCH_FIELDS:
            raise ValueError(f"Invalid Open-i search_fields: {search_fields}")

        # Validate hmp_type
        if hmp_type and hmp_type not in self.VALID_HMP_TYPES:
            raise ValueError(f"Invalid Open-i hmp_type: {hmp_type}")

        # Calculate pages needed
        pages_needed = math.ceil(max_results / self.PAGE_SIZE)
        all_images: list[ImageResult] = []
        total_count: int | None = None
        rows_received = 0
        rejected_rows = 0
        pages_fetched = 0
        issues: list[ImageProviderIssue] = []

        for page in range(pages_needed):
            start_index = page * self.PAGE_SIZE + 1  # 1-based
            remaining = min(max_results - len(all_images), self.PAGE_SIZE)
            end_index = start_index + remaining - 1

            # Build URL — 'query' is the correct param name (NOT 'q')
            params: dict[str, str] = {
                "query": query,
                "m": str(start_index),
                "n": str(end_index),
            }

            # Add optional filters (only if set)
            if image_type:
                params["it"] = image_type
            if collection:
                params["coll"] = collection
            if sort_by:
                params["favor"] = sort_by
            if article_type:
                params["at"] = article_type
            if specialty:
                params["sp"] = specialty
            if license_type:
                params["lic"] = license_type
            if subset:
                params["sub"] = subset
            if search_fields:
                params["fields"] = search_fields
            if video_only:
                params["vid"] = "1"
            if hmp_type:
                params["hmp"] = hmp_type

            url = f"{OPENI_API_URL}?{urllib.parse.urlencode(params)}"
            logger.debug("Executing bounded Open-i search page %s", page + 1)

            data = await self._make_request(url)
            try:
                page_total, items = self._validate_search_page(data, expected_total=total_count)
            except _OpenIResponseSchemaError:
                logger.warning("Open-i returned a malformed response page")
                if all_images:
                    issues.append(ImageProviderIssue(kind="malformed_response"))
                    break
                raise ImageProviderResponseError("Open-i response validation failed") from None

            pages_fetched += 1
            if total_count is None:
                total_count = page_total
                if total_count == 0:
                    return ImageProviderSearchResult(
                        images=[],
                        total_count=0,
                        status="empty",
                        rows_received=0,
                        pages_fetched=pages_fetched,
                    )

            # Parse results
            for item in items:
                if len(all_images) >= max_results:
                    break
                rows_received += 1
                try:
                    image = self._map_to_image_result(item)
                    all_images.append(image)
                except (TypeError, ValueError) as exc:
                    rejected_rows += 1
                    logger.warning("Failed to parse Open-i result (%s)", type(exc).__name__)
                    continue

            # Stop conditions
            if len(all_images) >= max_results:
                break
            if len(items) < self.PAGE_SIZE:
                # Last page — no more results
                break
            if end_index >= page_total:
                break

        if total_count is None or not all_images:
            raise ImageProviderResponseError("Open-i response validation failed") from None
        if rejected_rows:
            issues.append(
                ImageProviderIssue(
                    kind="malformed_rows",
                    rejected_rows=rejected_rows,
                )
            )
        return ImageProviderSearchResult(
            images=all_images,
            total_count=total_count,
            status="partial" if issues else "ok",
            rows_received=rows_received,
            pages_fetched=pages_fetched,
            issues=tuple(issues),
        )

    @staticmethod
    def _validate_search_page(
        data: object,
        *,
        expected_total: int | None,
    ) -> tuple[int, list[object]]:
        """Validate one Open-i response page without preserving raw payloads."""

        if not isinstance(data, dict) or "total" not in data or "list" not in data:
            raise _OpenIResponseSchemaError

        total = data["total"]
        items = data["list"]
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise _OpenIResponseSchemaError
        if not isinstance(items, list):
            raise _OpenIResponseSchemaError
        if (total == 0 and items) or (total > 0 and not items) or len(items) > total:
            raise _OpenIResponseSchemaError
        if expected_total is not None and total != expected_total:
            raise _OpenIResponseSchemaError
        return total, items

    @staticmethod
    def _map_to_image_result(item: object) -> ImageResult:
        """
        Map Open-i API response item to Domain entity.

        This is the Infrastructure mapper — conversion logic stays
        in Infrastructure, not in Domain.

        Args:
            item: Single result from Open-i API response .list[]

        Returns:
            ImageResult domain entity
        """
        if not isinstance(item, dict):
            raise TypeError("Open-i result row must be an object")

        source_id = OpenIClient._required_text(item, "uid")
        image_url = OpenIClient._asset_url(OpenIClient._required_text(item, "imgLarge"), required=True)
        thumbnail_value = OpenIClient._optional_text(item, "imgThumb")
        thumbnail_url = OpenIClient._asset_url(thumbnail_value, required=False) if thumbnail_value else None

        # Caption from nested image object
        image_obj = item.get("image")
        if image_obj is None:
            image_obj = {}
        if not isinstance(image_obj, dict):
            raise TypeError("Open-i image metadata must be an object")
        caption = OpenIClient._optional_text(image_obj, "caption") or ""

        return ImageResult(
            image_url=image_url,
            thumbnail_url=thumbnail_url,
            caption=caption,
            label="",
            source=ImageSource.OPENI,
            source_id=source_id,
            pmid=OpenIClient._optional_text(item, "pmid"),
            pmcid=OpenIClient._optional_text(item, "pmcid"),
            doi=None,  # Open-i does not return DOI
            article_title=OpenIClient._optional_text(item, "title") or "",
            journal=OpenIClient._optional_text(item, "journal_title") or "",
            authors=OpenIClient._optional_text(item, "authors") or "",
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
        mesh = item.get("MeSH")
        if mesh is None:
            return []
        if not isinstance(mesh, dict):
            raise TypeError("Open-i MeSH metadata must be an object")
        major = mesh.get("major", [])
        minor = mesh.get("minor", [])
        if not isinstance(major, list) or not isinstance(minor, list):
            raise TypeError("Open-i MeSH terms must be lists")
        if any(not isinstance(term, str) or not term.strip() for term in [*major, *minor]):
            raise TypeError("Open-i MeSH terms must be non-empty strings")
        return list(major) + list(minor)

    @staticmethod
    def _required_text(item: dict[str, Any], key: str) -> str:
        """Read one required non-empty provider text field."""

        value = item.get(key)
        if not isinstance(value, str) or not value.strip():
            raise TypeError("Open-i result row is missing required text")
        return value

    @staticmethod
    def _optional_text(item: dict[str, Any], key: str) -> str | None:
        """Read one optional provider text field without coercion."""

        value = item.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise TypeError("Open-i result row contains invalid text")
        return value

    @staticmethod
    def _asset_url(value: str, *, required: bool) -> str:
        """Resolve an Open-i-owned image path while rejecting foreign URLs."""

        if not value:
            if required:
                raise ValueError("Open-i result row is missing its image URL")
            return ""
        if value.startswith("/"):
            return f"{OPENI_BASE_URL}{value}"
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc == "openi.nlm.nih.gov":
            return value
        raise ValueError("Open-i result row contains an invalid image URL")
