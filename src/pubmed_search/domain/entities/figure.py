"""
Article Figure Domain Entity

Represents figure metadata extracted from PMC JATS XML articles.
These are structured figures embedded in article full text, distinct from
the ImageResult entity which represents biomedical image search results.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ArticleFigure:
    """Figure metadata extracted from article JATS XML.

    Contains label, caption, and image URLs for a single figure
    in a published article.
    """

    figure_id: str
    label: str  # e.g., "Figure 1"
    caption_text: str = ""
    caption_title: str | None = None
    image_url: str | None = None
    image_url_large: str | None = None
    graphic_href: str = ""  # Raw xlink:href from JATS XML
    subfigures: list[ArticleFigure] | None = None
    mentioned_in_sections: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        result: dict = {
            "figure_id": self.figure_id,
            "label": self.label,
            "caption_title": self.caption_title,
            "caption_text": self.caption_text,
            "image_url": self.image_url,
            "image_url_large": self.image_url_large,
            "graphic_href": self.graphic_href,
        }
        if self.subfigures:
            result["subfigures"] = [sf.to_dict() for sf in self.subfigures]
        if self.mentioned_in_sections:
            result["mentioned_in_sections"] = self.mentioned_in_sections
        return result


@dataclass
class ArticleFiguresResult:
    """Result of figure extraction from an article.

    Aggregates all figures found in a single PMC article,
    along with metadata about the extraction source and PDF links.
    """

    pmid: str | None = None
    pmcid: str = ""
    article_title: str = ""
    total_figures: int = 0
    figures: list[ArticleFigure] = field(default_factory=list)
    pdf_links: list[dict[str, str]] = field(default_factory=list)
    source: str = ""  # "europepmc", "pmc_efetch", "bioc"
    is_open_access: bool = True
    error: str | None = None
    error_detail: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        result: dict = {
            "pmcid": self.pmcid,
            "total_figures": self.total_figures,
            "figures": [f.to_dict() for f in self.figures],
            "source": self.source,
            "is_open_access": self.is_open_access,
        }
        if self.pmid:
            result["pmid"] = self.pmid
        if self.article_title:
            result["article_title"] = self.article_title
        if self.pdf_links:
            result["pdf_links"] = self.pdf_links
        if self.error:
            result["error"] = self.error
            if self.error_detail:
                result["error_detail"] = self.error_detail
        return result
