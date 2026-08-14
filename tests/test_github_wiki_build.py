from __future__ import annotations

from scripts import build_github_wiki


def test_build_github_wiki_outputs_expected_pages(tmp_path) -> None:
    build_github_wiki.build_wiki(tmp_path)

    for page in (
        "Semantic-Scholar-Data-Plane.md",
        "OpenAlex-Search-And-Data-Plane.md",
        "ClinicalKey-AI-Boundary.md",
        "BioMCP-Architecture-Analysis.md",
    ):
        assert (tmp_path / page).exists()

    expected_pages = {
        "Home.md",
        "_Sidebar.md",
        "User-Guide.md",
        "User-Guide.zh-TW.md",
        "Advanced-Research-Workflows.md",
        "Advanced-Research-Workflows.zh-TW.md",
        "Developer-Guide.md",
        "Developer-Guide.zh-TW.md",
        "Tools-Usage-Guide.md",
        "Tools-Usage-Guide.zh-TW.md",
        "Research-Chronicle-Rebuild-Spec.md",
        "Pipeline-Tutorial.md",
        "Pipeline-Tutorial.zh-TW.md",
        "Architecture.md",
        "Quick-Reference.md",
        "Source-Contracts.md",
        "Semantic-Scholar-Data-Plane.md",
        "OpenAlex-Search-And-Data-Plane.md",
        "ClinicalKey-AI-Boundary.md",
        "BioMCP-Architecture-Analysis.md",
        "Troubleshooting.md",
        "Deployment.md",
    }

    assert {path.name for path in tmp_path.glob("*.md")} == expected_pages

    home = (tmp_path / "Home.md").read_text(encoding="utf-8")
    user_guide = (tmp_path / "User-Guide.md").read_text(encoding="utf-8")
    sidebar = (tmp_path / "_Sidebar.md").read_text(encoding="utf-8")

    assert "https://u9401066.github.io/pubmed-search-mcp/" in home
    assert "[Advanced Research Workflows](Advanced-Research-Workflows)" in home
    assert "[Tools Usage Guide](Tools-Usage-Guide)" in user_guide
    assert "[進階研究工作流](Advanced-Research-Workflows.zh-TW)" in sidebar
    assert "[Developer Guide](Developer-Guide)" in sidebar
    assert "[Semantic Scholar Data Plane](Semantic-Scholar-Data-Plane)" in sidebar
    assert "[BioMCP Architecture Analysis](BioMCP-Architecture-Analysis)" in home

    source_contracts = (tmp_path / "Source-Contracts.md").read_text(encoding="utf-8")
    biomcp = (tmp_path / "BioMCP-Architecture-Analysis.md").read_text(encoding="utf-8")
    assert 'options="native_semantic"' in source_contracts
    assert "本輪已落地與後續邊界" in biomcp


def test_build_github_wiki_rewrites_image_links_to_raw_assets() -> None:
    route_map = build_github_wiki._source_route_map()

    rendered = build_github_wiki._rewrite_links(
        "![Workflow](images/research-workflow.svg)",
        build_github_wiki.DOCS_ROOT / "USER_GUIDE.md",
        route_map,
    )

    assert rendered == (
        "![Workflow](https://raw.githubusercontent.com/u9401066/pubmed-search-mcp/master/"
        "docs/images/research-workflow.svg)"
    )
