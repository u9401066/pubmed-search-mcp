# Changelog - v0.1.20 (Simplified Architecture)

## 🎯 Major Simplification

Streamlined from 34 tools to **20 core tools** for better Agent experience.

### ✅ Core Tools (Always Use These)

#### Main Entry Points (2)
- **unified_search** - 🌟 Primary search with auto-analysis, multi-source, dedup, ranking
- **parse_pico** - Advanced PICO clinical question parsing

#### Query Materials (2, Optional)
- **generate_search_queries** - Get MeSH terms and synonyms
- **analyze_search_query** - Preview strategy without executing

#### Article Exploration (5)
- **fetch_article_details** - Get article details
- **find_related_articles** - Similar articles
- **find_citing_articles** - Forward citations
- **get_article_references** - Backward citations
- **get_citation_metrics** - NIH iCite metrics

#### Fulltext (2)
- **get_fulltext** - Unified fulltext access (auto-selects best source)
- **get_text_mined_terms** - Extract gene/disease/drug annotations

#### NCBI Extended (6)
- **search_gene**, **get_gene_details**, **get_gene_literature**
- **search_compound**, **get_compound_details**
- **search_clinvar**

#### Session Management (3)
- **get_session_pmids** - Get cached PMIDs
- **list_search_history** - View search history
- **prepare_export** - Export citations (RIS/BibTeX/CSV)

### ⚠️ Deprecated Tools (Auto-integrated into unified_search)

These tools are now **backend-only** (not exposed to Agent):
- ~~search_literature~~ → Use `unified_search(mode="simple")`
- ~~expand_search_queries~~ → Auto-expands when results < 10
- ~~search_europe_pmc~~ → Auto-used by unified_search
- ~~search_core~~ → Auto-used by unified_search
- ~~search_core_fulltext~~ → Auto-used by unified_search
- ~~find_in_core~~ → Auto-used by get_fulltext
- ~~search_openalex~~ → Auto-used by unified_search
- ~~search_crossref~~ → Auto-used by unified_search
- ~~search_semantic_scholar~~ → Auto-used by unified_search
- ~~get_fulltext_xml~~ → Use `get_fulltext(format="xml")`
- ~~get_core_fulltext~~ → Merged into get_fulltext
- ~~analyze_fulltext_access~~ → Auto-executed by get_fulltext
- ~~get_europe_pmc_citations~~ → Merged into find_citing_articles
- ~~merge_search_results~~ → Auto-used by unified_search

### 📈 Benefits

1. **Simpler for Agents** - One primary entry point (`unified_search`)
2. **Fewer Decisions** - Auto-selects best strategy
3. **Same Power** - All features still available, just automated
4. **Backward Compatible** - Old tools still work (marked internal)

### 🔄 Migration Guide

**Before (complex)**:
```
1. analyze_search_query("query") # Analyze
2. generate_search_queries("term") # Get MeSH
3. search_europe_pmc("query") # Search
4. search_openalex("query") # Search
5. merge_search_results([...]) # Merge
```

**After (simple)**:
```
1. unified_search("query") # Done! All steps automated
```

**PICO workflow** (unchanged):
```
1. parse_pico("clinical question")
2. unified_search(..., mode="pico")
```

## 🛠️ Technical Changes

- Reorganized tool registration for clarity
- Backend tools still registered but marked internal-only
- No breaking changes - all existing integrations continue to work
- Updated documentation to reflect new architecture

## 📊 Version Info

- Version: 0.1.20
- Release Date: 2026-01-11
- Type: Major simplification (non-breaking)
