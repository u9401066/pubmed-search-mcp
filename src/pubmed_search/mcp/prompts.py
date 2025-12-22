"""
MCP Prompts - Pre-defined research workflows for AI Agents

These prompts provide structured guidance for common research tasks.
Agents can call prompts/list and prompts/get to retrieve these templates.

Prompts are NOT executed - they return guidance that the Agent follows.
"""

from mcp.server.fastmcp import FastMCP


def register_prompts(mcp: FastMCP) -> None:
    """Register all research prompts with MCP server."""
    
    # =========================================================================
    # 🔍 Search Workflows
    # =========================================================================
    
    @mcp.prompt()
    def quick_search(topic: str) -> str:
        """
        Quick literature search - just find some papers on a topic.
        
        Use when: User says "find papers about...", "search for...", "any articles on..."
        """
        return f"""# Quick Search Workflow

## User's Topic: {topic}

## Steps:
1. Call `search_literature(query="{topic}", limit=10)`
2. Present results with title, authors, year, journal
3. Ask if user wants to explore any paper further

## Example Response Format:
Found X papers on "{topic}":

1. **[Title]** (Year)
   Authors | Journal
   PMID: XXXXX

[Ask: "Would you like me to find related articles, get full text, or export these?"]
"""

    @mcp.prompt()
    def systematic_search(topic: str) -> str:
        """
        Systematic/comprehensive search using MeSH and synonyms.
        
        Use when: User asks for "systematic search", "comprehensive review",
        "find all papers", or needs thorough coverage.
        """
        return f"""# Systematic Search Workflow

## User's Topic: {topic}

## Steps:

### Step 1: Generate Search Materials
```python
generate_search_queries(topic="{topic}")
```
This returns:
- `corrected_topic`: Spell-corrected query
- `mesh_terms`: MeSH standard vocabulary with synonyms
- `suggested_queries`: Pre-built query strategies

### Step 2: Execute Parallel Searches
Use the `suggested_queries` from Step 1. Execute in parallel:
```python
search_literature(query=suggested_queries[0]["query"])  # Title search
search_literature(query=suggested_queries[1]["query"])  # Title/Abstract
search_literature(query=suggested_queries[2]["query"])  # MeSH terms
# ... more strategies
```

### Step 3: Merge Results
```python
merge_search_results(results_json='[["pmid1","pmid2"],["pmid2","pmid3"],...]')
```
Returns:
- `unique_pmids`: Deduplicated list
- `high_relevance_pmids`: Found in multiple searches (most relevant!)

### Step 4: Present Results
Prioritize high_relevance_pmids - these are the most relevant papers.

## Key Insight:
MeSH expansion finds papers that use different terminology but same concepts.
Example: "heart attack" → "Myocardial Infarction"[MeSH] → finds all related papers
"""

    @mcp.prompt()
    def pico_search(clinical_question: str) -> str:
        """
        PICO-based clinical question search.
        
        Use when: User asks comparative questions like "Is A better than B?",
        "Does X reduce Y?", "In patients with Z, what is the effect of..."
        """
        return f"""# PICO Clinical Search Workflow

## User's Question: {clinical_question}

## Steps:

### Step 1: Parse PICO Structure
```python
parse_pico(description="{clinical_question}")
```
Returns:
- P (Population): Who are the patients?
- I (Intervention): What treatment/exposure?
- C (Comparison): Compared to what?
- O (Outcome): What result?
- question_type: therapy/diagnosis/prognosis/etiology

### Step 2: Generate Materials for Each PICO Element (PARALLEL!)
```python
generate_search_queries(topic="<P element>")  # Population
generate_search_queries(topic="<I element>")  # Intervention
generate_search_queries(topic="<C element>")  # Comparison (if exists)
generate_search_queries(topic="<O element>")  # Outcome
```

### Step 3: Build Boolean Query
Combine with AND logic:
```
(P_mesh OR P_synonyms) AND 
(I_mesh OR I_synonyms) AND 
(C_mesh OR C_synonyms) AND 
(O_mesh OR O_synonyms)
```

High precision: All PICO elements required
High recall: (P) AND (I OR C) AND (O)

### Step 4: Add Clinical Query Filter
Based on question_type:
- therapy → `AND therapy[filter]`
- diagnosis → `AND diagnosis[filter]`
- prognosis → `AND prognosis[filter]`

### Step 5: Search and Merge
```python
search_literature(query=<combined_query>)
merge_search_results(...)
```

## Example PICO Parsing:
Question: "Is remimazolam better than propofol for ICU sedation?"
- P: ICU patients requiring sedation
- I: remimazolam
- C: propofol
- O: sedation outcomes (efficacy, safety)
- Type: therapy
"""

    # =========================================================================
    # 📚 Deep Exploration Workflows
    # =========================================================================
    
    @mcp.prompt()
    def explore_paper(pmid: str) -> str:
        """
        Deep exploration starting from a key paper.
        
        Use when: User found an important paper and wants to explore the research landscape.
        """
        return f"""# Deep Paper Exploration Workflow

## Starting Paper: PMID {pmid}

## Available Exploration Paths:

### Path 1: Similar Topics (find_related_articles)
```python
find_related_articles(pmid="{pmid}", limit=10)
```
- Uses PubMed's similarity algorithm
- Finds papers with similar MeSH terms, keywords, citation patterns
- Best for: "Find more papers like this"

### Path 2: Follow-up Research (find_citing_articles)
```python
find_citing_articles(pmid="{pmid}", limit=20)
```
- Forward in time: Who cited this paper?
- See how the field developed after this paper
- Best for: "What research came after this?"

### Path 3: Foundation Papers (get_article_references)
```python
get_article_references(pmid="{pmid}", limit=30)
```
- Backward in time: What did this paper cite?
- Find the foundational work
- Best for: "What is this paper based on?"

### Path 4: Full Citation Network (build_citation_tree)
First evaluate:
```python
suggest_citation_tree(pmid="{pmid}")
```
If worthwhile:
```python
build_citation_tree(pmid="{pmid}", depth=2, direction="both", output_format="mermaid")
```
- Builds complete research context map
- Best for: Literature review, understanding research landscape

## Recommended Flow:
1. Start with `find_related_articles` for quick exploration
2. Use `find_citing_articles` if paper is influential
3. Use `get_article_references` if paper is recent
4. Build citation tree only for key seed papers

## Get Full Text (if needed):
```python
get_fulltext(pmcid="PMC...")  # Europe PMC - structured sections
get_core_fulltext(core_id="...")  # CORE - plain text
```
"""

    @mcp.prompt()
    def gene_drug_research(gene_or_drug: str) -> str:
        """
        Research workflow for genes or drugs/compounds.
        
        Use when: User asks about a specific gene (BRCA1, TP53) or drug (propofol, aspirin).
        """
        return f"""# Gene/Drug Research Workflow

## Target: {gene_or_drug}

## For GENES (e.g., BRCA1, TP53, EGFR):

### Step 1: Get Gene Info
```python
search_gene(query="{gene_or_drug}", organism="human", limit=5)
```
Returns: gene_id, symbol, name, chromosome, aliases, summary

### Step 2: Get Gene Details
```python
get_gene_details(gene_id="<gene_id from step 1>")
```

### Step 3: Find Gene-related Literature
```python
get_gene_literature(gene_id="<gene_id>", limit=20)
```
Returns PMID list - these are curated gene-publication links!

### Step 4: Get Article Details
```python
fetch_article_details(pmids="<pmid1>,<pmid2>,...")
```

---

## For DRUGS/COMPOUNDS (e.g., propofol, aspirin, remimazolam):

### Step 1: Get Compound Info
```python
search_compound(query="{gene_or_drug}", limit=5)
```
Returns: cid, name, molecular_formula, molecular_weight, SMILES

### Step 2: Get Compound Details
```python
get_compound_details(cid="<cid from step 1>")
```

### Step 3: Find Compound-related Literature
```python
get_compound_literature(cid="<cid>", limit=20)
```
Returns PMID list - curated compound-publication links!

### Step 4: Also Search PubMed Directly
```python
search_literature(query='"{gene_or_drug}"[Substance Name]')
```

---

## For CLINICAL VARIANTS:

### Search ClinVar
```python
search_clinvar(query="{gene_or_drug}", limit=10)
```
Returns: variant info, clinical significance, associated conditions

## Key Insight:
NCBI's curated links (gene→pubmed, compound→pubmed) are MORE PRECISE
than keyword searches. Use both for comprehensive coverage.
"""

    # =========================================================================
    # 📤 Export & Full Text Workflows
    # =========================================================================
    
    @mcp.prompt()
    def export_results() -> str:
        """
        Export search results to reference manager formats.
        
        Use when: User wants to save, export, or cite the papers found.
        """
        return """# Export Workflow

## Available Formats:
| Format | Compatible With | Use Case |
|--------|-----------------|----------|
| `ris` | EndNote, Zotero, Mendeley | Universal import |
| `bibtex` | LaTeX, Overleaf, JabRef | Academic writing |
| `csv` | Excel, Google Sheets | Data analysis |
| `medline` | PubMed native | Archiving |
| `json` | Programmatic | Custom processing |

## Export from Last Search:
```python
prepare_export(pmids="last", format="ris")
```

## Export Specific PMIDs:
```python
prepare_export(pmids="12345678,87654321,11111111", format="bibtex")
```

## Check Full Text Availability:
```python
analyze_fulltext_access(pmids="last")
```
Returns:
- open_access: PMIDs with free full text
- subscription: PMIDs requiring subscription
- abstract_only: PMIDs with only abstract

## Get Full Text Links:
```python
get_article_fulltext_links(pmid="12345678")
```
Returns: PubMed URL, PMC URL (if available), DOI link

## Download Full Text:
```python
# Europe PMC (structured XML)
get_fulltext(pmcid="PMC7096777", sections="introduction,methods,results")

# CORE (plain text)
get_core_fulltext(core_id="123456789")
```
"""

    @mcp.prompt()
    def find_open_access(topic: str) -> str:
        """
        Find open access versions of papers on a topic.
        
        Use when: User needs free full-text access to papers.
        """
        return f"""# Find Open Access Papers Workflow

## Topic: {topic}

## Strategy 1: Search Europe PMC (6.5M+ Open Access)
```python
search_europe_pmc(query="{topic}", open_access_only=True, has_fulltext=True, limit=20)
```
- Returns papers with free full text available
- Can directly retrieve content with `get_fulltext(pmcid="...")`

## Strategy 2: Search CORE (42M+ Full Text)
```python
search_core(query="{topic}", has_fulltext=True, limit=20)
```
- Aggregates from institutional repositories worldwide
- Often has preprints and accepted manuscripts

## Strategy 3: Find OA Version of Known Paper
If you have a DOI or PMID:
```python
find_in_core(identifier="10.1234/example", identifier_type="doi")
```
- Finds open access version in institutional repositories

## Strategy 4: Analyze Existing Results
```python
# After a PubMed search:
analyze_fulltext_access(pmids="last")
```
- Shows which papers have OA available

## Best Practice:
1. Start with Europe PMC for medical/biomedical papers
2. Use CORE for broader coverage (all disciplines)
3. Check analyze_fulltext_access for papers from PubMed search

## Get Full Text Content:
```python
# From Europe PMC (structured)
get_fulltext(pmcid="PMC...", sections="all")

# From CORE (plain text)
get_core_fulltext(core_id="...")
```
"""

    # =========================================================================
    # 🔬 Advanced Research Workflows
    # =========================================================================
    
    @mcp.prompt()
    def literature_review(topic: str) -> str:
        """
        Comprehensive literature review workflow.
        
        Use when: User needs a thorough literature review for a research topic.
        """
        return f"""# Literature Review Workflow

## Topic: {topic}

## Phase 1: Comprehensive Search

### 1.1 Generate Search Strategy
```python
generate_search_queries(topic="{topic}", strategy="comprehensive")
```

### 1.2 Execute Multiple Search Strategies (Parallel)
- Title search
- Title/Abstract search  
- MeSH search
- Synonym search

### 1.3 Merge and Identify Key Papers
```python
merge_search_results(results_json=...)
```
Papers in `high_relevance_pmids` are your core papers.

## Phase 2: Deep Exploration

### 2.1 For each key paper, explore:
```python
find_citing_articles(pmid="<key_paper>")  # Follow-up research
get_article_references(pmid="<key_paper>")  # Foundation papers
```

### 2.2 Build Citation Network (Optional)
```python
build_citation_tree(pmid="<most_important_paper>", depth=2, output_format="mermaid")
```

## Phase 3: Analysis

### 3.1 Get Citation Metrics
```python
get_citation_metrics(pmids="<all_key_pmids>", sort_by="rcr")
```
- RCR (Relative Citation Ratio): Impact relative to field
- Percentile: How this paper ranks

### 3.2 Filter by Quality
```python
get_citation_metrics(pmids="...", min_citations=10, min_rcr=1.0)
```
Only keep high-impact papers.

## Phase 4: Full Text Analysis

### 4.1 Get Full Texts (Europe PMC)
```python
# For papers with PMC IDs:
get_fulltext(pmcid="PMC...", sections="introduction,discussion")
```

### 4.2 Extract Key Entities
```python
get_text_mined_terms(pmid="...", semantic_type="GENE_PROTEIN")
get_text_mined_terms(pmid="...", semantic_type="DISEASE")
```

## Phase 5: Export

```python
prepare_export(pmids="<final_list>", format="ris", include_abstract=True)
```

## Output Structure:
1. Search Strategy Summary
2. Key Papers List (with metrics)
3. Research Landscape (citation network)
4. Key Findings (from full texts)
5. Exportable Bibliography
"""

    @mcp.prompt()
    def text_mining_workflow(pmid_or_pmcid: str) -> str:
        """
        Extract structured information from papers using text mining.
        
        Use when: User wants to extract genes, diseases, chemicals mentioned in papers.
        """
        return f"""# Text Mining Workflow

## Target Paper: {pmid_or_pmcid}

## Available Annotations (Europe PMC Text Mining):

### Gene/Protein Mentions
```python
get_text_mined_terms(pmid="{pmid_or_pmcid}", semantic_type="GENE_PROTEIN")
```
Returns: Gene names, positions in text, confidence scores

### Disease Mentions
```python
get_text_mined_terms(pmid="{pmid_or_pmcid}", semantic_type="DISEASE")
```
Returns: Disease names with MeSH/DOID mappings

### Chemical/Drug Mentions
```python
get_text_mined_terms(pmid="{pmid_or_pmcid}", semantic_type="CHEMICAL")
```
Returns: Chemical names with ChEBI/PubChem IDs

### Organism Mentions
```python
get_text_mined_terms(pmid="{pmid_or_pmcid}", semantic_type="ORGANISM")
```
Returns: Species names with NCBI Taxonomy IDs

### All Annotations
```python
get_text_mined_terms(pmid="{pmid_or_pmcid}")  # No filter = all types
```

## Cross-Reference Workflow:

### Found a Gene? Look it up:
```python
search_gene(query="<gene_name>", organism="human")
get_gene_literature(gene_id="<gene_id>")  # More papers about this gene
```

### Found a Chemical? Look it up:
```python
search_compound(query="<chemical_name>")
get_compound_literature(cid="<cid>")  # More papers about this compound
```

### Found a Disease? Search for more:
```python
search_literature(query='"<disease_name>"[MeSH]')
```

## Batch Analysis:
For multiple papers, combine results to find:
- Most frequently mentioned genes
- Common diseases across papers
- Shared chemical entities
"""
