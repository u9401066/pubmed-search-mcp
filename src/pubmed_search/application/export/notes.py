"""Guided literature note export for local wiki/Foam/Markdown libraries."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SUPPORTED_NOTE_FORMATS = ("wiki", "foam", "markdown", "medpaper")
WIKILINK_NOTE_FORMATS = {"wiki", "foam", "medpaper"}


def resolve_note_export_dir(
    output_dir: str | None = None,
    *,
    notes_dir: str | None = None,
    workspace_dir: str | None = None,
    data_dir: str | None = None,
) -> Path:
    """Resolve where local literature notes should be written."""
    if output_dir:
        return Path(output_dir).expanduser()
    if notes_dir:
        return Path(notes_dir).expanduser()
    if workspace_dir:
        return Path(workspace_dir).expanduser() / "references"
    if data_dir:
        return Path(data_dir).expanduser() / "references"
    return Path.home() / ".pubmed-search-mcp" / "references"


def write_literature_notes(
    articles: list[dict[str, Any]],
    output_dir: Path,
    *,
    note_format: str = "wiki",
    include_abstract: bool = True,
    overwrite: bool = False,
    create_index: bool = True,
    collection_name: str | None = None,
    search_context: dict[str, Any] | None = None,
    template_file: Path | None = None,
    include_csl_json: bool = True,
) -> dict[str, Any]:
    """Write article metadata as guided local notes and return a JSON-ready result."""
    normalized_format = str(note_format or "wiki").strip().lower()
    if normalized_format not in SUPPORTED_NOTE_FORMATS:
        supported = ", ".join(SUPPORTED_NOTE_FORMATS)
        msg = f"Unsupported note format: {note_format}. Use one of: {supported}"
        raise ValueError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(tz=timezone.utc)
    written: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    template_text = _read_template_file(template_file) if template_file else None

    note_entries = _build_note_entries(articles)
    for entry in note_entries:
        article = entry["article"]
        note_path = _note_path(output_dir, entry, normalized_format)
        note_path.parent.mkdir(parents=True, exist_ok=True)
        existed = note_path.exists()
        if existed and not overwrite:
            skipped.append(
                {
                    "pmid": article.get("pmid", ""),
                    "title": article.get("title", ""),
                    "path": str(note_path),
                    "reason": "exists",
                    "wikilink": _format_reference_link(
                        entry["stem"],
                        article,
                        normalized_format,
                        citation_key=entry["citation_key"],
                    ),
                }
            )
            continue

        content = _render_article_note(
            article,
            citation_key=entry["citation_key"],
            note_format=normalized_format,
            include_abstract=include_abstract,
            created_at=now,
            template_text=template_text,
        )
        note_path.write_text(content, encoding="utf-8")
        metadata_path = _write_metadata_sidecar(
            note_path.parent,
            article,
            citation_key=entry["citation_key"],
            overwrite=overwrite,
            enabled=normalized_format == "medpaper",
        )
        written.append(
            {
                "pmid": article.get("pmid", ""),
                "title": article.get("title", ""),
                "citation_key": entry["citation_key"],
                "path": str(note_path),
                "metadata_path": str(metadata_path) if metadata_path else None,
                "action": "updated" if existed and overwrite else "created",
                "wikilink": _format_reference_link(
                    entry["stem"],
                    article,
                    normalized_format,
                    citation_key=entry["citation_key"],
                ),
            }
        )

    collection_name_explicit = bool(collection_name and collection_name.strip())
    should_write_collection_artifacts = bool(written) or overwrite or collection_name_explicit

    csl_file: dict[str, Any] | None = None
    if include_csl_json and should_write_collection_artifacts:
        csl_path = _write_csl_json(output_dir, note_entries, overwrite=overwrite, created_at=now)
        csl_file = {"path": str(csl_path), "format": "csl-json"}

    index_file: dict[str, Any] | None = None
    if create_index and should_write_collection_artifacts:
        index_title = collection_name.strip() if collection_name and collection_name.strip() else _default_index_title(now)
        index_stem = _slugify(index_title, fallback="pubmed-literature-notes", max_length=80)
        index_path = output_dir / f"{index_stem}.md"
        if index_path.exists() and not overwrite:
            index_path = _next_available_path(output_dir / f"{index_stem}-{now.strftime('%H%M%S')}.md")

        index_content = _render_index_note(
            index_title,
            note_entries,
            note_format=normalized_format,
            created_at=now,
            search_context=search_context,
        )
        index_path.write_text(index_content, encoding="utf-8")
        index_file = {"title": index_title, "path": str(index_path), "action": "created"}

    return {
        "status": "success",
        "note_format": normalized_format,
        "output_dir": str(output_dir),
        "article_count": len(articles),
        "written_count": len(written),
        "skipped_count": len(skipped),
        "csl_file": csl_file,
        "index_file": index_file,
        "files": written,
        "skipped": skipped,
    }


def _build_note_entries(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    used_stems: set[str] = set()
    for index, article in enumerate(articles, 1):
        pmid = str(article.get("pmid") or "").strip()
        title = str(article.get("title") or "").strip()
        fallback = f"article-{index}"
        citation_key = _build_citation_key(article, fallback_id=_primary_identifier(article, fallback=fallback))
        base = "-".join(part for part in (pmid, _slugify(title, fallback=fallback, max_length=70)) if part)
        stem = _dedupe_stem(_slugify(base, fallback=fallback, max_length=96), used_stems)
        used_stems.add(stem)
        entries.append({"stem": stem, "citation_key": citation_key, "article": article})
    return entries


def _note_path(output_dir: Path, entry: dict[str, Any], note_format: str) -> Path:
    if note_format == "medpaper":
        directory_name = _reference_directory_name(entry["article"], fallback=entry["citation_key"])
        return output_dir / directory_name / f"{entry['citation_key']}.md"
    return output_dir / f"{entry['stem']}.md"


def _read_template_file(template_file: Path) -> str:
    template_path = template_file.expanduser()
    if not template_path.exists():
        msg = f"Template file not found: {template_path}"
        raise ValueError(msg)
    if not template_path.is_file():
        msg = f"Template path is not a file: {template_path}"
        raise ValueError(msg)
    return template_path.read_text(encoding="utf-8")


def _unique_reference_id(article: dict[str, Any], *, fallback: str) -> str:
    return _primary_identifier(article, fallback=fallback)


def _primary_identifier(article: dict[str, Any], *, fallback: str) -> str:
    for key in ("pmid", "doi", "pmc_id"):
        value = str(article.get(key) or "").strip()
        if value:
            return value
    return fallback


def _reference_directory_name(article: dict[str, Any], *, fallback: str) -> str:
    unique_id = _unique_reference_id(article, fallback=fallback)
    return _slugify(unique_id, fallback=fallback, max_length=96)


def _build_citation_key(article: dict[str, Any], *, fallback_id: str) -> str:
    year = str(_year_as_int(article.get("year")) or "nd")
    first_author = _first_author_family(article)
    author_slug = _slugify(first_author, fallback="unknown", max_length=40).replace("-", "")
    id_slug = _slugify(fallback_id, fallback="ref", max_length=60).replace("-", "")
    return f"{author_slug}{year}_{id_slug}"


def _first_author_family(article: dict[str, Any]) -> str:
    authors_full = article.get("authors_full") or []
    if isinstance(authors_full, list) and authors_full:
        first = authors_full[0]
        if isinstance(first, dict):
            family = first.get("lastname") or first.get("last_name") or first.get("family")
            if family:
                return str(family)

    authors = article.get("authors") or []
    if isinstance(authors, list) and authors:
        first_author = str(authors[0]).strip()
        if first_author:
            return first_author.split()[0]

    return "unknown"


def _write_metadata_sidecar(
    directory: Path,
    article: dict[str, Any],
    *,
    citation_key: str,
    overwrite: bool,
    enabled: bool,
) -> Path | None:
    if not enabled:
        return None

    path = directory / "metadata.json"
    if path.exists() and not overwrite:
        return path

    payload = _metadata_payload(article, citation_key=citation_key)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _metadata_payload(article: dict[str, Any], *, citation_key: str) -> dict[str, Any]:
    payload = dict(article)
    payload["unique_id"] = _unique_reference_id(article, fallback=citation_key)
    payload["citation_key"] = citation_key
    payload["source"] = "pubmed"
    payload["data_source"] = "pubmed-search-mcp"
    payload["csl_json"] = _to_csl_json(article, citation_key=citation_key)
    return payload


def _write_csl_json(
    output_dir: Path,
    entries: list[dict[str, Any]],
    *,
    overwrite: bool,
    created_at: datetime,
) -> Path:
    path = output_dir / "references.csl.json"
    if path.exists() and not overwrite:
        suffix = created_at.strftime("%Y%m%d-%H%M%S")
        path = _next_available_path(output_dir / f"references-{suffix}.csl.json")

    payload = [_to_csl_json(entry["article"], citation_key=entry["citation_key"]) for entry in entries]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path
    suffix = "".join(path.suffixes)
    base_name = path.name[: -len(suffix)] if suffix else path.name
    counter = 2
    while True:
        candidate = path.with_name(f"{base_name}-{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def _to_csl_json(article: dict[str, Any], *, citation_key: str) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": citation_key,
        "type": "article-journal",
    }
    for target, source in (
        ("title", "title"),
        ("container-title", "journal"),
        ("container-title-short", "journal_abbrev"),
        ("volume", "volume"),
        ("issue", "issue"),
        ("page", "pages"),
        ("abstract", "abstract"),
    ):
        value = _clean_text(article.get(source, ""))
        if value:
            item[target] = value

    authors = _csl_authors(article)
    if authors:
        item["author"] = authors

    year = _year_as_int(article.get("year"))
    if year:
        item["issued"] = {"date-parts": [[year]]}

    doi = str(article.get("doi") or "").strip()
    pmid = str(article.get("pmid") or "").strip()
    pmc_id = str(article.get("pmc_id") or "").strip()
    if doi:
        item["DOI"] = doi
    if pmid:
        item["PMID"] = pmid
        item["URL"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if pmc_id:
        item["PMCID"] = pmc_id

    keywords = _string_list(article.get("keywords"))
    if keywords:
        item["keyword"] = ", ".join(keywords)

    return item


def _csl_authors(article: dict[str, Any]) -> list[dict[str, str]]:
    authors: list[dict[str, str]] = []
    authors_full = article.get("authors_full") or []
    if isinstance(authors_full, list):
        for author in authors_full:
            if not isinstance(author, dict):
                continue
            family = str(author.get("lastname") or author.get("last_name") or author.get("family") or "").strip()
            given = str(
                author.get("fore_name")
                or author.get("forename")
                or author.get("first_name")
                or author.get("given")
                or ""
            ).strip()
            if family or given:
                csl_author: dict[str, str] = {}
                if family:
                    csl_author["family"] = family
                if given:
                    csl_author["given"] = given
                authors.append(csl_author)
    if authors:
        return authors

    for raw_author in _string_list(article.get("authors")):
        parts = raw_author.split()
        if not parts:
            continue
        family = parts[0]
        given = " ".join(parts[1:])
        csl_author = {"family": family}
        if given:
            csl_author["given"] = given
        authors.append(csl_author)
    return authors


def _year_as_int(value: Any) -> int | None:
    match = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(match.group(0)) if match else None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_clean_text(item) for item in value if _clean_text(item)]
    if isinstance(value, tuple):
        return [_clean_text(item) for item in value if _clean_text(item)]
    text = _clean_text(value)
    return [text] if text else []


def _dedupe_stem(stem: str, used_stems: set[str]) -> str:
    if stem not in used_stems:
        return stem
    suffix = 2
    while f"{stem}-{suffix}" in used_stems:
        suffix += 1
    return f"{stem}-{suffix}"


def _slugify(value: str, *, fallback: str, max_length: int) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", normalized).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return (slug[:max_length].strip("-") or fallback).lower()


def _render_article_note(
    article: dict[str, Any],
    *,
    citation_key: str,
    note_format: str,
    include_abstract: bool,
    created_at: datetime,
    template_text: str | None = None,
) -> str:
    title = _clean_text(article.get("title", "Untitled article"))
    pmid = str(article.get("pmid", "")).strip()
    doi = str(article.get("doi", "")).strip()
    pmc_id = str(article.get("pmc_id", "")).strip()
    journal = _clean_text(article.get("journal", ""))
    year = str(article.get("year", "")).strip()
    authors = _string_list(article.get("authors"))
    aliases = _build_aliases(article, authors)
    if citation_key not in aliases:
        aliases.insert(0, citation_key)

    if template_text is not None:
        return _render_custom_template(
            template_text,
            article,
            citation_key=citation_key,
            note_format=note_format,
            include_abstract=include_abstract,
            created_at=created_at,
        )

    if note_format == "medpaper":
        return _render_medpaper_note(
            article,
            citation_key=citation_key,
            include_abstract=include_abstract,
            created_at=created_at,
        )

    lines = [
        "---",
        f"title: {_yaml_string(title)}",
        f"pmid: {_yaml_string(pmid)}",
        f"doi: {_yaml_string(doi)}",
        f"pmc_id: {_yaml_string(pmc_id)}",
        f"journal: {_yaml_string(journal)}",
        f"year: {_yaml_string(year)}",
        f"citation_key: {_yaml_string(citation_key)}",
        'source: "PubMed"',
        f"note_format: {_yaml_string(note_format)}",
        f"created: {_yaml_string(created_at.isoformat())}",
        'tags: ["literature", "pubmed"]',
        f"aliases: {_yaml_list(aliases)}",
        "---",
        "",
        f"# {title}",
        "",
        "## Metadata",
        f"- PMID: {_format_pubmed_link(pmid)}" if pmid else "- PMID:",
        f"- DOI: {_format_doi_link(doi)}" if doi else "- DOI:",
        f"- PMC: {_format_pmc_link(pmc_id)}" if pmc_id else "- PMC:",
        f"- Journal: {journal}" if journal else "- Journal:",
        f"- Year: {year}" if year else "- Year:",
        f"- Authors: {'; '.join(authors)}" if authors else "- Authors:",
        "",
        "## Triage",
        "- Status:",
        "- Relevance:",
        "- Decision:",
        "",
        "## Summary",
        "-",
        "",
        "## Key Findings",
        "-",
        "",
        "## Methods And Population",
        "-",
        "",
        "## Limitations",
        "-",
        "",
        "## Follow Up Questions",
        "-",
        "",
        "## Citation",
        f"- {_format_citation(article, authors)}",
        "",
        "## Links",
    ]

    for link in _article_links(pmid, doi, pmc_id):
        lines.append(f"- {link}")

    if include_abstract and article.get("abstract"):
        lines.extend(["", "## Abstract", "", _clean_text(article.get("abstract", ""))])

    return "\n".join(lines).rstrip() + "\n"


def _render_index_note(
    title: str,
    entries: list[dict[str, Any]],
    *,
    note_format: str,
    created_at: datetime,
    search_context: dict[str, Any] | None,
) -> str:
    lines = [
        "---",
        f"title: {_yaml_string(title)}",
        'type: "pubmed-literature-index"',
        f"created: {_yaml_string(created_at.isoformat())}",
        f"note_format: {_yaml_string(note_format)}",
        'tags: ["literature", "pubmed", "index"]',
        "---",
        "",
        f"# {title}",
        "",
    ]

    if search_context:
        lines.extend(
            [
                "## Search Context",
                f"- Query: {search_context.get('query', '')}",
                f"- Timestamp: {search_context.get('timestamp', '')}",
                f"- Result count: {search_context.get('result_count', '')}",
                "",
            ]
        )

    lines.extend(["## References", ""])
    for entry in entries:
        article = entry["article"]
        metadata = ", ".join(
            part
            for part in (str(article.get("year", "")).strip(), _clean_text(article.get("journal", "")))
            if part
        )
        link = _format_reference_link(
            entry["stem"],
            article,
            note_format,
            citation_key=entry["citation_key"],
        )
        suffix = f" - {metadata}" if metadata else ""
        lines.append(f"- {link}{suffix}")

    lines.extend(["", "## Synthesis Notes", "-"])
    return "\n".join(lines).rstrip() + "\n"


def _format_reference_link(
    stem: str,
    article: dict[str, Any],
    note_format: str,
    *,
    citation_key: str | None = None,
) -> str:
    title = _clean_text(article.get("title", "Untitled article"))
    if note_format in WIKILINK_NOTE_FORMATS:
        target = citation_key if note_format == "medpaper" and citation_key else stem
        return f"[[{target}|{title}]]"
    return f"[{title}]({stem}.md)"


class _SafeTemplateContext(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def _render_custom_template(
    template_text: str,
    article: dict[str, Any],
    *,
    citation_key: str,
    note_format: str,
    include_abstract: bool,
    created_at: datetime,
) -> str:
    title = _clean_text(article.get("title", "Untitled article"))
    pmid = str(article.get("pmid", "")).strip()
    doi = str(article.get("doi", "")).strip()
    pmc_id = str(article.get("pmc_id", "")).strip()
    authors = _string_list(article.get("authors"))
    abstract = _clean_text(article.get("abstract", "")) if include_abstract else ""
    csl_json = json.dumps(_to_csl_json(article, citation_key=citation_key), ensure_ascii=False, indent=2)
    context = _SafeTemplateContext(
        title=title,
        pmid=pmid,
        doi=doi,
        pmc_id=pmc_id,
        journal=_clean_text(article.get("journal", "")),
        journal_abbrev=_clean_text(article.get("journal_abbrev", "")),
        year=str(article.get("year", "")).strip(),
        volume=str(article.get("volume", "")).strip(),
        issue=str(article.get("issue", "")).strip(),
        pages=str(article.get("pages", "")).strip(),
        authors="; ".join(authors),
        abstract=abstract,
        citation_key=citation_key,
        reference_id=_unique_reference_id(article, fallback=citation_key),
        note_format=note_format,
        created=created_at.isoformat(),
        pubmed_url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        doi_url=f"https://doi.org/{doi}" if doi else "",
        csl_json=csl_json,
        citation=_format_citation(article, authors),
        keywords=", ".join(_string_list(article.get("keywords"))),
        mesh_terms=", ".join(_string_list(article.get("mesh_terms"))),
    )
    try:
        return template_text.format_map(context).rstrip() + "\n"
    except (KeyError, ValueError) as exc:
        msg = f"Template rendering failed: {exc}. Escape literal braces as '{{{{' and '}}}}'."
        raise ValueError(msg) from exc


def _render_medpaper_note(
    article: dict[str, Any],
    *,
    citation_key: str,
    include_abstract: bool,
    created_at: datetime,
) -> str:
    title = _clean_text(article.get("title", "Untitled article"))
    pmid = str(article.get("pmid", "")).strip()
    doi = str(article.get("doi", "")).strip()
    pmc_id = str(article.get("pmc_id", "")).strip()
    journal = _clean_text(article.get("journal", ""))
    year = str(article.get("year", "")).strip()
    authors = [_clean_text(author) for author in article.get("authors", []) if author]
    aliases = _build_aliases(article, authors)
    if citation_key not in aliases:
        aliases.insert(0, citation_key)

    lines = [
        "---",
        "# VERIFIED DATA",
        'source: "pubmed"',
        "verified: true",
        'data_source: "pubmed-search-mcp"',
        f"reference_id: {_yaml_string(_unique_reference_id(article, fallback=citation_key))}",
        'trust_level: "verified"',
        f"title: {_yaml_string(title)}",
        f"citation_key: {_yaml_string(citation_key)}",
        f"aliases: {_yaml_list(aliases)}",
        'type: "reference"',
        'tags: ["reference", "literature", "pubmed"]',
        'note_class: "reference"',
        'note_domain: "literature"',
        'source_kind: "pubmed"',
        'trust_state: "verified"',
        'analysis_state: "pending"',
        'fulltext_state: "missing"',
        f"pmid: {_yaml_string(pmid)}",
        f"year: {_yaml_string(year)}",
        f"doi: {_yaml_string(doi)}",
        f"pmc: {_yaml_string(pmc_id)}",
        f"journal: {_yaml_string(journal)}",
        f"saved_at: {_yaml_string(created_at.isoformat())}",
        "",
        "# AGENT DATA",
        'agent_notes: ""',
        'agent_summary: ""',
        "agent_relevance: null",
        "",
        "# USER DATA",
        'user_notes: ""',
        "user_tags: []",
        "user_rating: null",
        'user_read_status: "unread"',
        "---",
        "",
        f"# {title}",
        "",
        f"**Authors**: {'; '.join(authors)}",
        "",
        f"**Journal**: {_format_journal_line(article)}",
        "",
        f"**Reference ID**: {_unique_reference_id(article, fallback=citation_key)}",
        f"**PMID**: {pmid}",
    ]
    if doi:
        lines.append(f"**DOI**: [{doi}](https://doi.org/{doi})")
    if pmc_id:
        lines.append(f"**PMC**: {pmc_id}")

    if include_abstract and article.get("abstract"):
        lines.extend(["", "## Abstract", "", _clean_text(article.get("abstract", ""))])

    summary = _clean_text(article.get("abstract", ""))[:500]
    if summary:
        lines.extend(["", "## Key Findings", "", summary, "", "^key-findings"])

    lines.extend(
        [
            "",
            "## Evidence Notes",
            "",
            "### Methods",
            "",
            "^evidence-methods",
            "",
            "### Results",
            "",
            "^evidence-results",
            "",
            "### Limitations",
            "",
            "^evidence-limitations",
            "",
            "## Citation Formats",
            "",
            f"**Reference**: {_format_citation(article, authors)}",
            "",
            "**CSL JSON**:",
            "",
            "```json",
            json.dumps(_to_csl_json(article, citation_key=citation_key), ensure_ascii=False, indent=2),
            "```",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _format_journal_line(article: dict[str, Any]) -> str:
    journal = _clean_text(article.get("journal", ""))
    year = str(article.get("year", "")).strip()
    volume = str(article.get("volume", "")).strip()
    issue = str(article.get("issue", "")).strip()
    pages = str(article.get("pages", "")).strip()

    line = journal
    if year:
        line = f"{line} ({year})" if line else year
    volume_issue = f"{volume}({issue})" if volume and issue else volume or issue
    if volume_issue:
        line = f"{line}; {volume_issue}" if line else volume_issue
    if pages:
        line = f"{line}: {pages}" if line else pages
    return line


def _build_aliases(article: dict[str, Any], authors: list[str]) -> list[str]:
    aliases: list[str] = []
    pmid = str(article.get("pmid", "")).strip()
    year = str(article.get("year", "")).strip()
    if pmid:
        aliases.extend([pmid, f"PMID {pmid}"])
    if authors and year:
        aliases.append(f"{authors[0].split()[0]} {year}")
    return aliases


def _format_citation(article: dict[str, Any], authors: list[str]) -> str:
    title = _clean_text(article.get("title", ""))
    journal = _clean_text(article.get("journal", ""))
    year = str(article.get("year", "")).strip()
    doi = str(article.get("doi", "")).strip()
    author_text = "; ".join(authors[:6])
    if len(authors) > 6:
        author_text += "; et al."
    parts = [part for part in (author_text, title, journal, year) if part]
    citation = ". ".join(parts)
    if doi:
        citation = f"{citation}. doi:{doi}" if citation else f"doi:{doi}"
    return citation


def _article_links(pmid: str, doi: str, pmc_id: str) -> list[str]:
    links: list[str] = []
    if pmid:
        links.append(f"PubMed: https://pubmed.ncbi.nlm.nih.gov/{pmid}/")
    if doi:
        links.append(f"DOI: https://doi.org/{doi}")
    if pmc_id:
        links.append(f"PMC: https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/")
    return links or ["PubMed:"]


def _format_pubmed_link(pmid: str) -> str:
    return f"[{pmid}](https://pubmed.ncbi.nlm.nih.gov/{pmid}/)"


def _format_doi_link(doi: str) -> str:
    return f"[{doi}](https://doi.org/{doi})"


def _format_pmc_link(pmc_id: str) -> str:
    return f"[{pmc_id}](https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/)"


def _yaml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _yaml_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _default_index_title(created_at: datetime) -> str:
    return f"PubMed Search {created_at.strftime('%Y-%m-%d %H%M%S UTC')}"
