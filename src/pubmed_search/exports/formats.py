"""
Export Formats - Convert article data to various citation formats.

Supported formats:
- RIS: EndNote, Zotero, Mendeley
- BibTeX: LaTeX
- CSV: Excel, data analysis
- MEDLINE: Original PubMed format
- JSON: Programmatic access
"""

import csv
import io
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

# For LaTeX special character handling
try:
    from pylatexenc.latexencode import unicode_to_latex
    HAS_PYLATEXENC = True
except ImportError:
    HAS_PYLATEXENC = False

logger = logging.getLogger(__name__)

SUPPORTED_FORMATS = ["ris", "bibtex", "csv", "medline", "json"]


def _convert_to_latex(text: str) -> str:
    """
    Convert Unicode special characters to LaTeX commands.
    
    Uses pylatexenc if available, otherwise falls back to basic mapping.
    """
    if not text:
        return text
    
    if HAS_PYLATEXENC:
        return unicode_to_latex(text)
    
    # Fallback: basic character mapping
    UNICODE_TO_LATEX = {
        'ø': r'{\o}', 'Ø': r'{\O}',
        'æ': r'{\ae}', 'Æ': r'{\AE}',
        'å': r'{\aa}', 'Å': r'{\AA}',
        'ö': r'\"o', 'Ö': r'\"O',
        'ü': r'\"u', 'Ü': r'\"U',
        'ä': r'\"a', 'Ä': r'\"A',
        'ß': r'{\ss}',
        'é': r"\'e", 'É': r"\'E",
        'è': r'\`e', 'È': r'\`E',
        'ê': r'\^e', 'Ê': r'\^E',
        'á': r"\'a", 'Á': r"\'A",
        'à': r'\`a', 'À': r'\`A',
        'í': r"\'i", 'Í': r"\'I",
        'ó': r"\'o", 'Ó': r"\'O",
        'ú': r"\'u", 'Ú': r"\'U",
        'ñ': r'\~n', 'Ñ': r'\~N',
        'ç': r'\c{c}', 'Ç': r'\c{C}',
        'ł': r'{\l}', 'Ł': r'{\L}',
    }
    for char, latex in UNICODE_TO_LATEX.items():
        text = text.replace(char, latex)
    return text


def _strip_html_tags(text: str) -> str:
    """Remove HTML tags from text (e.g., <sup>, <sub>, <i>, <b>)."""
    import re
    if not text:
        return text
    # Remove common HTML tags
    text = re.sub(r'<sup>(.*?)</sup>', r'^\1', text)  # superscript
    text = re.sub(r'<sub>(.*?)</sub>', r'_\1', text)  # subscript
    text = re.sub(r'</?[a-zA-Z][^>]*>', '', text)  # all other tags
    return text


def _format_author_ris(author_name: str) -> str:
    """
    Format author name for RIS format (Last, First Middle).
    
    Input formats handled:
    - "Kraemer Moritz U G" -> "Kraemer, Moritz U G"
    - "Smith John" -> "Smith, John"
    - "O'Brien Mary Jane" -> "O'Brien, Mary Jane"
    """
    if not author_name:
        return author_name
    
    # If already has comma, assume correct format
    if "," in author_name:
        return author_name
    
    parts = author_name.strip().split()
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]}, {parts[1]}"
    else:
        # First part is last name, rest are first/middle names
        return f"{parts[0]}, {' '.join(parts[1:])}"


def export_ris(articles: List[Dict[str, Any]], include_abstract: bool = True) -> str:
    """
    Export articles to RIS format.
    
    RIS is widely supported by reference managers:
    - EndNote
    - Zotero
    - Mendeley
    - Papers
    
    RIS Format Specification:
    - TY: Type of reference (JOUR = Journal Article)
    - TI/T1: Title
    - AU/A1: Authors (Last, First Middle format)
    - JO/JF: Journal name (full)
    - JA/J2: Journal abbreviation
    - PY/Y1: Publication year
    - VL: Volume
    - IS: Issue
    - SP: Start page
    - EP: End page
    - DO: DOI
    - AN: Accession number (PMID)
    - AB/N2: Abstract
    - KW: Keywords
    - UR: URL
    - SN: ISSN
    - LA: Language
    - DB: Database (PubMed)
    
    Args:
        articles: List of article dictionaries with metadata.
        include_abstract: Whether to include abstracts (AB field).
        
    Returns:
        RIS formatted string compatible with EndNote/Zotero/Mendeley.
    """
    lines = []
    
    for article in articles:
        # Type of reference (JOUR = Journal Article)
        lines.append("TY  - JOUR")
        
        # Title (T1 is more universally supported than TI)
        if article.get("title"):
            lines.append(f"T1  - {article['title']}")
            lines.append(f"TI  - {article['title']}")
        
        # Authors (one per line, Last, First format)
        authors = article.get("authors", [])
        for author in authors:
            formatted_author = _format_author_ris(author)
            lines.append(f"AU  - {formatted_author}")
            lines.append(f"A1  - {formatted_author}")
        
        # Journal (both full and abbreviated)
        if article.get("journal"):
            lines.append(f"JO  - {article['journal']}")
            lines.append(f"JF  - {article['journal']}")
            lines.append(f"T2  - {article['journal']}")
        if article.get("journal_abbrev"):
            lines.append(f"JA  - {article['journal_abbrev']}")
            lines.append(f"J2  - {article['journal_abbrev']}")
        
        # ISSN
        if article.get("issn"):
            lines.append(f"SN  - {article['issn']}")
        
        # Publication date
        if article.get("year"):
            lines.append(f"PY  - {article['year']}")
            lines.append(f"Y1  - {article['year']}")
            # Add publication date if available
            pub_date = article.get("pub_date", "")
            if pub_date:
                lines.append(f"DA  - {pub_date}")
        
        # Volume, Issue, Pages
        if article.get("volume"):
            lines.append(f"VL  - {article['volume']}")
        if article.get("issue"):
            lines.append(f"IS  - {article['issue']}")
        if article.get("pages"):
            pages = article['pages']
            lines.append(f"SP  - {pages}")
            # Split pages into start/end if possible
            if "-" in pages:
                sp, ep = pages.split("-", 1)
                lines.append(f"EP  - {ep.strip()}")
        
        # Identifiers
        if article.get("pmid"):
            lines.append(f"AN  - {article['pmid']}")
            lines.append(f"C1  - PMID: {article['pmid']}")
            lines.append(f"ID  - {article['pmid']}")
        if article.get("doi"):
            lines.append(f"DO  - {article['doi']}")
        if article.get("pmc_id"):
            lines.append(f"C2  - {article['pmc_id']}")
        
        # Language
        if article.get("language"):
            lines.append(f"LA  - {article['language']}")
        else:
            lines.append("LA  - eng")
        
        # Publication type
        if article.get("publication_types"):
            for pub_type in article.get("publication_types", []):
                lines.append(f"M3  - {pub_type}")
        
        # Abstract
        if include_abstract and article.get("abstract"):
            lines.append(f"AB  - {article['abstract']}")
            lines.append(f"N2  - {article['abstract']}")
        
        # Keywords (author keywords)
        for kw in article.get("keywords", []):
            lines.append(f"KW  - {kw}")
        
        # MeSH terms (also as keywords for compatibility)
        for mesh in article.get("mesh_terms", []):
            lines.append(f"KW  - {mesh}")
        
        # URLs
        if article.get("pmid"):
            lines.append(f"UR  - https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/")
        if article.get("doi"):
            lines.append(f"L2  - https://doi.org/{article['doi']}")
        if article.get("pmc_id"):
            lines.append(f"L1  - https://www.ncbi.nlm.nih.gov/pmc/articles/{article['pmc_id']}/pdf/")
        
        # Database
        lines.append("DB  - PubMed")
        
        # End of record
        lines.append("ER  - ")
        lines.append("")
    
    return "\n".join(lines)


def _format_author_bibtex(author_name: str) -> str:
    """
    Format author name for BibTeX format (Last, First Middle).
    
    BibTeX prefers "Last, First" format for proper sorting.
    """
    if not author_name:
        return author_name
    
    # If already has comma, assume correct format
    if "," in author_name:
        return author_name
    
    parts = author_name.strip().split()
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return f"{parts[0]}, {parts[1]}"
    else:
        # First part is last name, rest are first/middle names
        return f"{parts[0]}, {' '.join(parts[1:])}"


def export_bibtex(articles: List[Dict[str, Any]], include_abstract: bool = True) -> str:
    """
    Export articles to BibTeX format.
    
    BibTeX is used for LaTeX documents.
    Enhanced format with all fields needed for proper citation.
    Special characters (ø, ü, é, etc.) are converted to LaTeX commands.
    
    Args:
        articles: List of article dictionaries with metadata.
        include_abstract: Whether to include abstracts.
        
    Returns:
        BibTeX formatted string compatible with LaTeX/BibLaTeX.
    """
    entries = []
    
    for article in articles:
        # Generate citation key: FirstAuthorLastNameYear_PMID
        authors = article.get("authors", [])
        year = article.get("year", "")
        pmid = article.get("pmid", "unknown")
        
        if authors:
            first_author = authors[0].split()[0] if authors[0] else "Unknown"
            # Remove special characters from cite key
            first_author = ''.join(c for c in first_author if c.isalnum() or c.isascii())
            first_author = first_author.replace(' ', '')
        else:
            first_author = "Unknown"
        
        cite_key = f"{first_author}{year}_{pmid}"
        
        entry_lines = [f"@article{{{cite_key},"]
        
        # Title (preserve special characters with braces, convert Unicode to LaTeX)
        if article.get("title"):
            title = _convert_to_latex(article["title"])
            # Escape special LaTeX characters
            for char in ['&', '%', '$', '#', '_']:
                title = title.replace(char, f'\\{char}')
            entry_lines.append(f"  title = {{{title}}},")
        
        # Authors (BibTeX format: "Last, First and Last, First")
        # Convert Unicode to LaTeX for proper rendering
        if authors:
            bibtex_authors = " and ".join(_convert_to_latex(_format_author_bibtex(a)) for a in authors)
            entry_lines.append(f"  author = {{{bibtex_authors}}},")
        
        # Journal
        if article.get("journal"):
            entry_lines.append(f"  journal = {{{article['journal']}}},")
        
        # Journal abbreviation (useful for some styles)
        if article.get("journal_abbrev"):
            entry_lines.append(f"  journaltitle = {{{article['journal']}}},")
            entry_lines.append(f"  shortjournal = {{{article['journal_abbrev']}}},")
        
        # Year and month
        if year:
            entry_lines.append(f"  year = {{{year}}},")
        if article.get("month"):
            entry_lines.append(f"  month = {{{article['month']}}},")
        
        # Volume, number, pages
        if article.get("volume"):
            entry_lines.append(f"  volume = {{{article['volume']}}},")
        if article.get("issue"):
            entry_lines.append(f"  number = {{{article['issue']}}},")
        if article.get("pages"):
            # Convert "123-456" to "123--456" for LaTeX
            pages = article['pages'].replace('-', '--') if '-' in article['pages'] else article['pages']
            entry_lines.append(f"  pages = {{{pages}}},")
        
        # ISSN
        if article.get("issn"):
            entry_lines.append(f"  issn = {{{article['issn']}}},")
        
        # DOI
        if article.get("doi"):
            entry_lines.append(f"  doi = {{{article['doi']}}},")
        
        # PMID (custom field, widely recognized)
        if article.get("pmid"):
            entry_lines.append(f"  pmid = {{{article['pmid']}}},")
            entry_lines.append(f"  eprint = {{{article['pmid']}}},")
            entry_lines.append(f"  eprinttype = {{pubmed}},")
        
        # PMC
        if article.get("pmc_id"):
            entry_lines.append(f"  pmcid = {{{article['pmc_id']}}},")
        
        # Language
        if article.get("language"):
            entry_lines.append(f"  language = {{{article['language']}}},")
        
        # Abstract (strip HTML, convert Unicode to LaTeX)
        if include_abstract and article.get("abstract"):
            abstract = _strip_html_tags(article["abstract"])
            abstract = _convert_to_latex(abstract)
            for char in ['&', '%', '$', '#', '_']:
                abstract = abstract.replace(char, f'\\{char}')
            entry_lines.append(f"  abstract = {{{abstract}}},")
        
        # Keywords (combine author keywords and MeSH)
        keywords = article.get("keywords", []) + article.get("mesh_terms", [])
        if keywords:
            entry_lines.append(f"  keywords = {{{', '.join(keywords)}}},")
        
        # URL
        if article.get("doi"):
            entry_lines.append(f"  url = {{https://doi.org/{article['doi']}}},")
        elif article.get("pmid"):
            entry_lines.append(f"  url = {{https://pubmed.ncbi.nlm.nih.gov/{article['pmid']}/}},")
        
        # Remove trailing comma from last field
        if entry_lines[-1].endswith(","):
            entry_lines[-1] = entry_lines[-1][:-1]
        
        entry_lines.append("}")
        entries.append("\n".join(entry_lines))
    
    return "\n\n".join(entries)


def export_csv(
    articles: List[Dict[str, Any]], 
    include_abstract: bool = True,
    delimiter: str = ","
) -> str:
    """
    Export articles to CSV format.
    
    Enhanced CSV with all fields needed for reference management and data analysis.
    Compatible with Excel, EndNote CSV import, and data analysis tools.
    
    Args:
        articles: List of article dictionaries with metadata.
        include_abstract: Whether to include abstracts.
        delimiter: CSV delimiter (comma or tab).
        
    Returns:
        CSV formatted string with comprehensive citation data.
    """
    output = io.StringIO()
    
    # Define comprehensive columns for citation management
    columns = [
        # Core identifiers
        "PMID", "DOI", "PMC_ID",
        # Title
        "Title",
        # Authors (multiple formats for compatibility)
        "Authors",  # Semicolon-separated full names
        "First_Author",  # For sorting
        "Author_Count",
        # Journal information
        "Journal", "Journal_Abbrev", "ISSN",
        # Publication details
        "Year", "Month", "Publication_Date",
        "Volume", "Issue", "Pages",
        # Content
        "Abstract" if include_abstract else None,
        # Classification
        "Publication_Type", "Language",
        # Keywords and indexing
        "Keywords", "MeSH_Terms",
        # Links
        "PubMed_URL", "DOI_URL", "PMC_URL"
    ]
    # Remove None values
    columns = [c for c in columns if c is not None]
    
    writer = csv.DictWriter(output, fieldnames=columns, delimiter=delimiter, extrasaction='ignore')
    writer.writeheader()
    
    for article in articles:
        authors = article.get("authors", [])
        first_author = authors[0] if authors else ""
        
        row = {
            # Core identifiers
            "PMID": article.get("pmid", ""),
            "DOI": article.get("doi", ""),
            "PMC_ID": article.get("pmc_id", ""),
            # Title
            "Title": article.get("title", ""),
            # Authors
            "Authors": "; ".join(authors),
            "First_Author": first_author,
            "Author_Count": len(authors),
            # Journal
            "Journal": article.get("journal", ""),
            "Journal_Abbrev": article.get("journal_abbrev", ""),
            "ISSN": article.get("issn", ""),
            # Publication details
            "Year": article.get("year", ""),
            "Month": article.get("month", ""),
            "Publication_Date": article.get("pub_date", ""),
            "Volume": article.get("volume", ""),
            "Issue": article.get("issue", ""),
            "Pages": article.get("pages", ""),
            # Classification
            "Publication_Type": "; ".join(article.get("publication_types", [])),
            "Language": article.get("language", "eng"),
            # Keywords
            "Keywords": "; ".join(article.get("keywords", [])),
            "MeSH_Terms": "; ".join(article.get("mesh_terms", [])),
            # URLs
            "PubMed_URL": f"https://pubmed.ncbi.nlm.nih.gov/{article.get('pmid', '')}/",
            "DOI_URL": f"https://doi.org/{article['doi']}" if article.get('doi') else "",
            "PMC_URL": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{article['pmc_id']}/" if article.get('pmc_id') else ""
        }
        
        if include_abstract:
            row["Abstract"] = article.get("abstract", "")
        
        writer.writerow(row)
    
    return output.getvalue()


def export_medline(articles: List[Dict[str, Any]]) -> str:
    """
    Export articles to MEDLINE format.
    
    MEDLINE is the original PubMed format.
    
    Args:
        articles: List of article dictionaries with metadata.
        
    Returns:
        MEDLINE formatted string.
    """
    lines = []
    
    for article in articles:
        # PMID
        if article.get("pmid"):
            lines.append(f"PMID- {article['pmid']}")
        
        # Title
        if article.get("title"):
            lines.append(f"TI  - {article['title']}")
        
        # Authors
        for author in article.get("authors", []):
            lines.append(f"AU  - {author}")
        
        # Full author info if available
        for author_full in article.get("authors_full", []):
            if isinstance(author_full, dict):
                full_name = f"{author_full.get('last_name', '')} {author_full.get('first_name', '')}".strip()
                if full_name:
                    lines.append(f"FAU - {full_name}")
        
        # Journal
        if article.get("journal"):
            lines.append(f"JT  - {article['journal']}")
        if article.get("journal_abbrev"):
            lines.append(f"TA  - {article['journal_abbrev']}")
        
        # Publication date
        if article.get("year"):
            lines.append(f"DP  - {article['year']}")
        
        # Volume/Issue/Pages
        if article.get("volume"):
            lines.append(f"VI  - {article['volume']}")
        if article.get("issue"):
            lines.append(f"IP  - {article['issue']}")
        if article.get("pages"):
            lines.append(f"PG  - {article['pages']}")
        
        # Abstract
        if article.get("abstract"):
            lines.append(f"AB  - {article['abstract']}")
        
        # DOI
        if article.get("doi"):
            lines.append(f"AID - {article['doi']} [doi]")
        
        # PMC
        if article.get("pmc_id"):
            lines.append(f"PMC - {article['pmc_id']}")
        
        # MeSH terms
        for mesh in article.get("mesh_terms", []):
            lines.append(f"MH  - {mesh}")
        
        # Keywords
        for kw in article.get("keywords", []):
            lines.append(f"OT  - {kw}")
        
        # Record separator
        lines.append("")
    
    return "\n".join(lines)


def export_json(
    articles: List[Dict[str, Any]], 
    include_abstract: bool = True,
    pretty: bool = True
) -> str:
    """
    Export articles to JSON format.
    
    Good for programmatic access and data processing.
    
    Args:
        articles: List of article dictionaries with metadata.
        include_abstract: Whether to include abstracts.
        pretty: Whether to pretty-print JSON.
        
    Returns:
        JSON formatted string.
    """
    export_data = {
        "exported_at": datetime.now().isoformat(),
        "article_count": len(articles),
        "articles": []
    }
    
    for article in articles:
        export_article = {
            "pmid": article.get("pmid", ""),
            "title": article.get("title", ""),
            "authors": article.get("authors", []),
            "journal": article.get("journal", ""),
            "journal_abbrev": article.get("journal_abbrev", ""),
            "year": article.get("year", ""),
            "volume": article.get("volume", ""),
            "issue": article.get("issue", ""),
            "pages": article.get("pages", ""),
            "doi": article.get("doi", ""),
            "pmc_id": article.get("pmc_id", ""),
            "keywords": article.get("keywords", []),
            "mesh_terms": article.get("mesh_terms", []),
            "urls": {
                "pubmed": f"https://pubmed.ncbi.nlm.nih.gov/{article.get('pmid', '')}/",
                "doi": f"https://doi.org/{article['doi']}" if article.get("doi") else None,
                "pmc": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{article['pmc_id']}/" if article.get("pmc_id") else None
            }
        }
        
        if include_abstract:
            export_article["abstract"] = article.get("abstract", "")
        
        export_data["articles"].append(export_article)
    
    if pretty:
        return json.dumps(export_data, indent=2, ensure_ascii=False)
    else:
        return json.dumps(export_data, ensure_ascii=False)


def export_articles(
    articles: List[Dict[str, Any]],
    format: str = "ris",
    include_abstract: bool = True
) -> str:
    """
    Export articles to specified format.
    
    Args:
        articles: List of article dictionaries.
        format: Export format (ris, bibtex, csv, medline, json).
        include_abstract: Whether to include abstracts.
        
    Returns:
        Formatted string in requested format.
        
    Raises:
        ValueError: If format is not supported.
    """
    format = format.lower()
    
    if format not in SUPPORTED_FORMATS:
        raise ValueError(f"Unsupported format: {format}. Supported: {SUPPORTED_FORMATS}")
    
    if format == "ris":
        return export_ris(articles, include_abstract)
    elif format == "bibtex":
        return export_bibtex(articles, include_abstract)
    elif format == "csv":
        return export_csv(articles, include_abstract)
    elif format == "medline":
        return export_medline(articles)
    elif format == "json":
        return export_json(articles, include_abstract)
    
    raise ValueError(f"Unknown format: {format}")
