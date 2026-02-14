"""
ClinicalTrials.gov API Client

Provides access to ongoing and completed clinical trials for research enhancement.
This is a FREE public API with no registration required.

API Documentation: https://clinicaltrials.gov/data-api/api

Features:
- Search trials by condition/intervention
- Get trial status (recruiting, completed, etc.)
- Return structured trial information

Usage:
    >>> client = ClinicalTrialsClient()
    >>> trials = client.search("remimazolam sedation", limit=5)
    >>> for trial in trials:
    ...     print(f"{trial['nct_id']}: {trial['title']} ({trial['status']})")
"""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Base URL for ClinicalTrials.gov API v2
BASE_URL = "https://clinicaltrials.gov/api/v2"
DEFAULT_TIMEOUT = 10.0


class ClinicalTrialsClient:
    """Client for ClinicalTrials.gov public API."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT):
        """
        Initialize client.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Lazy-init HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"Accept": "application/json"},
            )
        return self._client

    async def search(
        self,
        query: str,
        limit: int = 5,
        status: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Search for clinical trials.

        Args:
            query: Search query (condition, intervention, etc.)
            limit: Maximum number of results (default 5)
            status: Filter by status (e.g., ["RECRUITING", "COMPLETED"])
                   Options: RECRUITING, NOT_YET_RECRUITING, ACTIVE_NOT_RECRUITING,
                           COMPLETED, TERMINATED, WITHDRAWN, SUSPENDED, UNKNOWN

        Returns:
            List of trial dictionaries with keys:
            - nct_id: NCT identifier
            - title: Brief title
            - status: Overall status
            - phase: Trial phase(s)
            - conditions: List of conditions
            - interventions: List of interventions
            - start_date: Study start date
            - enrollment: Expected enrollment
            - url: Link to ClinicalTrials.gov page
        """
        try:
            params: dict[str, Any] = {
                "query.term": query,
                "pageSize": min(limit, 20),  # API max is 1000, but we limit
            }

            # Add status filter if specified
            if status:
                params["filter.overallStatus"] = ",".join(status)

            response = await self.client.get(f"{BASE_URL}/studies", params=params)
            response.raise_for_status()

            data = response.json()
            studies = data.get("studies", [])

            return [self._normalize_study(s) for s in studies]

        except httpx.TimeoutException:
            logger.warning(f"ClinicalTrials.gov timeout for query: {query}")
            return []
        except httpx.HTTPStatusError as e:
            logger.warning(f"ClinicalTrials.gov HTTP error: {e}")
            return []
        except Exception as e:
            logger.warning(f"ClinicalTrials.gov error: {e}")
            return []

    def _normalize_study(self, study: dict) -> dict[str, Any]:
        """Normalize API response to simplified format."""
        protocol = study.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        arms_module = protocol.get("armsInterventionsModule", {})

        nct_id = id_module.get("nctId", "")

        # Extract interventions
        interventions = []
        for interv in arms_module.get("interventions", []):
            interventions.append(
                {
                    "type": interv.get("type", ""),
                    "name": interv.get("name", ""),
                }
            )

        # Extract phases
        phases = design_module.get("phases", [])
        phase_str = ", ".join(phases) if phases else "N/A"

        # Extract enrollment
        enrollment_info = design_module.get("enrollmentInfo", {})
        enrollment = enrollment_info.get("count")

        # Extract start date
        start_date_struct = status_module.get("startDateStruct", {})
        start_date = start_date_struct.get("date", "")

        return {
            "nct_id": nct_id,
            "title": id_module.get("briefTitle", ""),
            "official_title": id_module.get("officialTitle", ""),
            "status": status_module.get("overallStatus", "UNKNOWN"),
            "phase": phase_str,
            "conditions": conditions_module.get("conditions", []),
            "interventions": interventions,
            "start_date": start_date,
            "enrollment": enrollment,
            "url": f"https://clinicaltrials.gov/study/{nct_id}",
            "sponsor": protocol.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", ""),
        }

    async def get_study(self, nct_id: str) -> dict[str, Any] | None:
        """
        Get a specific study by NCT ID.

        Args:
            nct_id: NCT identifier (e.g., "NCT12345678")

        Returns:
            Study dictionary or None if not found
        """
        try:
            # Clean NCT ID
            nct_id = nct_id.strip().upper()
            if not nct_id.startswith("NCT"):
                nct_id = f"NCT{nct_id}"

            response = await self.client.get(f"{BASE_URL}/studies/{nct_id}")

            if response.status_code == 404:
                return None

            response.raise_for_status()
            return self._normalize_study(response.json())

        except Exception as e:
            logger.warning(f"Failed to get study {nct_id}: {e}")
            return None

    async def close(self):
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


def format_trials_section(trials: list[dict], max_display: int = 3) -> str:
    """
    Format clinical trials as markdown section.

    Args:
        trials: List of trial dictionaries
        max_display: Maximum trials to display inline

    Returns:
        Formatted markdown string
    """
    if not trials:
        return ""

    lines = ["\n---", "\n## 📋 Related Clinical Trials\n"]

    # Status emoji mapping
    status_emoji = {
        "RECRUITING": "🟢",
        "ACTIVE_NOT_RECRUITING": "🟡",
        "NOT_YET_RECRUITING": "🔵",
        "COMPLETED": "✅",
        "TERMINATED": "🔴",
        "WITHDRAWN": "⚫",
        "SUSPENDED": "🟠",
        "UNKNOWN": "⚪",
    }

    for i, trial in enumerate(trials[:max_display]):
        emoji = status_emoji.get(trial["status"], "⚪")
        phase = trial["phase"] if trial["phase"] != "N/A" else ""
        phase_str = f" ({phase})" if phase else ""

        lines.append(f"**{i + 1}. [{trial['nct_id']}]({trial['url']})**{phase_str} {emoji} {trial['status']}")
        lines.append(f"   {trial['title']}")

        if trial.get("enrollment"):
            lines.append(f"   *Target enrollment: {trial['enrollment']}*")
        lines.append("")

    if len(trials) > max_display:
        remaining = len(trials) - max_display
        lines.append(f"*...and {remaining} more trials*")

    # Add search link
    lines.append("\n[→ Search all on ClinicalTrials.gov](https://clinicaltrials.gov/)")

    return "\n".join(lines)


# Module-level singleton
_client: ClinicalTrialsClient | None = None


def get_clinical_trials_client() -> ClinicalTrialsClient:
    """Get or create singleton client."""
    global _client
    if _client is None:
        _client = ClinicalTrialsClient()
    return _client


async def search_related_trials(
    query: str,
    limit: int = 5,
    recruiting_only: bool = False,
) -> list[dict]:
    """
    Convenience function to search related trials.

    Args:
        query: Search query
        limit: Max results
        recruiting_only: Only show recruiting trials

    Returns:
        List of trial dictionaries
    """
    client = get_clinical_trials_client()
    status = ["RECRUITING", "NOT_YET_RECRUITING"] if recruiting_only else None
    return await client.search(query, limit=limit, status=status)
