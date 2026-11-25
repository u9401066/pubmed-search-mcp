"""
Policy tables for milestone detection heuristics.

Keeps regex, publication-type, and citation-threshold heuristics separate
from MilestoneDetector orchestration so rules stay inspectable and tunable.
"""

from __future__ import annotations

from dataclasses import dataclass

from pubmed_search.domain.entities.timeline import MilestoneType


@dataclass(frozen=True)
class RegexMilestonePolicy:
    """Regex-based rule for title/abstract milestone detection."""

    name: str
    pattern: str
    milestone_type: MilestoneType
    label: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class PublicationTypeMilestonePolicy:
    """Publication-type lookup rule for milestone detection."""

    name: str
    publication_type: str
    milestone_type: MilestoneType
    label: str
    confidence: float
    reason: str


@dataclass(frozen=True)
class CitationThresholdPolicy:
    """Citation threshold rule for landmark study detection."""

    name: str
    minimum_citations: int
    label: str
    confidence: float
    reason: str
    emit_event: bool = True


DEFAULT_TITLE_PATTERN_POLICIES: tuple[RegexMilestonePolicy, ...] = (
    RegexMilestonePolicy(
        name="fda_approval",
        pattern=r"\b(FDA|US Food and Drug Administration)\s+(approv|clear|authoriz)",
        milestone_type=MilestoneType.FDA_APPROVAL,
        label="FDA Approval",
        confidence=0.95,
        reason="監管核准關鍵字命中 FDA 核准語境",
    ),
    RegexMilestonePolicy(
        name="ema_approval",
        pattern=r"\b(EMA|European Medicines Agency)\s+(approv|authoriz)",
        milestone_type=MilestoneType.EMA_APPROVAL,
        label="EMA Approval",
        confidence=0.95,
        reason="監管核准關鍵字命中 EMA 核准語境",
    ),
    RegexMilestonePolicy(
        name="regulatory_approval",
        pattern=r"\bregulatory\s+approv",
        milestone_type=MilestoneType.REGULATORY_APPROVAL,
        label="Regulatory Approval",
        confidence=0.8,
        reason="命中一般性監管核准語句",
    ),
    RegexMilestonePolicy(
        name="phase_3_trial",
        pattern=r"\b(phase\s*(?:III|3)\b|pivotal\s+trial)",
        milestone_type=MilestoneType.PHASE_3,
        label="Phase 3 Trial",
        confidence=0.9,
        reason="命中第三期或 pivotal trial 詞彙",
    ),
    RegexMilestonePolicy(
        name="phase_2_trial",
        pattern=r"\b(phase\s*(?:II|2)\b|dose[- ]?find)",
        milestone_type=MilestoneType.PHASE_2,
        label="Phase 2 Trial",
        confidence=0.85,
        reason="命中第二期或 dose-finding 詞彙",
    ),
    RegexMilestonePolicy(
        name="phase_1_trial",
        pattern=r"\b(phase\s*(?:I|1)\b|first[- ]?in[- ]?human|FIH)",
        milestone_type=MilestoneType.PHASE_1,
        label="Phase 1 Trial",
        confidence=0.85,
        reason="命中第一期或 first-in-human 詞彙",
    ),
    RegexMilestonePolicy(
        name="phase_4_study",
        pattern=r"\b(phase\s*(?:IV|4)\b|post[- ]?market)",
        milestone_type=MilestoneType.PHASE_4,
        label="Phase 4 Study",
        confidence=0.85,
        reason="命中第四期或 post-market 詞彙",
    ),
    RegexMilestonePolicy(
        name="meta_analysis",
        pattern=r"\b(meta[- ]?analysis|pooled\s+analysis)",
        milestone_type=MilestoneType.META_ANALYSIS,
        label="Meta-Analysis",
        confidence=0.9,
        reason="命中統合分析或 pooled analysis 詞彙",
    ),
    RegexMilestonePolicy(
        name="systematic_review",
        pattern=r"\bsystematic\s+review",
        milestone_type=MilestoneType.SYSTEMATIC_REVIEW,
        label="Systematic Review",
        confidence=0.9,
        reason="命中系統性回顧詞彙",
    ),
    RegexMilestonePolicy(
        name="guideline",
        pattern=r"\b(guideline|recommendation|consensus\s+statement)",
        milestone_type=MilestoneType.GUIDELINE,
        label="Clinical Guideline",
        confidence=0.85,
        reason="命中 guideline 或 recommendation 詞彙",
    ),
    RegexMilestonePolicy(
        name="consensus",
        pattern=r"\b(expert\s+consensus|panel\s+recommendation)",
        milestone_type=MilestoneType.CONSENSUS,
        label="Expert Consensus",
        confidence=0.8,
        reason="命中 expert consensus 類語句",
    ),
    RegexMilestonePolicy(
        name="mechanism_discovery",
        pattern=r"\b(mechanism\s+of\s+action|pharmacodynamic|receptor\s+binding)",
        milestone_type=MilestoneType.MECHANISM_DISCOVERY,
        label="Mechanism Discovery",
        confidence=0.75,
        reason="命中機轉或受體結合相關語句",
    ),
    RegexMilestonePolicy(
        name="preclinical",
        pattern=r"\b(preclinical|animal\s+model|in\s+vivo\s+study)",
        milestone_type=MilestoneType.PRECLINICAL,
        label="Preclinical Study",
        confidence=0.7,
        reason="命中前臨床或動物模型語境",
    ),
    RegexMilestonePolicy(
        name="safety_alert",
        # Reporting adverse events is routine in trials and cohorts; only an
        # explicit safety communication or boxed warning is a safety alert.
        pattern=(
            r"\b(safety\s+(?:alert|communication|warning|signal)"
            r"|black[- ]box(?:ed)?\s+warning|boxed\s+warning"
            r"|(?:FDA|EMA|MHRA|PMDA|regulatory)\s+(?:safety\s+)?warning)"
        ),
        milestone_type=MilestoneType.SAFETY_ALERT,
        label="Safety Alert",
        confidence=0.85,
        reason="命中明確的安全警訊、安全通報或 boxed warning 詞彙",
    ),
    RegexMilestonePolicy(
        name="label_update",
        pattern=r"\b(label\s+update|indication.*expand|new\s+indication)",
        milestone_type=MilestoneType.LABEL_UPDATE,
        label="Label Update",
        confidence=0.8,
        reason="命中適應症擴增或 label 更新語句",
    ),
    RegexMilestonePolicy(
        name="withdrawal",
        pattern=r"\b(withdraw|recall|market\s+removal)",
        milestone_type=MilestoneType.WITHDRAWAL,
        label="Market Withdrawal",
        confidence=0.9,
        reason="命中 withdraw 或 recall 語境",
    ),
    RegexMilestonePolicy(
        name="breakthrough",
        pattern=r"\b(breakthrough|paradigm\s+shift|revolutioniz)",
        milestone_type=MilestoneType.BREAKTHROUGH,
        label="Breakthrough Discovery",
        confidence=0.7,
        reason="命中 breakthrough 或 paradigm shift 語句",
    ),
    RegexMilestonePolicy(
        name="controversy",
        pattern=r"\b(controver|debate|challenge|dispute)",
        milestone_type=MilestoneType.CONTROVERSY,
        label="Scientific Debate",
        confidence=0.65,
        reason="命中爭議或辯論詞彙",
    ),
)


DEFAULT_PUBTYPE_POLICIES: tuple[PublicationTypeMilestonePolicy, ...] = (
    PublicationTypeMilestonePolicy(
        name="rct",
        publication_type="Randomized Controlled Trial",
        milestone_type=MilestoneType.RANDOMIZED_TRIAL,
        label="RCT",
        confidence=0.9,
        reason="PubMed publication type 標示為 RCT；未明示試驗 phase，不推論為 Phase III",
    ),
    PublicationTypeMilestonePolicy(
        name="phase_1_pubtype",
        publication_type="Clinical Trial, Phase I",
        milestone_type=MilestoneType.PHASE_1,
        label="Phase 1 Trial",
        confidence=0.9,
        reason="PubMed publication type 標示為第一期試驗",
    ),
    PublicationTypeMilestonePolicy(
        name="phase_2_pubtype",
        publication_type="Clinical Trial, Phase II",
        milestone_type=MilestoneType.PHASE_2,
        label="Phase 2 Trial",
        confidence=0.9,
        reason="PubMed publication type 標示為第二期試驗",
    ),
    PublicationTypeMilestonePolicy(
        name="phase_3_pubtype",
        publication_type="Clinical Trial, Phase III",
        milestone_type=MilestoneType.PHASE_3,
        label="Phase 3 Trial",
        confidence=0.95,
        reason="PubMed publication type 標示為第三期試驗",
    ),
    PublicationTypeMilestonePolicy(
        name="phase_4_pubtype",
        publication_type="Clinical Trial, Phase IV",
        milestone_type=MilestoneType.PHASE_4,
        label="Phase 4 Study",
        confidence=0.9,
        reason="PubMed publication type 標示為第四期試驗",
    ),
    PublicationTypeMilestonePolicy(
        name="meta_analysis_pubtype",
        publication_type="Meta-Analysis",
        milestone_type=MilestoneType.META_ANALYSIS,
        label="Meta-Analysis",
        confidence=0.95,
        reason="PubMed publication type 標示為 Meta-Analysis",
    ),
    PublicationTypeMilestonePolicy(
        name="systematic_review_pubtype",
        publication_type="Systematic Review",
        milestone_type=MilestoneType.SYSTEMATIC_REVIEW,
        label="Systematic Review",
        confidence=0.95,
        reason="PubMed publication type 標示為 Systematic Review",
    ),
    PublicationTypeMilestonePolicy(
        name="guideline_pubtype",
        publication_type="Guideline",
        milestone_type=MilestoneType.GUIDELINE,
        label="Clinical Guideline",
        confidence=0.95,
        reason="PubMed publication type 標示為 Guideline",
    ),
    PublicationTypeMilestonePolicy(
        name="practice_guideline_pubtype",
        publication_type="Practice Guideline",
        milestone_type=MilestoneType.GUIDELINE,
        label="Practice Guideline",
        confidence=0.95,
        reason="PubMed publication type 標示為 Practice Guideline",
    ),
    PublicationTypeMilestonePolicy(
        name="consensus_conference_pubtype",
        publication_type="Consensus Development Conference",
        milestone_type=MilestoneType.CONSENSUS,
        label="Consensus Conference",
        confidence=0.9,
        reason="PubMed publication type 標示為 Consensus Development Conference",
    ),
    PublicationTypeMilestonePolicy(
        name="consensus_statement_pubtype",
        publication_type="Consensus Statement",
        milestone_type=MilestoneType.CONSENSUS,
        label="Consensus Statement",
        confidence=0.9,
        reason="PubMed publication type 標示為 Consensus Statement",
    ),
)


DEFAULT_CITATION_THRESHOLD_POLICIES: tuple[CitationThresholdPolicy, ...] = (
    CitationThresholdPolicy(
        name="exceptional",
        minimum_citations=500,
        label="Landmark Study",
        confidence=0.9,
        reason="引用數達 exceptional threshold",
    ),
    CitationThresholdPolicy(
        name="high",
        minimum_citations=200,
        label="High-Impact Study",
        confidence=0.8,
        reason="引用數達 high-impact threshold",
    ),
    CitationThresholdPolicy(
        name="notable",
        minimum_citations=100,
        label="Notable Study",
        confidence=0.7,
        reason="引用數達 notable threshold",
    ),
    CitationThresholdPolicy(
        name="moderate",
        minimum_citations=50,
        label="Moderately Cited Study",
        confidence=0.0,
        reason="引用數達 moderate threshold，但預設不單獨升級成 milestone 事件",
        emit_event=False,
    ),
)


_TRIAL_PHASES = frozenset({MilestoneType.PHASE_1, MilestoneType.PHASE_2, MilestoneType.PHASE_3, MilestoneType.PHASE_4})
_SYNTHESIS = frozenset({MilestoneType.META_ANALYSIS, MilestoneType.SYSTEMATIC_REVIEW})
_GUIDANCE = frozenset({MilestoneType.GUIDELINE, MilestoneType.CONSENSUS})
_COMMUNICATIONS = frozenset(
    {
        MilestoneType.FDA_APPROVAL,
        MilestoneType.EMA_APPROVAL,
        MilestoneType.REGULATORY_APPROVAL,
        MilestoneType.SAFETY_ALERT,
        MilestoneType.WITHDRAWAL,
        MilestoneType.LABEL_UPDATE,
        MilestoneType.CONTROVERSY,
    }
)

#: Text-pattern milestones that may refine a record whose study design PubMed
#: publication types already state, keyed by ``indexed_design_family``. The
#: publication type is the authority: a title or abstract pattern can add
#: specificity the type vocabulary lacks (a trial phase), but cannot relabel an
#: indexed trial or synthesis as a safety alert, approval, debate or
#: breakthrough. An observational study may carry a trial phase (extension or
#: post-marketing follow-up) or an explicit safety signal (pharmacovigilance),
#: as it did before indexed designs were consulted. Records whose publication
#: types state no design, including MeSH-only designs, accept every title
#: pattern.
TEXT_MILESTONES_COMPATIBLE_WITH_INDEXED_DESIGN: dict[str, frozenset[MilestoneType]] = {
    "trial": _TRIAL_PHASES,
    "evidence_synthesis": _SYNTHESIS,
    "guidance": _GUIDANCE,
    "observational": _TRIAL_PHASES | {MilestoneType.SAFETY_ALERT},
    "review": _SYNTHESIS | _GUIDANCE | {MilestoneType.CONTROVERSY, MilestoneType.MECHANISM_DISCOVERY},
    "case_report": frozenset(),
    "commentary": _COMMUNICATIONS,
    "protocol": frozenset(),
    "publication_notice": frozenset(),
    "other": _TRIAL_PHASES | _SYNTHESIS | {MilestoneType.MECHANISM_DISCOVERY, MilestoneType.PRECLINICAL},
}

#: Design families that report no results of their own: a trial protocol or a
#: notice (erratum, retraction, expression of concern) is never a milestone,
#: whatever trial publication types or title wording it carries.
NON_MILESTONE_DESIGN_FAMILIES = frozenset({"protocol", "publication_notice"})

#: Abstracts describe background literature and routine outcomes (adverse
#: events, recommendations, prior approvals), so abstract matching is limited
#: to self-describing design policies and to records without an indexed design.
ABSTRACT_PATTERN_POLICY_NAMES = frozenset(
    {"phase_1_trial", "phase_2_trial", "phase_3_trial", "phase_4_study", "meta_analysis", "systematic_review"}
)


TITLE_PATTERNS = [
    (policy.pattern, policy.milestone_type, policy.label, policy.confidence)
    for policy in DEFAULT_TITLE_PATTERN_POLICIES
]

PUBTYPE_PATTERNS = {
    policy.publication_type: (policy.milestone_type, policy.label, policy.confidence)
    for policy in DEFAULT_PUBTYPE_POLICIES
}

LANDMARK_CITATION_THRESHOLDS = {policy.name: policy.minimum_citations for policy in DEFAULT_CITATION_THRESHOLD_POLICIES}
