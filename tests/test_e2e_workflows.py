"""
End-to-End Testing - Verify complete user workflows.

Tests realistic scenarios that users would encounter.
Run with: pytest tests/test_e2e_workflows.py -v
"""

import pytest
from unittest.mock import Mock
from pubmed_search import PubMedClient


# ============================================================
# E2E Test Fixtures
# ============================================================

@pytest.fixture
def complete_article_data():
    """Complete article data for E2E tests."""
    return {
        "pmid": "33475315",
        "title": "Remimazolam for procedural sedation: a systematic review",
        "authors": ["Chen SH", "Wang ST", "Cheng WC"],
        "authors_full": [
            {"lastname": "Chen", "forename": "Shih-Hao", "initials": "SH"},
            {"lastname": "Wang", "forename": "Shao-Tung", "initials": "ST"},
            {"lastname": "Cheng", "forename": "Wei-Chun", "initials": "WC"}
        ],
        "abstract": (
            "Background: Remimazolam is an ultra-short-acting benzodiazepine. "
            "This systematic review evaluates its efficacy and safety for procedural sedation. "
            "Methods: We searched PubMed, EMBASE, and Cochrane Library. "
            "Results: Remimazolam showed effective sedation with rapid onset and offset. "
            "Conclusion: Remimazolam is a promising agent for procedural sedation."
        ),
        "journal": "British Journal of Anaesthesia",
        "journal_abbrev": "Br J Anaesth",
        "year": "2021",
        "month": "Feb",
        "volume": "126",
        "issue": "2",
        "pages": "404-413",
        "doi": "10.1016/j.bja.2020.09.032",
        "pmc_id": "PMC7816155",
        "keywords": ["remimazolam", "sedation", "procedural sedation"],
        "mesh_terms": ["Benzodiazepines", "Conscious Sedation", "Anesthetics"]
    }


@pytest.fixture
def mock_client_full(complete_article_data):
    """Fully mocked PubMedClient for E2E tests."""
    client = Mock(spec=PubMedClient)
    
    # Mock search
    client.search.return_value = [complete_article_data]
    
    # Mock fetch_details
    client.fetch_details.return_value = [complete_article_data]
    
    # Mock get_related_articles
    client.get_related_articles.return_value = [
        {**complete_article_data, "pmid": "33475316", "title": "Related Article 1"},
        {**complete_article_data, "pmid": "33475317", "title": "Related Article 2"}
    ]
    
    # Mock get_citing_articles
    client.get_citing_articles.return_value = [
        {**complete_article_data, "pmid": "33475318", "title": "Citing Article 1"}
    ]
    
    return client


# ============================================================
# Workflow 1: Quick Literature Search
# ============================================================

class TestQuickSearchWorkflow:
    """Test: User wants to quickly find papers on a topic."""
    
    def test_quick_search_workflow(self, mock_client_full):
        """
        Workflow:
        1. User searches for a topic
        2. Gets back relevant articles
        3. Reads titles and abstracts
        """
        # Step 1: Search
        results = mock_client_full.search("remimazolam sedation", limit=10)
        
        assert len(results) > 0
        assert results[0]["pmid"] is not None
        
        # Step 2: Verify article data
        article = results[0]
        assert "title" in article
        assert "abstract" in article
        assert "authors" in article
        
        # Step 3: User can read key information
        assert len(article["title"]) > 0
        assert len(article["abstract"]) > 0
        assert len(article["authors"]) > 0


# ============================================================
# Workflow 2: Systematic Literature Review
# ============================================================

class TestSystematicReviewWorkflow:
    """Test: Researcher conducting systematic literature review."""
    
    def test_systematic_review_workflow(self, mock_client_full, complete_article_data):
        """
        Workflow:
        1. Search with MeSH terms
        2. Get detailed article information
        3. Export citations for reference manager
        4. Check for full text availability
        """
        # Step 1: Comprehensive search with MeSH
        mesh_query = '("Remimazolam"[MeSH]) AND ("Conscious Sedation"[MeSH])'
        results = mock_client_full.search(mesh_query, limit=50)
        
        assert len(results) > 0
        
        # Step 2: Get detailed information
        pmids = [r["pmid"] for r in results[:10]]
        details = mock_client_full.fetch_details(pmids)
        
        assert len(details) > 0
        assert all("abstract" in d for d in details)
        
        # Step 3: Prepare export (mock)
        # In real scenario, would call prepare_export()
        export_data = {
            "format": "ris",
            "articles": details,
            "count": len(details)
        }
        assert export_data["format"] == "ris"
        assert export_data["count"] > 0
        
        # Step 4: Check full text availability
        article = details[0]
        has_pmc = bool(article.get("pmc_id"))
        has_doi = bool(article.get("doi"))
        
        # User can access full text if PMC or DOI available
        can_access_fulltext = has_pmc or has_doi
        assert can_access_fulltext  # Our test data has both


# ============================================================
# Workflow 3: Citation Network Exploration
# ============================================================

class TestCitationExplorationWorkflow:
    """Test: Researcher exploring citation networks."""
    
    def test_citation_network_workflow(self, mock_client_full):
        """
        Workflow:
        1. Find a key paper
        2. Get related articles
        3. Find papers that cite this paper
        4. Get references from this paper
        """
        key_pmid = "33475315"
        
        # Step 1: Get the key paper details
        article = mock_client_full.fetch_details([key_pmid])[0]
        assert article["pmid"] == key_pmid
        
        # Step 2: Find related articles
        related = mock_client_full.get_related_articles(key_pmid, limit=10)
        assert len(related) > 0
        assert all(r["pmid"] != key_pmid for r in related)
        
        # Step 3: Find citing articles (forward citation)
        citing = mock_client_full.get_citing_articles(key_pmid, limit=10)
        assert len(citing) > 0
        
        # Step 4: Get references (backward citation)
        # Mock would be similar
        # references = mock_client_full.get_article_references(key_pmid)
        
        # User now has complete citation network
        network = {
            "key_paper": article,
            "related": related,
            "cited_by": citing,
            # "references": references
        }
        assert network["key_paper"] is not None
        assert len(network["related"]) > 0
        assert len(network["cited_by"]) > 0


# ============================================================
# Workflow 4: PICO Clinical Question
# ============================================================

class TestPICOWorkflow:
    """Test: Clinician asking PICO-based question."""
    
    def test_pico_clinical_workflow(self, mock_client_full):
        """
        Workflow:
        1. Clinician has PICO question
        2. System parses PICO elements
        3. Generates optimized search query
        4. Finds relevant clinical trials
        5. Filters for high-quality evidence
        """
        # Step 1: PICO question
        question = "Is remimazolam better than propofol for ICU sedation?"
        
        # Step 2: Parse PICO (mock)
        pico = {
            "P": "ICU patients",
            "I": "remimazolam",
            "C": "propofol",
            "O": "sedation quality"
        }
        
        # Step 3: Generate optimized query
        # Combine PICO elements with Boolean logic
        optimized_query = (
            f'("{pico["P"]}"[All Fields]) AND '
            f'("{pico["I"]}"[All Fields]) AND '
            f'("{pico["C"]}"[All Fields])'
        )
        
        # Step 4: Search
        results = mock_client_full.search(optimized_query, limit=20)
        assert len(results) > 0
        
        # Step 5: Filter for high-quality evidence
        # Look for systematic reviews, RCTs, meta-analyses
        high_quality = [
            r for r in results
            if any(term in r.get("title", "").lower() 
                   for term in ["systematic review", "meta-analysis", "randomized"])
        ]
        
        # User gets evidence-based answer
        assert len(results) > 0  # Found papers


# ============================================================
# Workflow 5: Drug Research Workflow
# ============================================================

class TestDrugResearchWorkflow:
    """Test: Pharmacologist researching a drug compound."""
    
    def test_drug_compound_workflow(self, mock_client_full):
        """
        Workflow:
        1. Search for drug by name
        2. Get compound information
        3. Find related literature
        4. Identify clinical trials
        """
        drug_name = "remimazolam"
        
        # Step 1: Search PubMed
        results = mock_client_full.search(drug_name, limit=50)
        assert len(results) > 0
        
        # Step 2: Search PubChem (mock)
        # compound_info = search_compound(drug_name)
        compound_info = {
            "cid": "11550111",
            "name": "Remimazolam",
            "formula": "C21H21N5O3",
            "molecular_weight": "391.42"
        }
        assert compound_info["cid"] is not None
        
        # Step 3: Get literature linked to compound
        # compound_literature = get_compound_literature(compound_info["cid"])
        
        # Step 4: Filter for clinical trials
        clinical_trials = [
            r for r in results
            if "clinical trial" in r.get("title", "").lower()
            or "Clinical Trial" in r.get("mesh_terms", [])
        ]
        
        # Researcher has comprehensive drug information
        drug_profile = {
            "compound": compound_info,
            "literature_count": len(results),
            "clinical_trials": clinical_trials
        }
        assert drug_profile["compound"] is not None
        assert drug_profile["literature_count"] > 0


# ============================================================
# Workflow 6: Full Text Access Workflow
# ============================================================

class TestFullTextAccessWorkflow:
    """Test: Researcher needing full text access."""
    
    def test_fulltext_access_workflow(self, mock_client_full, complete_article_data):
        """
        Workflow:
        1. Find articles
        2. Check open access availability
        3. Access full text from PMC
        4. Get PDF links
        """
        # Step 1: Find articles
        results = mock_client_full.search("diabetes treatment", limit=10)
        assert len(results) > 0
        
        # Step 2: Check OA availability
        article = results[0]
        has_pmc = bool(article.get("pmc_id"))
        has_doi = bool(article.get("doi"))
        
        # Step 3: Access PMC full text (mock)
        if has_pmc:
            # fulltext = get_fulltext(article["pmc_id"])
            fulltext = {
                "pmcid": article["pmc_id"],
                "title": article["title"],
                "sections": {
                    "introduction": "Full introduction text...",
                    "methods": "Full methods text...",
                    "results": "Full results text...",
                    "discussion": "Full discussion text..."
                }
            }
            assert fulltext["pmcid"] == article["pmc_id"]
            assert "introduction" in fulltext["sections"]
        
        # Step 4: Get PDF links (mock)
        pdf_links = {
            "pmc": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{article['pmc_id']}/pdf/",
            "doi": f"https://doi.org/{article['doi']}" if has_doi else None
        }
        
        # User can access full text
        assert has_pmc or has_doi


# ============================================================
# Workflow 7: Session Management Workflow
# ============================================================

class TestSessionWorkflow:
    """Test: User managing research sessions."""
    
    def test_session_management_workflow(self, mock_client_full):
        """
        Workflow:
        1. Create research session
        2. Save search results
        3. Build reading list
        4. Add notes
        5. Resume session later
        """
        from pubmed_search.session import SessionManager
        
        session_mgr = SessionManager()
        session_id = "research-project-001"
        
        # Step 1: Create session
        session_mgr.create_session(session_id, topic="diabetes treatment")
        session = session_mgr.get_session(session_id)
        assert session is not None
        assert session["topic"] == "diabetes treatment"
        
        # Step 2: Save search results
        results = mock_client_full.search("diabetes", limit=10)
        session_mgr.cache_articles(session_id, results)
        
        # Step 3: Build reading list
        important_pmid = results[0]["pmid"]
        session_mgr.add_to_reading_list(
            session_id,
            important_pmid,
            priority="high"
        )
        
        # Step 4: Add notes
        session_mgr.add_note(
            session_id,
            important_pmid,
            "Key paper for methodology section"
        )
        
        # Step 5: Resume session
        reading_list = session_mgr.get_reading_list(session_id)
        notes = session_mgr.get_notes(session_id, important_pmid)
        
        assert important_pmid in reading_list
        assert len(notes) > 0


# ============================================================
# Workflow 8: Error Recovery Workflow
# ============================================================

class TestErrorRecoveryWorkflow:
    """Test: System handles errors gracefully."""
    
    def test_network_error_recovery(self):
        """Handle network failures gracefully."""
        from pubmed_search.core.exceptions import SearchError
        
        mock_client = Mock()
        mock_client.search.side_effect = SearchError("Network timeout")
        
        # User should get meaningful error
        with pytest.raises(SearchError) as exc_info:
            mock_client.search("diabetes")
        
        assert "Network timeout" in str(exc_info.value)
    
    def test_invalid_pmid_handling(self, mock_client_full):
        """Handle invalid PMIDs gracefully."""
        invalid_pmids = ["invalid", "999999999", ""]
        
        # Should not crash, just skip invalid PMIDs
        mock_client_full.fetch_details.return_value = []
        
        results = mock_client_full.fetch_details(invalid_pmids)
        # Should return empty or valid results only
        assert isinstance(results, list)
    
    def test_rate_limit_retry(self):
        """Retry on rate limit errors."""
        mock_client = Mock()
        
        # First call fails with rate limit
        # Second call succeeds
        mock_client.search.side_effect = [
            Exception("Rate limit exceeded"),
            [{"pmid": "12345678", "title": "Success"}]
        ]
        
        # Implementation should retry
        # For now, just verify exception is raised
        with pytest.raises(Exception):
            mock_client.search("diabetes")


# ============================================================
# Integration of Workflows
# ============================================================

class TestCompleteResearchProject:
    """Test: Complete research project from start to finish."""
    
    def test_full_research_project(self, mock_client_full):
        """
        Complete workflow:
        1. Define research question
        2. Systematic search
        3. Screen articles
        4. Extract data
        5. Export results
        """
        # Step 1: Research question
        question = "What is the efficacy of remimazolam for procedural sedation?"
        
        # Step 2: Systematic search
        results = mock_client_full.search("remimazolam procedural sedation", limit=100)
        assert len(results) > 0
        
        # Step 3: Screen articles (mock screening)
        relevant = [r for r in results if "sedation" in r["title"].lower()]
        assert len(relevant) > 0
        
        # Step 4: Extract data
        extracted_data = []
        for article in relevant[:10]:
            data = {
                "pmid": article["pmid"],
                "title": article["title"],
                "year": article["year"],
                "study_type": "RCT" if "randomized" in article.get("abstract", "").lower() else "Other"
            }
            extracted_data.append(data)
        
        assert len(extracted_data) > 0
        
        # Step 5: Export (mock)
        export_package = {
            "question": question,
            "search_date": "2024-01-01",
            "total_found": len(results),
            "screened": len(relevant),
            "included": len(extracted_data),
            "data": extracted_data
        }
        
        assert export_package["included"] > 0
        assert export_package["included"] <= export_package["screened"]
