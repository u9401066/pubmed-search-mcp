# Advanced Research Workflows

This page provides a centralized, in-depth guide to the core advanced workflows
in PubMed Search MCP: **Research Chronicle (Evolution & Lineage Trees)**,
**Open-i Image Search**, **Uploaded-Image Handoff**, and **Persistent Query Memory**.

## Quick Map

| Need | Start here | Continue with |
| --- | --- | --- |
| See how a topic evolved, branched, and settled over time | `build_research_chronicle` | `read_research_chronicle` |
| Find biomedical images from text (X-ray, histology, CT) | `search_biomedical_images` | `get_article_figures`, `unified_search` |
| Upload or pass an image and search by its visual meaning | `analyze_figure_for_search` | `search_biomedical_images`, `unified_search` |
| Re-open large search/fulltext outputs without rerunning | `read_session(action="artifact")` | `read_session(action="list_artifacts")` |

---

## Research Chronicle / Lineage Tree

![Research Chronicle Architecture and Lineage Flow](images/research-chronicle-lineage-flow.svg)

### 1. Core Principles & Epistemic Model

Traditional literature search returns flat lists that cannot answer fundamental
scientific questions such as: *"How did this field evolve from early mechanisms
to modern clinical practice?"*, *"Where were the landmark paradigm shifts?"*,
and *"What has changed since my last search?"*.

**Research Chronicle** is PubMed Search MCP's versioned research evolution system:

- **Chronological Time Spine (X-axis)**: Publication years form the horizontal
  backbone, ordering scientific milestones chronologically.
- **Thematic Lineage Branches (Y-axis)**: Distinct research lines are
  automatically clustered from shared MeSH descriptors and author keywords,
  branching off from the year of their earliest observed paper.
- **Single Source of Truth**: All projections (time spine, lineage tree,
  mindmap, Mermaid diagrams, narrative Markdown, and JSON) originate from the
  same `ChronicleSnapshot`, ensuring mutual consistency. For a lightweight preview
  inside a normal search response, use `unified_search(options="context_graph")`
  (which generates a preview from the current PMID-backed ranked set rather than a full persisted chronicle).
- **Immutable Versioned Storage**: Each update or continuation atomically
  appends `Revision N+1`, enabling precise longitudinal diffing.
- **Epistemic Rigor**: Missing papers in later revisions are classified as
  `not_observed_in_revision` (absence is not retirement); each snapshot is
  backed by an automated completeness audit.

![Evaluation and Timeline Workflow](images/timeline-evaluation-workflow.svg)

---

### 2. Dual Tool Facades & Output Modes

#### 🛠️ `build_research_chronicle` — Create or Continue a Chronicle

```python
# 1. Build from topic (retrieves PubMed, scores landmarks, clusters lineages)
build_research_chronicle(topic="remimazolam intraoperative", max_events=30)

# 2. Build from previous search results or explicit PMIDs
build_research_chronicle(pmids="last", topic="My Reading List")
build_research_chronicle(pmids="32417976,34999964,36712948", topic="Selected Studies")

# 3. Continue an existing chronicle (inherits stored topic and filters to produce Revision N+1)
build_research_chronicle(chronicle_id="remimazolam-intraoperative-08c229f3")
```

#### 📖 `read_research_chronicle` — Read, Diff, and Analyze Stored Evidence

| Action | Purpose | Example |
| --- | --- | --- |
| `load` | Load a stored revision in any format (defaults to latest) | `read_research_chronicle(chronicle_id="...", output="mermaid")` |
| `list` | List all persisted chronicles with latest revision IDs | `read_research_chronicle(action="list")` |
| `diff` | Compare two revisions (added, unobserved, role shifts, audit) | `read_research_chronicle(action="diff", chronicle_id="...", from_revision=1)` |
| `milestones` | Diagnostic overview of milestone types, years, and landmark scores | `read_research_chronicle(action="milestones", chronicle_id="...")` |
| `compare` | Compare 2–5 topics side-by-side with shared evidence analysis | `read_research_chronicle(action="compare", topics="remimazolam,propofol")` |
| `narrate` | Render evidence-backed Markdown with citations for writing/reporting | `read_research_chronicle(action="narrate", chronicle_id="...", mode="full")` |

#### 🎨 12 Supported Output Formats (`output` parameter)

| Output Format | Type | Description |
| --- | :---: | --- |
| `summary` | Markdown | Default compact summary with chronological spine, research lines, and highlights. |
| `mermaid` | Diagram | **Canonical X-Y lineage tree**. Horizontal year spine + branching research lines + article blocks. |
| `mindmap` | Diagram | **Research lineage mindmap**. Radial Mermaid mindmap diagram. |
| `timeline_mermaid` | Diagram | Flat legacy Mermaid timeline syntax. |
| `chronicle_map` | JSON | Complete diagram coordinate contract for custom frontend renderers. |
| `timeline` | JSON | Chronological projection JSON ordered strictly by publication date. |
| `tree` | JSON | Thematic lineage tree JSON organized into branch and sub-branch hierarchies. |
| `graph` | JSON | Typed provenance graph (Topic → Branch → Entry → EvidenceArticle). |
| `evidence` | JSON | Deduplicated evidence articles with per-source counts. |
| `milestones` | JSON | Milestone distributions, year spread, citation metrics, and landmark rankings. |
| `narrative` | Markdown | Academic prose narrative with inline PMID/DOI citations. |
| `json` | JSON | Complete immutable snapshot dictionary. |

---

### 3. Concrete Example: Remimazolam Intraoperative Lineage

The following diagrams illustrate the research evolution of **Remimazolam in intraoperative anesthesia and sedation** (2020–2026):

#### Example 1: X-Axis Time Spine + Y-Axis Lineage Branches (`output="mermaid"`)

```mermaid
flowchart LR
    n_topic["Topic: Remimazolam Intraoperative Anesthesia (2020-2026)"]

    %% X-axis Time Spine
    n_y2020["Year 2020"]
    n_y2021["Year 2021"]
    n_y2022["Year 2022"]
    n_y2023["Year 2023"]
    n_y2024["Year 2024"]
    n_y2025["Year 2025"]
    n_y2026["Year 2026"]

    n_topic ==> n_y2020
    n_y2020 --> n_y2021
    n_y2021 --> n_y2022
    n_y2022 --> n_y2023
    n_y2023 --> n_y2024
    n_y2024 --> n_y2025
    n_y2025 --> n_y2026

    %% Y-axis Research Lineage Branches
    b_propofol["Branch: Propofol Comparator & Hemodynamics (24 entries)"]
    b_remi["Branch: Remimazolam Clinical Trials & Indications (3 entries)"]
    b_general["Branch: General Anesthesia & Complex Surgery (5 entries)"]
    b_sedatives["Branch: Sedation Depth & Neuromonitoring (6 entries)"]
    b_benzo["Branch: Benzodiazepines & Reversal (2 entries)"]

    %% Branch points at earliest observed year
    n_y2020 --> b_propofol
    n_y2021 --> b_remi
    n_y2022 --> b_sedatives
    n_y2024 --> b_general
    n_y2025 --> b_benzo

    %% Key Entry Blocks
    e_2020_phase2["[2020-08] Phase 2/3 Trial (PMID: 32417976)<br/>Doi et al. Non-inferior efficacy to propofol, significantly less hypotension"]
    e_2021_cardiac["[2021-03] Case Study (PMID: 33677710)<br/>Cardiopulmonary bypass cardiac surgery exploration"]
    e_2022_sedation["[2022-04] Observational Study (PMID: 34999964)<br/>EEG/BIS depth of sedation monitoring indices"]
    e_2023_delirium["[2023-01] Safety Alert / RCT (PMID: 36712948)<br/>Postoperative delirium reduction in elderly orthopedics"]
    e_2023_sleep["[2023-08] RCT (PMID: 37055671)<br/>Improved postoperative sleep quality after joint replacement"]
    e_2024_rct["[2024-03] RCT (PMID: 38541158)<br/>Hemodynamic stability in laparoscopic & thoracoscopic surgery"]
    e_2024_meta["[2024-07] Meta-Analysis (PMID: 39069837)<br/>Safety meta-analysis across complex surgical procedures"]
    e_2025_sr["[2025-01] Systematic Review (PMID: 39832842)<br/>Perioperative neurocognitive disorders & organ protection"]
    e_2025_tavi["[2025-03] RCT (PMID: 39715979)<br/>Transcatheter aortic valve implantation (TAVI) vs sevoflurane"]
    e_2026_seizure["[2026] Clinical Cohort (PMID: 42299573)<br/>Intraoperative seizure incidence during awake craniotomy"]

    %% Connect entries to branches and years
    b_propofol --> e_2020_phase2
    b_remi --> e_2021_cardiac
    b_sedatives --> e_2022_sedation
    b_propofol --> e_2023_delirium
    b_remi --> e_2023_sleep
    b_propofol --> e_2024_rct
    b_propofol --> e_2024_meta
    b_propofol --> e_2025_sr
    b_general --> e_2025_tavi
    b_sedatives --> e_2026_seizure

    n_y2020 -.-> e_2020_phase2
    n_y2021 -.-> e_2021_cardiac
    n_y2022 -.-> e_2022_sedation
    n_y2023 -.-> e_2023_delirium
    n_y2024 -.-> e_2024_meta
    n_y2025 -.-> e_2025_tavi
    n_y2026 -.-> e_2026_seizure

    %% Styles
    classDef topic fill:#0f172a,color:#ffffff,stroke:#0f172a,stroke-width:2px;
    classDef spine fill:#dbeafe,color:#1e3a8a,stroke:#2563eb,stroke-width:2px;
    classDef branch fill:#ecfeff,color:#164e63,stroke:#0891b2,stroke-width:2px;
    classDef event fill:#ffffff,color:#111827,stroke:#94a3b8,stroke-width:1px;
    classDef landmark fill:#fef3c7,color:#92400e,stroke:#f59e0b,stroke-width:2px;

    class n_topic topic;
    class n_y2020,n_y2021,n_y2022,n_y2023,n_y2024,n_y2025,n_y2026 spine;
    class b_propofol,b_remi,b_general,b_sedatives,b_benzo branch;
    class e_2021_cardiac,e_2022_sedation,e_2023_delirium,e_2023_sleep,e_2024_rct,e_2025_tavi,e_2026_seizure event;
    class e_2020_phase2,e_2024_meta,e_2025_sr landmark;
```

---

#### Example 2: Research Lineage Mindmap (`output="mindmap"`)

```mermaid
mindmap
  root["Remimazolam Intraoperative Lineage"]
    branch_propofol["Propofol Comparator Line"]
      entry_p1["2020 — Phase 2b/3 Landmark Trial (PMID: 32417976)"]
      entry_p2["Hemodynamics: Significant hypotension reduction"]
      entry_p3["Injection site pain virtually eliminated"]
      entry_p4["2024-2025 Multicenter Meta-Analyses"]
    branch_neuro["Depth of Sedation & Neurocognitive"]
      entry_n1["EEG / BIS spectral index characteristics"]
      entry_n2["Postoperative delirium incidence reduction"]
      entry_n3["Perioperative neurocognitive disorder (PND) mitigation"]
    branch_cardio["Cardiovascular & Complex Surgery"]
      entry_c1["Transcatheter aortic valve implantation (TAVI)"]
      entry_c2["Coronary artery bypass grafting (CABG)"]
      entry_c3["High-risk critical illness general anesthesia"]
    branch_antidote["Emergence & Flumazenil Reversal"]
      entry_a1["Flumazenil specific rapid reversal capability"]
      entry_a2["Emergence agitation evaluation"]
      entry_a3["Tissue carboxylesterase-1 (CES-1) rapid hydrolysis"]
```

---

#### Example 3: Landmark Paper Bidirectional Citation Tree (`build_citation_tree`)

Grounded on the foundational 2020 trial by **Doi et al. (PMID: 32417976)**:

```mermaid
graph TD
    %% Root Paper
    pmid_32417976(["<b>Doi Matsuyuki et al. (2020)</b><br/>Efficacy & safety of remimazolam vs propofol<br/>[PMID: 32417976 | Phase IIb/III Trial]"])

    %% Forward Citations (Latest Clinical Implementations)
    pmid_42225960["Ni et al. (2026)<br/>Weight-based dose scaling comparison"]
    pmid_41987344["Kimura et al. (2026)<br/>Pediatric sedation and anesthesia"]
    pmid_41954614["Morimoto et al. (2026)<br/>Effect-site concentration monitoring (Ce)"]
    pmid_41926002["Kotani et al. (2026)<br/>Postoperative hemodynamic stability"]

    %% Backward References (Pharmacological Foundation)
    pmid_23653886("Chitilian et al. (2013)<br/>Novel esterase-cleaved anesthetic development")
    pmid_10215689("Tuk et al. (1999)<br/>GABAA pharmacodynamic modeling")
    pmid_22531340("Egan et al. (2012)<br/>Metabolically labile sedative architectures")

    %% Edges
    pmid_42225960 --> pmid_32417976
    pmid_41987344 --> pmid_32417976
    pmid_41954614 --> pmid_32417976
    pmid_41926002 --> pmid_32417976

    pmid_32417976 --> pmid_23653886
    pmid_32417976 --> pmid_10215689
    pmid_23653886 --> pmid_22531340

    %% Styles
    style pmid_32417976 fill:#e74c3c,stroke:#c0392b,stroke-width:3px,color:#fff
    style pmid_42225960 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_41987344 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_41954614 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_41926002 fill:#3498db,stroke:#2980b9,color:#fff
    style pmid_23653886 fill:#2ecc71,stroke:#27ae60,color:#fff
    style pmid_10215689 fill:#2ecc71,stroke:#27ae60,color:#fff
    style pmid_22531340 fill:#2ecc71,stroke:#27ae60,color:#fff
```

---

#### Example 4: Topic-to-Topic Comparison (`action="compare"`)

Comparing `remimazolam intraoperative` (2020–2026) with `propofol intraoperative` (1991–2026):

```json
{
  "projection": "comparison",
  "summary": {
    "earliest_research": 1991,
    "latest_research": 2026,
    "shared_evidence_count": 7
  },
  "shared_evidence": [
    { "evidence_id": "pmid:32417976", "shared_by": ["remimazolam", "propofol"] },
    { "evidence_id": "pmid:36712948", "shared_by": ["remimazolam", "propofol"] },
    { "evidence_id": "pmid:38494158", "shared_by": ["remimazolam", "propofol"] },
    { "evidence_id": "pmid:39832842", "shared_by": ["remimazolam", "propofol"] }
  ]
}
```

---

## Open-i Biomedical Image Search

Use `search_biomedical_images` when the visual finding is already text and the
goal is image evidence from Open-i.

```python
search_biomedical_images("chest X-ray pneumonia", sources="openi", image_type="x", limit=10)
search_biomedical_images("histology liver fibrosis", sources="openi", image_type="mc", license_type="by")
```

Open-i expects English medical terminology. For non-English prompts, the agent
should first translate anatomy, finding, and modality into English, then call
`search_biomedical_images`. Open-i is strongest for radiology, microscopy,
clinical photos, and teaching images; for article-native figures, use
`get_article_figures` on PMC Open Access articles.

---

## Uploaded Image To Literature Search

`analyze_figure_for_search` is the handoff tool for images supplied by an MCP
client. It accepts an image URL or a base64/data-URI image and returns MCP
`ImageContent` plus instructions for the LLM agent.

```python
analyze_figure_for_search(image="data:image/png;base64,...", search_type="medical")
```

The server does not perform standalone visual diagnosis. The intended workflow
is:

1. The MCP client passes the uploaded image or image URL to `analyze_figure_for_search`.
2. The LLM agent uses its vision capability to describe the image and extract English biomedical search terms.
3. The agent immediately continues with `search_biomedical_images` for similar biomedical images or `unified_search` for related papers.

---

## Persistent Query Memory

When session persistence is configured, large `unified_search` and
`get_fulltext` outputs can be saved as artifacts. The immediate tool response can
stay compact while the reusable payload remains available for later reads.

```python
read_session(action="list_artifacts")
read_session(action="artifact", artifact_id="...")
read_session(action="artifact", artifact_uri="artifact://...")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="audit.json")
read_session(action="artifact", artifact_uri="artifact://...", artifact_file="results.json", offset=0, max_chars=200000)
```

Artifacts are query memory, not a second search. Reading them does not rerun
external source calls. Local filesystem paths are redacted by default because
remote clients cannot read server-local paths. Set
`PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` only for local agents.

---

## Verification Status

The primary 45-tool MCP server directly exposes:

- Research chronicle: `build_research_chronicle`, `read_research_chronicle`
- Image search: `search_biomedical_images`
- Uploaded image handoff: `analyze_figure_for_search`
- Query memory: `read_session(action="artifact")`

These capabilities are guarded by docs alignment tests, tool registry tests,
image-search tests, vision-search tests, timeline tests, and session artifact
tests.
remote clients cannot read the server host path. Set
`PUBMED_ARTIFACT_INCLUDE_LOCAL_PATHS=true` only for local MCP clients that really
need `local_path` and `manifest_path`.

For `unified_search`, artifact files are intentionally richer than the immediate
MCP response. Read `audit.json` first for completeness warnings, then
`query_strategy.json` for the executed source/query plan, then `results.json` or
`results.toon` for the full article list. This keeps response tokens small while
leaving enough evidence for repeated agent reads, sandboxed clients, and future
remote artifact backends.

## Verification Status

The current primary 45-tool MCP server exposes these tools directly:

- Research chronicle: `build_research_chronicle`, `read_research_chronicle`
- Image search: `search_biomedical_images`
- Uploaded-image handoff: `analyze_figure_for_search`
- Query memory: `read_session(action="artifact")`

Coverage is guarded by docs alignment tests, tool registry tests, image-search
tests, vision-search tests, timeline tests, and session artifact tests.
