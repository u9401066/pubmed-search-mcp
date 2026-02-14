"""Comprehensive tests for QueryValidator — PubMed query syntax validation."""

from pubmed_search.application.search.query_validator import (
    VALID_FIELD_TAGS,
    QueryValidationResult,
    QueryValidator,
    _edit_distance,
    _is_close_match,
    validate_query,
)

# ============================================================
# Basic Validation
# ============================================================


class TestBasicValidation:
    def setup_method(self):
        self.v = QueryValidator()

    async def test_valid_simple_query(self):
        r = self.v.validate("aspirin AND stroke")
        assert r.is_valid is True
        assert not r.errors
        assert r.corrected_query is None

    async def test_empty_query(self):
        r = self.v.validate("")
        assert r.is_valid is False
        assert "Empty query" in r.errors[0]

    async def test_whitespace_only_query(self):
        r = self.v.validate("   ")
        assert r.is_valid is False
        assert "Empty query" in r.errors[0]

    async def test_none_like_empty(self):
        # validate_query convenience function handles None → ""
        r = validate_query("")
        assert r.is_valid is False

    async def test_long_query_warning(self):
        long_q = "aspirin " * 1000
        r = self.v.validate(long_q)
        assert any("length" in w for w in r.warnings)

    async def test_normal_length_no_warning(self):
        r = self.v.validate("aspirin AND stroke")
        assert not any("length" in w for w in r.warnings)


# ============================================================
# Parentheses Balance
# ============================================================


class TestParenthesesBalance:
    def setup_method(self):
        self.v = QueryValidator()

    async def test_balanced_parens(self):
        r = self.v.validate("(aspirin OR ibuprofen) AND stroke")
        assert r.is_valid is True

    async def test_nested_balanced(self):
        r = self.v.validate("((A OR B) AND (C OR D))")
        assert r.is_valid is True

    async def test_missing_closing_paren(self):
        r = self.v.validate("(aspirin AND stroke")
        assert r.is_valid is False
        assert any("Unbalanced parentheses" in e for e in r.errors)
        # Corrected query should have closing paren
        assert r.corrected_query is not None
        assert r.corrected_query.count("(") == r.corrected_query.count(")")

    async def test_extra_closing_paren(self):
        r = self.v.validate("aspirin AND stroke)")
        assert r.is_valid is False
        assert any("closing ')' without matching" in e for e in r.errors)

    async def test_multiple_unclosed(self):
        r = self.v.validate("((aspirin AND stroke")
        assert r.is_valid is False
        assert "2 opening" in r.errors[0]

    async def test_parens_inside_quotes_ignored(self):
        """Parentheses inside quotes should not be counted."""
        r = self.v.validate('"heart (failure)" AND stroke')
        assert r.is_valid is True

    async def test_real_mesh_query(self):
        r = self.v.validate('("Aspirin"[MeSH Terms]) AND ("Stroke"[MeSH Terms])')
        assert r.is_valid is True

    async def test_deep_nesting(self):
        r = self.v.validate("(((A AND B) OR C) AND D)")
        assert r.is_valid is True

    async def test_auto_correct_missing_close(self):
        r = self.v.validate("(A AND B")
        assert r.corrected_query == "(A AND B)"


# ============================================================
# Quote Balance
# ============================================================


class TestQuoteBalance:
    def setup_method(self):
        self.v = QueryValidator()

    async def test_balanced_quotes(self):
        r = self.v.validate('"heart failure" AND "stroke prevention"')
        assert r.is_valid is True

    async def test_unbalanced_single_quote(self):
        r = self.v.validate('"aspirin AND stroke')
        assert r.is_valid is False
        assert any("Unbalanced quotes" in e for e in r.errors)

    async def test_odd_number_quotes(self):
        r = self.v.validate('"A" AND "B" AND "C')
        assert r.is_valid is False
        assert "5 double quote" in r.errors[0]

    async def test_auto_correct_adds_closing_quote_before_tag(self):
        r = self.v.validate('"aspirin[Title] AND stroke')
        assert r.corrected_query is not None
        # Should add quote before [Title]
        assert r.corrected_query.count('"') % 2 == 0

    async def test_no_quotes_is_valid(self):
        r = self.v.validate("aspirin AND stroke")
        assert r.is_valid is True

    async def test_mesh_with_quotes(self):
        r = self.v.validate('"Diabetes Mellitus, Type 2"[MeSH]')
        assert r.is_valid is True


# ============================================================
# Field Tag Validation
# ============================================================


class TestFieldTagValidation:
    def setup_method(self):
        self.v = QueryValidator()

    async def test_valid_title_tag(self):
        r = self.v.validate("aspirin[Title]")
        assert r.is_valid is True
        assert not r.errors

    async def test_valid_tiab_tag(self):
        r = self.v.validate("aspirin[tiab]")
        assert r.is_valid is True

    async def test_valid_mesh_tag(self):
        r = self.v.validate('"Aspirin"[MeSH Terms]')
        assert r.is_valid is True

    async def test_valid_mesh_noexp(self):
        r = self.v.validate('"Aspirin"[MeSH:NoExp]')
        assert r.is_valid is True

    async def test_valid_pt_tag(self):
        r = self.v.validate('"Review"[pt]')
        assert r.is_valid is True

    async def test_valid_filter_tag(self):
        r = self.v.validate("(Therapy/Broad[filter])")
        assert r.is_valid is True

    async def test_valid_dp_tag(self):
        r = self.v.validate("2020/01/01:2024/12/31[dp]")
        assert r.is_valid is True

    async def test_valid_language_tag(self):
        r = self.v.validate("eng[la]")
        assert r.is_valid is True

    async def test_valid_author_tag(self):
        r = self.v.validate("Smith J[au]")
        assert r.is_valid is True

    async def test_valid_journal_tag(self):
        r = self.v.validate('"JAMA"[ta]')
        assert r.is_valid is True

    async def test_valid_pmid_tag(self):
        r = self.v.validate("12345678[PMID]")
        assert r.is_valid is True

    async def test_misspelled_tag(self):
        r = self.v.validate("aspirin[Tilte]")
        # Should detect misspelling
        assert any("Invalid field tag" in e or "Unrecognized" in w for e in r.errors for w in r.warnings) or any(
            "Invalid field tag" in e for e in r.errors
        )

    async def test_valid_mesh_tag_lowercase(self):
        r = self.v.validate('"Aspirin"[mesh terms]')
        assert r.is_valid is True

    async def test_case_insensitive_tags(self):
        """All tag checks should be case insensitive."""
        r = self.v.validate("aspirin[TITLE]")
        assert r.is_valid is True

    async def test_multiple_tags(self):
        r = self.v.validate('"aspirin"[MeSH Terms] AND "stroke"[Title/Abstract]')
        assert r.is_valid is True

    async def test_all_standard_tags_valid(self):
        """Spot-check that standard field tags don't raise errors."""
        for tag in ["Title", "tiab", "MeSH Terms", "pt", "dp", "la", "au", "ta", "PMID", "filter", "sb", "1au"]:
            r = self.v.validate(f"test[{tag}]")
            assert r.is_valid, f"Tag [{tag}] should be valid but got: {r.errors}"


# ============================================================
# Boolean Operators
# ============================================================


class TestBooleanOperators:
    def setup_method(self):
        self.v = QueryValidator()

    async def test_valid_and(self):
        r = self.v.validate("A AND B")
        assert r.is_valid is True

    async def test_valid_or(self):
        r = self.v.validate("A OR B")
        assert r.is_valid is True

    async def test_valid_not(self):
        r = self.v.validate("A NOT B")
        assert r.is_valid is True

    async def test_valid_complex(self):
        r = self.v.validate("(A OR B) AND (C NOT D)")
        assert r.is_valid is True

    async def test_consecutive_and(self):
        r = self.v.validate("A AND AND B")
        assert r.is_valid is False
        assert any("Consecutive Boolean" in e for e in r.errors)

    async def test_consecutive_or_and(self):
        r = self.v.validate("A OR AND B")
        assert r.is_valid is False
        assert any("Consecutive Boolean" in e for e in r.errors)

    async def test_leading_and(self):
        r = self.v.validate("AND aspirin")
        assert r.is_valid is False
        assert any("starts with" in e for e in r.errors)

    async def test_leading_or(self):
        r = self.v.validate("OR aspirin")
        assert r.is_valid is False
        assert any("starts with" in e for e in r.errors)

    async def test_trailing_and(self):
        r = self.v.validate("aspirin AND")
        assert r.is_valid is False
        assert any("ends with" in e for e in r.errors)

    async def test_trailing_or(self):
        r = self.v.validate("aspirin OR")
        assert r.is_valid is False
        assert any("ends with" in e for e in r.errors)

    async def test_trailing_not(self):
        r = self.v.validate("aspirin NOT")
        assert r.is_valid is False
        assert any("ends with" in e for e in r.errors)

    async def test_leading_not_warning(self):
        r = self.v.validate("NOT aspirin")
        # NOT at start is a warning, not error (PubMed allows it)
        assert any("starts with NOT" in w for w in r.warnings)

    async def test_boolean_in_quotes_ignored(self):
        """AND/OR/NOT inside quotes should not trigger Boolean checks."""
        r = self.v.validate('"aspirin AND ibuprofen" OR stroke')
        assert r.is_valid is True

    async def test_auto_correct_leading_and(self):
        r = self.v.validate("AND aspirin AND stroke")
        assert r.corrected_query is not None
        assert not r.corrected_query.strip().startswith("AND")

    async def test_auto_correct_trailing_or(self):
        r = self.v.validate("aspirin OR")
        assert r.corrected_query is not None
        assert not r.corrected_query.strip().endswith("OR")


# ============================================================
# Empty Parentheses
# ============================================================


class TestEmptyParentheses:
    def setup_method(self):
        self.v = QueryValidator()

    async def test_empty_parens_warning(self):
        r = self.v.validate("aspirin AND () stroke")
        assert any("empty parentheses" in w for w in r.warnings)

    async def test_empty_parens_with_spaces(self):
        r = self.v.validate("aspirin AND (  ) stroke")
        assert any("empty parentheses" in w for w in r.warnings)


# ============================================================
# Real-World Query Patterns
# ============================================================


class TestRealWorldQueries:
    """Test with realistic query patterns from the codebase."""

    def setup_method(self):
        self.v = QueryValidator()

    async def test_mesh_expanded_query(self):
        """Query generated by SemanticEnhancer._build_mesh_query()."""
        q = '("Diabetes Mellitus"[MeSH Terms] OR "Insulin Resistance"[MeSH Terms]) AND (metformin treatment)'
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_clinical_filter_query(self):
        """Query with clinical query filter appended."""
        q = "aspirin stroke AND (Therapy/Broad[filter])"
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_date_range_query(self):
        """Query with date range filter."""
        q = "aspirin AND stroke AND 2020/01/01:2024/12/31[dp]"
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_age_sex_species_filter(self):
        """Query with demographic filters appended by search.py."""
        q = 'aspirin AND stroke AND "Adult"[MeSH] AND "Male"[MeSH] AND "Humans"[MeSH]'
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_icd_expanded_query(self):
        """Query after ICD code expansion."""
        q = '("Diabetes Mellitus, Type 2"[MeSH] OR E11) AND treatment'
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_strategy_title_query(self):
        """Query from strategy.py with [Title] tags."""
        q = '"aspirin"[Title] AND "stroke"[Title]'
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_strategy_tiab_query(self):
        """Query from strategy.py with [Title/Abstract] tags."""
        q = '"remimazolam"[Title/Abstract] AND "sedation"[Title/Abstract]'
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_publication_type_filter(self):
        """Query with publication type filter."""
        q = 'aspirin AND stroke AND "randomized controlled trial"[pt]'
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_pubtator_entity_query(self):
        """Query built from PubTator entities."""
        q = '"BRCA1"[Gene Name] AND "Breast Neoplasms"[MeSH Terms]'
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_complex_systematic_review_query(self):
        """Complex query for systematic review."""
        q = (
            '(("Propofol"[MeSH Terms] OR "propofol"[Title/Abstract]) '
            'AND ("Remimazolam"[MeSH Terms] OR "remimazolam"[Title/Abstract]) '
            'AND ("Conscious Sedation"[MeSH Terms] OR "sedation"[Title/Abstract]))'
        )
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_relaxation_and_to_or(self):
        """Query after AND→OR relaxation."""
        q = "aspirin OR stroke OR prevention"
        r = self.v.validate(q)
        assert r.is_valid is True

    async def test_auto_relax_core_keywords(self):
        """Query after core keyword extraction."""
        q = "aspirin stroke prevention"
        r = self.v.validate(q)
        assert r.is_valid is True


# ============================================================
# Edge Cases & Error Combinations
# ============================================================


class TestEdgeCases:
    def setup_method(self):
        self.v = QueryValidator()

    async def test_single_word(self):
        r = self.v.validate("aspirin")
        assert r.is_valid is True

    async def test_single_pmid(self):
        r = self.v.validate("12345678")
        assert r.is_valid is True

    async def test_multiple_errors(self):
        """Query with both paren and Boolean errors."""
        r = self.v.validate("AND (aspirin AND")
        assert r.is_valid is False
        assert len(r.errors) >= 2  # leading AND + unbalanced parens

    async def test_corrected_query_fixes_multiple(self):
        """Corrected query should fix all detected issues."""
        r = self.v.validate("AND (aspirin AND stroke")
        assert r.corrected_query is not None
        # Re-validate corrected query
        r2 = self.v.validate(r.corrected_query)
        assert r2.is_valid is True

    async def test_unicode_quotes_in_query(self):
        """Unicode quotes should have been normalized before validator."""
        # But if they slip through, validator should still handle them
        r = self.v.validate("\u201caspirin\u201d AND stroke")
        # These are balanced (even if non-ASCII)
        assert r.is_valid is True  # Non-ASCII quotes don't count as double quotes

    async def test_truncation_wildcard(self):
        """Wildcard * should be valid."""
        r = self.v.validate("cardio* AND stroke")
        assert r.is_valid is True

    async def test_only_boolean(self):
        r = self.v.validate("AND")
        assert r.is_valid is False

    async def test_many_nested_parens(self):
        r = self.v.validate("((((A))))")
        assert r.is_valid is True


# ============================================================
# QueryValidationResult
# ============================================================


class TestValidationResult:
    async def test_summary_valid(self):
        r = QueryValidationResult(is_valid=True)
        assert "✅" in r.summary()

    async def test_summary_errors(self):
        r = QueryValidationResult(is_valid=False, errors=["test error"])
        assert "❌" in r.summary()
        assert "test error" in r.summary()

    async def test_summary_warnings(self):
        r = QueryValidationResult(is_valid=True, warnings=["test warning"])
        assert "⚠️" in r.summary()

    async def test_summary_corrected(self):
        r = QueryValidationResult(is_valid=False, errors=["err"], corrected_query="fixed query")
        assert "💡" in r.summary()

    async def test_has_warnings(self):
        r = QueryValidationResult(is_valid=True, warnings=["w"])
        assert r.has_warnings is True
        r2 = QueryValidationResult(is_valid=True)
        assert r2.has_warnings is False


# ============================================================
# Helper Functions
# ============================================================


class TestHelpers:
    async def test_edit_distance_same(self):
        assert _edit_distance("abc", "abc") == 0

    async def test_edit_distance_one(self):
        assert _edit_distance("abc", "abd") == 1

    async def test_edit_distance_insert(self):
        assert _edit_distance("abc", "abcd") == 1

    async def test_edit_distance_delete(self):
        assert _edit_distance("abcd", "abc") == 1

    async def test_edit_distance_swap(self):
        assert _edit_distance("ab", "ba") == 2

    async def test_edit_distance_empty(self):
        assert _edit_distance("", "abc") == 3

    async def test_close_match_exact(self):
        assert _is_close_match("title", "title") is True

    async def test_close_match_one_off(self):
        assert _is_close_match("tilte", "title") is True

    async def test_close_match_substring(self):
        # _is_close_match has a length diff cutoff of 2, so "mesh" vs "mesh terms" returns False
        # But shorter substrings within the length bound work
        assert _is_close_match("mesh", "messh") is True  # edit distance 1

    async def test_not_close_match(self):
        assert _is_close_match("xyz", "title") is False


# ============================================================
# validate_query convenience function
# ============================================================


class TestConvenienceFunction:
    async def test_valid(self):
        r = validate_query("aspirin AND stroke")
        assert r.is_valid is True

    async def test_invalid(self):
        r = validate_query("(aspirin AND stroke")
        assert r.is_valid is False

    async def test_returns_result_type(self):
        r = validate_query("test")
        assert isinstance(r, QueryValidationResult)


# ============================================================
# Valid field tags coverage
# ============================================================


class TestFieldTagsCoverage:
    """Ensure our VALID_FIELD_TAGS includes all tags used in the codebase."""

    async def test_mesh_terms_is_valid(self):
        assert "mesh terms" in VALID_FIELD_TAGS

    async def test_title_is_valid(self):
        assert "title" in VALID_FIELD_TAGS

    async def test_title_abstract_is_valid(self):
        assert "title/abstract" in VALID_FIELD_TAGS

    async def test_tiab_is_valid(self):
        assert "tiab" in VALID_FIELD_TAGS

    async def test_pt_is_valid(self):
        assert "pt" in VALID_FIELD_TAGS

    async def test_dp_is_valid(self):
        assert "dp" in VALID_FIELD_TAGS

    async def test_la_is_valid(self):
        assert "la" in VALID_FIELD_TAGS

    async def test_au_is_valid(self):
        assert "au" in VALID_FIELD_TAGS

    async def test_filter_is_valid(self):
        assert "filter" in VALID_FIELD_TAGS

    async def test_all_fields_is_valid(self):
        assert "all fields" in VALID_FIELD_TAGS

    async def test_gene_name_is_valid(self):
        assert "gene name" in VALID_FIELD_TAGS

    async def test_mesh_noexp_is_valid(self):
        assert "mesh:noexp" in VALID_FIELD_TAGS

    async def test_majr_is_valid(self):
        assert "majr" in VALID_FIELD_TAGS

    async def test_sb_is_valid(self):
        assert "sb" in VALID_FIELD_TAGS

    async def test_pmid_is_valid(self):
        assert "pmid" in VALID_FIELD_TAGS

    async def test_edat_is_valid(self):
        assert "edat" in VALID_FIELD_TAGS

    async def test_pdat_is_valid(self):
        assert "pdat" in VALID_FIELD_TAGS

    async def test_1au_is_valid(self):
        assert "1au" in VALID_FIELD_TAGS
