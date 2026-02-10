# Contributing to PubMed Search MCP

Thank you for your interest in contributing to PubMed Search MCP! This document provides guidelines and instructions for contributing.

## 📋 Table of Contents

- [Contributing to PubMed Search MCP](#contributing-to-pubmed-search-mcp)
  - [📋 Table of Contents](#-table-of-contents)
  - [Code of Conduct](#code-of-conduct)
  - [Getting Started](#getting-started)
  - [Development Setup](#development-setup)
    - [Prerequisites](#prerequisites)
    - [Installation](#installation)
    - [Environment Variables (Optional)](#environment-variables-optional)
  - [Project Architecture](#project-architecture)
    - [Key Principles](#key-principles)
  - [Making Changes](#making-changes)
    - [Branch Naming](#branch-naming)
    - [Commit Messages](#commit-messages)
  - [Code Style](#code-style)
    - [Formatting](#formatting)
    - [Type Hints](#type-hints)
    - [Docstrings](#docstrings)
  - [Testing](#testing)
    - [Running Tests](#running-tests)
    - [Writing Tests](#writing-tests)
    - [Test Coverage](#test-coverage)
  - [Pull Request Process](#pull-request-process)
    - [PR Review Checklist](#pr-review-checklist)
  - [Reporting Issues](#reporting-issues)
    - [Bug Reports](#bug-reports)
    - [Feature Requests](#feature-requests)
  - [Questions?](#questions)

## Code of Conduct

By participating in this project, you agree to maintain a respectful and inclusive environment. Please be kind to other contributors and maintain professional communication.

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/pubmed-search-mcp.git
   cd pubmed-search-mcp
   ```
3. **Add upstream** remote:
   ```bash
   git remote add upstream https://github.com/u9401066/pubmed-search-mcp.git
   ```

## Development Setup

### Prerequisites

- Python 3.12+
- Git
- (Optional) NCBI API Key for higher rate limits

### Installation

This project uses [UV](https://github.com/astral-sh/uv) for dependency management.
**All commands (including tests, lint, type check) must go through `uv run`** to ensure the correct virtual environment and dependency versions.

> 💡 **UV is extremely efficient**: Built in Rust, 10-100x faster than pip. Even `uv run pytest` confirms env consistency in milliseconds before executing — virtually zero overhead.

```bash
# Install all dependencies (including dev tools)
uv sync

# Run commands through uv (ALWAYS use uv run prefix)
uv run pytest              # Run tests
uv run ruff check .        # Lint
uv run ruff check . --fix  # Lint auto-fix
uv run ruff format .       # Format
uv run mypy src/ tests/    # Type check (including tests)
uv run pytest --cov        # Coverage
uv run pytest --timeout=60 # Tests with timeout
```

> ⚠️ **NEVER** call `pytest`, `ruff`, or `mypy` directly. Always use the `uv run` prefix.
> **Do NOT** use `pip install`. All dependencies are managed via `uv` and defined in `pyproject.toml` with `[dependency-groups]`.

### Environment Variables (Optional)

```bash
export NCBI_API_KEY="your_api_key"  # Get from: https://www.ncbi.nlm.nih.gov/account/settings/
```

## Project Architecture

This project follows **Domain-Driven Design (DDD)** with an Onion Architecture:

```
src/pubmed_search/
├── domain/                 # Core business logic
│   └── entities/           # UnifiedArticle, TimelineEvent
├── application/            # Use cases
│   ├── search/             # QueryAnalyzer, ResultAggregator
│   ├── export/             # Citation export (RIS, BibTeX...)
│   ├── session/            # SessionManager
│   └── timeline/           # TimelineBuilder, MilestoneDetector
├── infrastructure/         # External systems
│   ├── ncbi/               # Entrez, iCite, Citation Exporter
│   ├── sources/            # Europe PMC, CORE, CrossRef...
│   └── http/               # HTTP clients
├── presentation/           # User interfaces
│   ├── mcp_server/         # MCP tools, prompts, resources
│   └── api/                # REST API (Copilot Studio)
└── shared/                 # Cross-cutting concerns
    ├── exceptions.py       # Unified error handling
    └── async_utils.py      # Rate limiter, retry, circuit breaker
```

### Key Principles

1. **Dependency flows inward** - Outer layers depend on inner layers
2. **Domain models are pure** - No external dependencies in `models/`
3. **Sources are isolated** - Each external API has its own adapter
4. **Tools are thin** - MCP tools delegate to domain/application services

## Making Changes

### Branch Naming

```
feature/description-of-feature
fix/description-of-bug
docs/description-of-docs-change
refactor/description-of-refactor
```

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add citation export to BibTeX format
fix: handle rate limit errors in Europe PMC client
docs: update installation instructions
refactor: extract search logic to dedicated service
test: add unit tests for PICO parser
```

## Code Style

### Formatting

We use **ruff** for linting and formatting:

```bash
# Check for issues
uv run ruff check src/

# Auto-fix issues
uv run ruff check src/ --fix

# Format code
uv run ruff format src/
```

### Type Hints

All public functions must have type hints:

```python
def search_articles(
    query: str,
    limit: int = 10,
    *,
    include_abstract: bool = True,
) -> list[Article]:
    """Search for articles matching the query."""
    ...
```

### Docstrings

Use Google-style docstrings:

```python
def get_citation_tree(
    pmid: str,
    max_depth: int = 2,
) -> CitationTree:
    """Build a citation tree from a seed article.
    
    Args:
        pmid: The PubMed ID of the seed article.
        max_depth: Maximum depth to traverse (default: 2).
        
    Returns:
        A CitationTree containing related articles.
        
    Raises:
        ArticleNotFoundError: If the PMID doesn't exist.
    """
    ...
```

## Testing

### Running Tests

```bash
# Run all tests
uv run pytest

# Run with coverage
uv run pytest --cov=src/pubmed_search --cov-report=html

# Run specific test file
uv run pytest tests/test_client.py

# Run tests matching pattern
uv run pytest -k "test_search"
```

### Writing Tests

- Place tests in `tests/` directory
- Name test files as `test_*.py`
- Use `pytest` fixtures from `conftest.py`
- Mock external API calls to avoid network dependencies

```python
import pytest
from unittest.mock import patch

def test_search_returns_articles(mock_entrez_response):
    """Test that search returns properly formatted articles."""
    with patch("pubmed_search.entrez.search.esearch") as mock:
        mock.return_value = mock_entrez_response
        results = search_articles("cancer treatment")
        assert len(results) > 0
        assert all(hasattr(r, "pmid") for r in results)
```

### Test Coverage

We aim for **>85% code coverage**. Run coverage report:

```bash
uv run pytest --cov=src/pubmed_search --cov-report=term-missing
```

## Pull Request Process

1. **Sync with upstream**:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Create a feature branch**:
   ```bash
   git checkout -b feature/your-feature
   ```

3. **Make your changes** following the code style guidelines

4. **Run checks locally**:
   ```bash
   uv run ruff check src/
   uv run ruff format src/
   uv run pytest
   ```

5. **Push and create PR**:
   ```bash
   git push origin feature/your-feature
   ```

6. **Fill out the PR template** with:
   - Description of changes
   - Related issues (if any)
   - Testing performed
   - Screenshots (for UI changes)

### PR Review Checklist

- [ ] Code follows project architecture (DDD/Onion)
- [ ] All tests pass
- [ ] New code has test coverage
- [ ] Documentation updated (if needed)
- [ ] No breaking changes (or documented)
- [ ] Commit messages follow convention

## Reporting Issues

### Bug Reports

Include:
- Python version
- OS and version
- Steps to reproduce
- Expected vs actual behavior
- Error messages/stack traces

### Feature Requests

Include:
- Use case description
- Proposed solution
- Alternatives considered

## Questions?

- Open a [Discussion](https://github.com/u9401066/pubmed-search-mcp/discussions)
- Check existing [Issues](https://github.com/u9401066/pubmed-search-mcp/issues)

---

Thank you for contributing! 🎉
