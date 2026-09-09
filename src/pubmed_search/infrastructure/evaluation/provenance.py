"""Content identities for evaluation revisions independent of checkout location."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def source_fingerprint(repo_root: Path) -> str:
    """Fingerprint Python product sources; exclude the shared evaluation adapter."""
    digest = hashlib.sha256()
    paths = sorted((repo_root / "src" / "pubmed_search").rglob("*.py"))
    if not paths:
        raise ValueError(f"No PubMed Search sources found in {repo_root}")
    for path in paths:
        relative = path.relative_to(repo_root).as_posix()
        if "/infrastructure/evaluation/" not in relative:
            digest.update(relative.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()
