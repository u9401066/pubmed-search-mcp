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

import logging
import math
import urllib.parse
from typing import Any

from pubmed_search.domain.entities.image import ImageResult, ImageSource
from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

logger = logging.getLogger(__name__)

# API endpoints
OPENI_BASE_URL = "https://openi.nlm.nih.gov"
OPENI_API_URL = f"{OPENI_BASE_URL}/api/search"


class OpenIClient(BaseAPIClient):
    """
    Open-i (NLM) biomedical image search client.

    Supports ALL 13 API parameters from Swagger spec.

    Usage:
        client = OpenIClient()
        images, total = client.search("chest pneumonia", image_type="xg")
        images, total = client.search("surgery", sort_by="d", video_only=True)
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
    ) -> tuple[list[ImageResult], int]:
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
            logger.warning(f"Invalid image_type '{image_type}', valid: {self.VALID_IMAGE_TYPES}. Ignoring filter.")
            image_type = None

        # Validate collection
        if collection and collection not in self.VALID_COLLECTIONS:
            logger.warning(f"Invalid collection '{collection}', valid: {self.VALID_COLLECTIONS}. Ignoring filter.")
            collection = None

        # Validate sort_by
        if sort_by and sort_by not in self.VALID_SORT_BY:
            logger.warning(f"Invalid sort_by '{sort_by}', valid: {self.VALID_SORT_BY}. Ignoring.")
            sort_by = None

        # Validate article_type
        if article_type and article_type not in self.VALID_ARTICLE_TYPES:
            logger.warning(f"Invalid article_type '{article_type}', valid: {self.VALID_ARTICLE_TYPES}. Ignoring.")
            article_type = None

        # Validate specialty
        if specialty and specialty not in self.VALID_SPECIALTIES:
            logger.warning(f"Invalid specialty '{specialty}', valid: {self.VALID_SPECIALTIES}. Ignoring.")
            specialty = None

        # Validate license_type
        if license_type and license_type not in self.VALID_LICENSES:
            logger.warning(f"Invalid license_type '{license_type}', valid: {self.VALID_LICENSES}. Ignoring.")
            license_type = None

        # Validate subset
        if subset and subset not in self.VALID_SUBSETS:
            logger.warning(f"Invalid subset '{subset}', valid: {self.VALID_SUBSETS}. Ignoring.")
            subset = None

        # Validate search_fields
        if search_fields and search_fields not in self.VALID_SEARCH_FIELDS:
            logger.warning(f"Invalid search_fields '{search_fields}', valid: {self.VALID_SEARCH_FIELDS}. Ignoring.")
            search_fields = None

        # Validate hmp_type
        if hmp_type and hmp_type not in self.VALID_HMP_TYPES:
            logger.warning(f"Invalid hmp_type '{hmp_type}', valid: {self.VALID_HMP_TYPES}. Ignoring.")
            hmp_type = None

        # Calculate pages needed
        pages_needed = math.ceil(max_results / self.PAGE_SIZE)
        all_images: list[ImageResult] = []
        total_count = 0

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
            logger.debug(f"Open-i search: {url}")

            data = await self._make_request(url)
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
            if end_index >= total_count:
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
            image_url=(f"{OPENI_BASE_URL}{img_large}" if img_large else ""),
            thumbnail_url=(f"{OPENI_BASE_URL}{img_thumb}" if img_thumb else None),
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
