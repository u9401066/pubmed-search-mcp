from __future__ import annotations

from scripts import build_github_wiki


def test_build_github_wiki_outputs_expected_pages(tmp_path) -> None:
    build_github_wiki.build_wiki(tmp_path)

    expected_pages = {
        "Home.md",
        "_Sidebar.md",
        "User-Guide.md",
        "User-Guide.zh-TW.md",
        "Developer-Guide.md",
        "Developer-Guide.zh-TW.md",
        "Tools-Usage-Guide.md",
        "Tools-Usage-Guide.zh-TW.md",
        "Pipeline-Tutorial.md",
        "Pipeline-Tutorial.zh-TW.md",
        "Architecture.md",
        "Quick-Reference.md",
        "Source-Contracts.md",
        "Troubleshooting.md",
        "Deployment.md",
    }

    assert {path.name for path in tmp_path.glob("*.md")} == expected_pages

    home = (tmp_path / "Home.md").read_text(encoding="utf-8")
    user_guide = (tmp_path / "User-Guide.md").read_text(encoding="utf-8")
    sidebar = (tmp_path / "_Sidebar.md").read_text(encoding="utf-8")

    assert "https://u9401066.github.io/pubmed-search-mcp/" in home
    assert "[Tools Usage Guide](Tools-Usage-Guide)" in user_guide
    assert "[Developer Guide](Developer-Guide)" in sidebar
