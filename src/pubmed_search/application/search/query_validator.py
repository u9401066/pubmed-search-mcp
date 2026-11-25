"""
QueryValidator - PubMed/Entrez Query Syntax Validation

Pre-flight validation for PubMed queries before sending to NCBI API.
Catches syntax errors that would cause silent failures or unexpected results.

Validation checks:
- P0: Parentheses balancing
- P0: Quote balancing
- P1: Valid field tags
- P1: Empty Boolean operands
- P1: Query length limit
- P2: Dangling Boolean operators
- P2: Double operators

Example:
    >>> validator = QueryValidator()
    >>> result = validator.validate('"aspirin[Title] AND stroke')
    >>> result.is_valid
    False
    >>> result.errors
    ['Unbalanced quotes: 1 opening quote(s) without closing']
    >>> result.corrected_query
    '"aspirin"[Title] AND stroke'
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pubmed_search.domain.services.pubmed_boolean import PUBMED_BOOLEAN_OPERATORS, misspelled_operator

# Maximum query length for PubMed (conservative estimate)
MAX_QUERY_LENGTH = 4096

# Valid PubMed field tags (case-insensitive match)
# Reference: https://pubmed.ncbi.nlm.nih.gov/help/#search-tags
VALID_FIELD_TAGS = frozenset(
    {
        # Core search fields
        "title",
        "ti",
        "title/abstract",
        "tiab",
        "abstract",
        "ab",
        "text word",
        "tw",
        "all fields",
        "all",
        # MeSH
        "mesh terms",
        "mh",
        "mh:noexp",
        "mesh",
        "mesh major topic",
        "majr",
        "majr:noexp",
        "mesh subheading",
        "sh",
        "mesh:noexp",
        # Publication info
        "journal",
        "ta",
        "volume",
        "vi",
        "issue",
        "ip",
        "page",
        "pg",
        "publication type",
        "pt",
        "publication date",
        "dp",
        "date - publication",
        # Date fields
        "edat",
        "pdat",
        "mdat",
        "entrez date",
        "crdt",
        # Author fields
        "author",
        "au",
        "first author",
        "1au",
        "last author",
        "lastau",
        "full author name",
        "fau",
        "corporate author",
        "cn",
        "author identifier",
        "auid",
        # IDs
        "pmid",
        "doi",
        "pmcid",
        "lid",
        "aid",
        # Organism/language
        "language",
        "la",
        "humans",
        "animals",
        # Other
        "affiliation",
        "ad",
        "filter",
        "sb",
        "subset",
        "book",
        "ed",
        "isbn",
        "grant number",
        "gr",
        "investigator",
        "ir",
        "pharmacological action",
        "pa",
        "supplementary concept",
        "nm",
        "place of publication",
        "pl",
        "publisher",
        "pubn",
        # Gene-specific
        "gene name",
        "gene",
        # Other searchable fields
        "other term",
        "ot",
        "conflict of interest",
        "cois",
        "space flight mission",
        "mhda",
        "date - mesh",
    }
)

# Pattern to match field tags in a query
_FIELD_TAG_CAPTURE = re.compile(r"\[([^\]]+)\]")

# Boolean operators as PubMed spells them (AND, OR/or, NOT/not; see pubmed_boolean),
# delimited like PubMed words: by whitespace, parentheses or quotes, not inside "Do-Not-Resuscitate".
_OPERATOR = "(?:" + "|".join(sorted(PUBMED_BOOLEAN_OPERATORS, key=len, reverse=True)) + ")"
_START, _STOP = r'(?<![^\s()"])', r'(?![^\s()"])'
_CONSECUTIVE_OPERATORS = re.compile(rf"{_START}{_OPERATOR}\s+{_OPERATOR}{_STOP}")
_LEADING_AND_OR = re.compile(rf"^\s*(?:AND|OR|or){_STOP}")
_TRAILING_OPERATOR = re.compile(rf"{_START}{_OPERATOR}\s*$")
_LEADING_NOT = re.compile(rf"^\s*(?:NOT|not){_STOP}")
_OPERATOR_LOOKALIKE = re.compile(rf"{_START}(?i:and|or|not){_STOP}")
# A lowercase "and" after a complete term, followed by bare words and a field tag: PubMed
# searches it as part of that phrase (delirium[tiab] and pacu[tiab] -> "and pacu"[tiab]).
_GLUED_AND = re.compile(r'[\])"]\s+and\s+((?:[^\s()"\[\]]+\s+)*[^\s()"\[\]]+)\s*\[')


def pubmed_field_tags(query: str) -> list[str]:
    """Return known PubMed field tags for planning and fallback dialect checks."""
    return sorted(
        {
            match.group(1).strip()
            for match in _FIELD_TAG_CAPTURE.finditer(query)
            if match.group(1).strip().lower() in VALID_FIELD_TAGS
        }
    )


@dataclass
class QueryValidationResult:
    """Result of query syntax validation."""

    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    corrected_query: str | None = None

    @property
    def has_warnings(self) -> bool:
        return len(self.warnings) > 0

    def summary(self) -> str:
        """Human-readable summary."""
        if self.is_valid and not self.warnings:
            return "✅ Query syntax is valid"
        parts = []
        if self.errors:
            parts.append(f"❌ {len(self.errors)} error(s): {'; '.join(self.errors)}")
        if self.warnings:
            parts.append(f"⚠️ {len(self.warnings)} warning(s): {'; '.join(self.warnings)}")
        if self.corrected_query:
            parts.append(f"💡 Suggested: {self.corrected_query}")
        return " | ".join(parts)


class QueryValidator:
    """
    PubMed query syntax validator.

    Validates query strings before they are sent to NCBI Entrez API.
    Can optionally auto-correct common issues.
    """

    def validate(self, query: str) -> QueryValidationResult:
        """
        Validate a PubMed query string.

        Checks (in order):
        1. Empty/whitespace-only query
        2. Query length
        3. Parentheses balance
        4. Quote balance
        5. Field tag validity
        6. Boolean operator issues
        7. Empty parentheses

        Args:
            query: The PubMed query string to validate.

        Returns:
            QueryValidationResult with errors, warnings, and optional correction.
        """
        errors: list[str] = []
        warnings: list[str] = []
        corrected = query

        # 1. Empty query
        if not query or not query.strip():
            return QueryValidationResult(
                is_valid=False,
                errors=["Empty query"],
            )

        # 2. Query length
        if len(query) > MAX_QUERY_LENGTH:
            warnings.append(
                f"Query length ({len(query)}) exceeds recommended limit "
                f"({MAX_QUERY_LENGTH}). PubMed may truncate or reject it."
            )

        # 3. Parentheses balance
        paren_result = self._check_parentheses(query)
        if paren_result:
            errors.append(paren_result)
            corrected = self._fix_parentheses(corrected)

        # 4. Quote balance
        quote_result = self._check_quotes(query)
        if quote_result:
            errors.append(quote_result)
            corrected = self._fix_quotes(corrected)

        # 5. Field tag validity
        tag_errors, tag_warnings = self._check_field_tags(query)
        errors.extend(tag_errors)
        warnings.extend(tag_warnings)

        # 6. Boolean operator issues
        bool_errors, bool_warnings = self._check_boolean_operators(query)
        errors.extend(bool_errors)
        warnings.extend(bool_warnings)
        if bool_errors:
            corrected = self._fix_boolean_operators(corrected)

        # 7. Empty parentheses
        if re.search(r"\(\s*\)", corrected):
            warnings.append("Query contains empty parentheses '()'. This may cause unexpected results.")
            corrected = re.sub(r"\(\s*\)", "", corrected)
            corrected = re.sub(r"\s+", " ", corrected).strip()

        is_valid = len(errors) == 0

        return QueryValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            corrected_query=corrected if corrected != query else None,
        )

    # ================================================================
    # Check methods
    # ================================================================

    @staticmethod
    def _check_parentheses(query: str) -> str | None:
        """Check if parentheses are balanced. Returns error message or None."""
        # Skip parentheses inside quotes
        in_quote = False
        depth = 0
        for ch in query:
            if ch == '"' and not in_quote:
                in_quote = True
            elif ch == '"' and in_quote:
                in_quote = False
            elif not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth < 0:
                        return "Unbalanced parentheses: closing ')' without matching opening '('"

        if depth > 0:
            return f"Unbalanced parentheses: {depth} opening '(' without matching closing ')'"
        return None

    @staticmethod
    def _check_quotes(query: str) -> str | None:
        """Check if double quotes are balanced. Returns error message or None."""
        # Count quotes not escaped (simple: just count all double quotes)
        count = query.count('"')
        if count % 2 != 0:
            return f"Unbalanced quotes: {count} double quote(s) found (should be even)"
        return None

    @staticmethod
    def _check_field_tags(query: str) -> tuple[list[str], list[str]]:
        """Check field tag validity. Returns (errors, warnings)."""
        errors: list[str] = []
        warnings: list[str] = []

        for match in _FIELD_TAG_CAPTURE.finditer(query):
            tag = match.group(1).strip()
            tag_lower = tag.lower()

            # Check for date range format: YYYY/MM/DD:YYYY/MM/DD[dp]
            # The date range is part of the preceding text, not the tag
            if tag_lower in VALID_FIELD_TAGS:
                continue

            # Check common misspellings
            close_matches = sorted(t for t in VALID_FIELD_TAGS if _is_close_match(tag_lower, t))
            if close_matches:
                errors.append(f"Invalid field tag [{tag}]. Did you mean [{close_matches[0]}]?")
            else:
                warnings.append(f"Unrecognized field tag [{tag}]. This may be valid but is not in our known tags list.")

        return errors, warnings

    @staticmethod
    def _check_boolean_operators(query: str) -> tuple[list[str], list[str]]:
        """Check for Boolean operator issues. Returns (errors, warnings)."""
        errors: list[str] = []
        warnings: list[str] = []

        # Remove quoted strings for Boolean analysis
        stripped = re.sub(r'"[^"]*"', '""', query)

        # Check for consecutive Boolean operators: AND AND, OR OR, etc.
        if _CONSECUTIVE_OPERATORS.search(stripped):
            errors.append(
                "Consecutive Boolean operators detected (e.g., 'AND AND' or 'OR NOT' without operand between)"
            )

        # Check for leading Boolean operator
        stripped_trimmed = stripped.strip()
        if _LEADING_AND_OR.match(stripped_trimmed):
            errors.append("Query starts with a Boolean operator (AND/OR). Missing left operand.")

        # Check for trailing Boolean operator
        if _TRAILING_OPERATOR.search(stripped_trimmed):
            errors.append("Query ends with a Boolean operator. Missing right operand.")

        # Check NOT at start (valid in PubMed but warn)
        if _LEADING_NOT.match(stripped_trimmed):
            warnings.append("Query starts with NOT. PubMed may interpret this differently than expected.")

        # Spellings of and/or/not that PubMed searches as words.
        for word in dict.fromkeys(match.group() for match in _OPERATOR_LOOKALIKE.finditer(stripped)):
            if misspelled_operator(word):
                warnings.append(
                    f"'{word}' is not a PubMed operator; PubMed searches it as a word. Only AND, OR/or and "
                    f"NOT/not are operators: use {word.upper()}."
                )
        for match in _GLUED_AND.finditer(stripped):
            warnings.append(
                f"Lowercase 'and' is not a PubMed operator; before a tagged phrase PubMed searches it as part of "
                f'the phrase ("and {" ".join(match.group(1).split())}"). Use AND.'
            )

        return errors, warnings

    # ================================================================
    # Fix methods (best-effort auto-correction)
    # ================================================================

    @staticmethod
    def _fix_parentheses(query: str) -> str:
        """Best-effort fix for unbalanced parentheses."""
        # Count balance
        in_quote = False
        depth = 0
        for ch in query:
            if ch == '"':
                in_quote = not in_quote
            elif not in_quote:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1

        if depth > 0:
            # Missing closing parens
            query = query + ")" * depth
        elif depth < 0:
            # Remove excess closing parens from the right
            excess = abs(depth)
            result = list(query)
            for i in range(len(result) - 1, -1, -1):
                if result[i] == ")" and excess > 0:
                    result[i] = ""
                    excess -= 1
                    if excess == 0:
                        break
            query = "".join(result)

        return query

    @staticmethod
    def _fix_quotes(query: str) -> str:
        """Best-effort fix for unbalanced quotes."""
        count = query.count('"')
        if count % 2 != 0:
            # Try to find the unmatched quote and close it
            # Simple heuristic: add closing quote before the next field tag or at end
            in_quote = False
            result = list(query)
            last_open = -1
            for i, ch in enumerate(query):
                if ch == '"':
                    if not in_quote:
                        in_quote = True
                        last_open = i
                    else:
                        in_quote = False
            if in_quote and last_open >= 0:
                # Find the next '[' or end of query after the last open quote
                bracket_pos = query.find("[", last_open + 1)
                if bracket_pos > 0:
                    result.insert(bracket_pos, '"')
                else:
                    result.append('"')
            query = "".join(result)
        return query

    @staticmethod
    def _fix_boolean_operators(query: str) -> str:
        """Fix common Boolean operator issues (operators spelled as PubMed reads them)."""
        # Remove leading AND/OR
        query = re.sub(rf"^\s*(?:AND|OR|or){_STOP}\s*", "", query)
        # Remove trailing AND/OR/NOT
        query = re.sub(rf"\s+{_OPERATOR}\s*$", "", query)
        # Fix consecutive operators (keep the first one)
        return re.sub(rf"{_START}({_OPERATOR})\s+{_OPERATOR}{_STOP}", r"\1", query)


def _is_close_match(a: str, b: str) -> bool:
    """Check if two strings are close matches (edit distance ≤ 2)."""
    if abs(len(a) - len(b)) > 2:
        return False
    # Simple character-level comparison
    if a == b:
        return True
    # Check if one is a substring of the other
    if a in b or b in a:
        return True
    # Simple edit distance check (Levenshtein ≤ 2)
    return _edit_distance(a, b) <= 2


def _edit_distance(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) > len(b):
        a, b = b, a
    distances: list[int] = list(range(len(a) + 1))
    for j, ch_b in enumerate(b):
        new_distances = [j + 1]
        for i, ch_a in enumerate(a):
            if ch_a == ch_b:
                new_distances.append(distances[i])
            else:
                new_distances.append(1 + min(distances[i], distances[i + 1], new_distances[-1]))
        distances = new_distances
    return distances[-1]


def validate_query(query: str) -> QueryValidationResult:
    """Convenience function to validate a PubMed query."""
    return QueryValidator().validate(query)
