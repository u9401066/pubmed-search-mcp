"""
Policy tables for ImageQueryAdvisor.

This module keeps tunable keyword packs and policy thresholds separate from
the advisor orchestration and scorer implementation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from re import Pattern


def _keyword_set(*keywords: str) -> frozenset[str]:
    return frozenset(keyword.lower() for keyword in keywords)


@dataclass(frozen=True)
class KeywordScoringRule:
    """A keyword pack that contributes to image suitability scoring."""

    name: str
    keywords: frozenset[str]
    score_per_hit: float
    max_contribution: float
    direction: int = 1
    reason: str = ""


@dataclass(frozen=True)
class ImageTypePolicy:
    """Policy entry for recommending a specific image type."""

    image_type: str
    keywords: frozenset[str]
    reason: str
    coarse_category: str | None = None


@dataclass(frozen=True)
class CollectionPolicy:
    """Policy entry for recommending a specific Open-i collection."""

    collection: str
    keywords: frozenset[str]
    min_hits: int
    reason: str


@dataclass(frozen=True)
class QueryCleanupRule:
    """Regex-based cleanup rule for query enhancement."""

    name: str
    pattern: Pattern[str]


SUITABILITY_THRESHOLD = 0.3
TYPE_SUITABILITY_WEIGHT = 0.2
TYPE_SUITABILITY_CAP = 0.6

SUITABILITY_RULES: tuple[KeywordScoringRule, ...] = (
    KeywordScoringRule(
        name="explicit_image_terms",
        keywords=_keyword_set(
            "image",
            "images",
            "picture",
            "pictures",
            "photo",
            "photos",
            "photograph",
            "scan",
            "scans",
            "x-ray",
            "xray",
            "x ray",
            "radiograph",
            "radiography",
            "ct scan",
            "mri",
            "ultrasound",
            "echocardiography",
            "mammography",
            "fluoroscopy",
            "microscopy",
            "histology",
            "histopathology",
            "pathology",
            "cytology",
            "biopsy",
            "slide",
            "staining",
            "figure",
            "illustration",
            "diagram",
            "chart",
            "clinical appearance",
            "gross appearance",
            "visual",
            "morphology",
            "anatomy",
            "dermoscopy",
            "endoscopy",
            "fundoscopy",
            "ophthalmoscopy",
            "angiography",
            "圖片",
            "影像",
            "照片",
            "x光",
            "x射線",
            "掃描",
            "顯微鏡",
            "組織學",
            "病理",
            "切片",
        ),
        score_per_hit=0.3,
        max_contribution=0.9,
        reason="明確影像詞彙",
    ),
    KeywordScoringRule(
        name="anatomical_visual_context",
        keywords=_keyword_set(
            "fracture",
            "dislocation",
            "effusion",
            "opacity",
            "consolidation",
            "infiltrate",
            "nodule",
            "mass",
            "tumor",
            "tumour",
            "cyst",
            "abscess",
            "stenosis",
            "occlusion",
            "aneurysm",
            "edema",
            "oedema",
            "hemorrhage",
            "haemorrhage",
            "atrophy",
            "hypertrophy",
            "calcification",
            "erosion",
            "deformity",
            "swelling",
        ),
        score_per_hit=0.15,
        max_contribution=0.45,
        reason="解剖或病灶可視化語境",
    ),
    KeywordScoringRule(
        name="non_image_terms",
        keywords=_keyword_set(
            "pharmacokinetics",
            "pharmacodynamics",
            "mechanism of action",
            "drug interaction",
            "dosing",
            "dosage",
            "protocol",
            "guideline",
            "guidelines",
            "meta-analysis",
            "systematic review",
            "randomized",
            "randomised",
            "clinical trial",
            "rct",
            "prevalence",
            "incidence",
            "epidemiology",
            "statistics",
            "gene expression",
            "molecular",
            "genomics",
            "proteomics",
            "biomarker",
            "pathway",
            "signaling",
            "receptor",
            "cost-effectiveness",
            "economic",
            "policy",
            "survey",
            "questionnaire",
            "interview",
            "藥物動力學",
            "藥理",
            "劑量",
            "指南",
            "統合分析",
            "系統性回顧",
            "隨機",
            "臨床試驗",
            "流行病學",
            "基因表達",
            "分子",
            "生物標記",
        ),
        score_per_hit=0.25,
        max_contribution=0.75,
        direction=-1,
        reason="非影像研究詞彙",
    ),
)

IMAGE_TYPE_POLICIES: tuple[ImageTypePolicy, ...] = (
    ImageTypePolicy(
        image_type="x",
        keywords=_keyword_set(
            "x-ray",
            "xray",
            "x ray",
            "radiograph",
            "radiography",
            "chest",
            "lung",
            "thorax",
            "bone",
            "fracture",
            "skeletal",
            "spine",
            "vertebra",
            "pelvis",
            "abdomen",
            "abdominal",
            "mammography",
            "mammogram",
            "fluoroscopy",
            "barium",
            "angiography",
            "angiogram",
            "pneumonia",
            "pneumothorax",
            "pleural",
            "effusion",
            "cardiomegaly",
            "mediastinal",
            "x光",
            "胸部",
            "骨折",
            "脊椎",
            "腹部",
        ),
        reason="偵測到放射學/X光相關關鍵字",
        coarse_category="radiology",
    ),
    ImageTypePolicy(
        image_type="c",
        keywords=_keyword_set(
            "ct",
            "ct scan",
            "computed tomography",
            "ct angiography",
            "cta",
            "hrct",
            "contrast enhanced",
            "hounsfield",
            "axial",
            "coronal",
            "sagittal",
            "ct abdomen",
            "ct chest",
            "ct head",
            "ct brain",
            "ct spine",
            "電腦斷層",
            "斷層掃描",
        ),
        reason="偵測到 CT/電腦斷層相關關鍵字",
        coarse_category="radiology",
    ),
    ImageTypePolicy(
        image_type="m",
        keywords=_keyword_set(
            "mri",
            "magnetic resonance",
            "magnetic resonance imaging",
            "t1 weighted",
            "t2 weighted",
            "flair",
            "dwi",
            "diffusion",
            "gadolinium",
            "contrast enhanced mri",
            "brain mri",
            "spine mri",
            "knee mri",
            "mr angiography",
            "mra",
            "mrcp",
            "磁振造影",
            "核磁共振",
        ),
        reason="偵測到 MRI/磁振造影相關關鍵字",
        coarse_category="radiology",
    ),
    ImageTypePolicy(
        image_type="p",
        keywords=_keyword_set(
            "pet",
            "pet scan",
            "pet-ct",
            "pet/ct",
            "positron emission",
            "positron emission tomography",
            "fdg",
            "suv",
            "standardized uptake",
            "nuclear medicine",
            "scintigraphy",
            "spect",
            "正子造影",
            "正子掃描",
        ),
        reason="偵測到 PET/正子造影相關關鍵字",
        coarse_category="radiology",
    ),
    ImageTypePolicy(
        image_type="u",
        keywords=_keyword_set(
            "ultrasound",
            "ultrasonography",
            "sonography",
            "sonogram",
            "echocardiography",
            "echocardiogram",
            "echo",
            "doppler",
            "b-mode",
            "m-mode",
            "transesophageal",
            "transthoracic",
            "obstetric ultrasound",
            "fetal ultrasound",
            "abdominal ultrasound",
            "renal ultrasound",
            "thyroid ultrasound",
            "breast ultrasound",
            "超音波",
            "心臟超音波",
        ),
        reason="偵測到超音波/心臟超音波相關關鍵字",
        coarse_category="ultrasound",
    ),
    ImageTypePolicy(
        image_type="mc",
        keywords=_keyword_set(
            "histology",
            "histological",
            "histopathology",
            "histopathological",
            "microscopy",
            "microscopic",
            "micrograph",
            "pathology",
            "pathological",
            "cytology",
            "cytological",
            "biopsy",
            "tissue",
            "specimen",
            "staining",
            "stain",
            "h&e",
            "hematoxylin",
            "eosin",
            "immunohistochemistry",
            "ihc",
            "slide",
            "section",
            "thin section",
            "cell",
            "cells",
            "cellular",
            "tumor",
            "tumour",
            "neoplasm",
            "granuloma",
            "fibrosis",
            "necrosis",
            "inflammation",
            "顯微鏡",
            "組織學",
            "病理",
            "切片",
            "染色",
            "細胞",
        ),
        reason="偵測到顯微鏡/組織學/病理相關關鍵字",
        coarse_category="microscopy",
    ),
    ImageTypePolicy(
        image_type="ph",
        keywords=_keyword_set(
            "photo",
            "photograph",
            "photography",
            "clinical photo",
            "clinical appearance",
            "gross appearance",
            "gross pathology",
            "skin",
            "dermatology",
            "dermatological",
            "rash",
            "lesion",
            "wound",
            "ulcer",
            "burn",
            "scar",
            "eye",
            "ophthalmology",
            "fundus",
            "retina",
            "endoscopy",
            "endoscopic",
            "colonoscopy",
            "bronchoscopy",
            "surgery",
            "surgical",
            "intraoperative",
            "anatomical",
            "cadaver",
            "dissection",
            "照片",
            "皮膚",
            "傷口",
            "內視鏡",
            "手術",
        ),
        reason="偵測到臨床照片/皮膚/內視鏡相關關鍵字",
        coarse_category="photo",
    ),
    ImageTypePolicy(
        image_type="g",
        keywords=_keyword_set(
            "diagram",
            "schematic",
            "illustration",
            "drawing",
            "flowchart",
            "flow chart",
            "algorithm",
            "graph",
            "chart",
            "plot",
            "figure",
            "infographic",
            "visualization",
            "anatomical diagram",
            "pathway diagram",
            "decision tree",
            "clinical pathway",
            "圖表",
            "流程圖",
            "示意圖",
            "插圖",
        ),
        reason="偵測到圖表/示意圖/流程圖相關關鍵字",
        coarse_category="graphics",
    ),
)

STRONG_IMAGE_TYPE_CODES = ("x", "c", "m", "p", "u", "mc", "ph")

COLLECTION_POLICIES: tuple[CollectionPolicy, ...] = (
    CollectionPolicy(
        collection="cxr",
        keywords=_keyword_set(
            "chest x-ray",
            "chest xray",
            "chest radiograph",
            "cxr",
            "pa view",
            "ap view",
            "lateral chest",
            "chest film",
            "胸部x光",
            "胸片",
        ),
        min_hits=2,
        reason="查詢高度偏向胸部 X 光，建議使用 cxr 專集",
    ),
    CollectionPolicy(
        collection="mpx",
        keywords=_keyword_set(
            "teaching",
            "clinical case",
            "case study",
            "educational",
            "medpix",
            "teaching image",
            "教學",
            "臨床案例",
            "教學影像",
        ),
        min_hits=1,
        reason="查詢含教學/案例相關詞彙，MedPix 提供高品質教學影像",
    ),
    CollectionPolicy(
        collection="hmd",
        keywords=_keyword_set(
            "history of medicine",
            "historical",
            "vintage",
            "medical history",
            "antique",
            "醫學史",
        ),
        min_hits=1,
        reason="查詢含醫學史相關詞彙",
    ),
)

POST_2020_KEYWORDS = _keyword_set(
    "covid-19",
    "sars-cov-2",
    "omicron",
    "delta variant",
    "monkeypox",
    "mpox",
    "long covid",
    "2021",
    "2022",
    "2023",
    "2024",
    "2025",
    "2026",
    "chatgpt",
    "gpt-4",
    "large language model",
    "llm",
    "新冠",
    "猴痘",
    "長新冠",
)

YEAR_PATTERN = re.compile(r"\b(202[1-9]|20[3-9]\d)\b")

QUERY_CLEANUP_RULES: tuple[QueryCleanupRule, ...] = (
    QueryCleanupRule(
        name="study_design_noise",
        pattern=re.compile(r"\b(?:systematic review|meta-analysis|rct|randomized)\b"),
    ),
    QueryCleanupRule(
        name="guideline_noise",
        pattern=re.compile(r"\b(?:guideline|protocol|consensus)\b"),
    ),
    QueryCleanupRule(
        name="recency_noise",
        pattern=re.compile(r"\b(?:recent|latest|2020s?|2021|2022|2023|2024|2025|2026)\b"),
    ),
)

NON_ENGLISH_EXAMPLES = """
常見醫學術語翻譯範例 (Examples for Agent):
- 喉頭水腫 → laryngeal edema
- 肺炎 → pneumonia
- 骨折 → fracture
- 胸部X光 → chest X-ray
- 心臟超音波 → echocardiography
- 電腦斷層 → CT scan
- 磁振造影 → MRI
"""

NON_LATIN_PATTERN = re.compile(
    r"[\u4e00-\u9fff"
    r"\u3040-\u309f"
    r"\u30a0-\u30ff"
    r"\uac00-\ud7af"
    r"\u0400-\u04ff"
    r"\u0600-\u06ff"
    r"\u0e00-\u0e7f]"
)

TYPE_LABELS: dict[str, str] = {
    "x": "X-ray/X光 (x)",
    "c": "CT Scan/電腦斷層 (c)",
    "m": "MRI/磁振造影 (m)",
    "mc": "Microscopy/顯微鏡 (mc)",
    "p": "PET/正子造影 (p)",
    "ph": "Photographs/臨床照片 (ph)",
    "u": "Ultrasound/超音波 (u)",
    "g": "Graphics/圖表 (g)",
    "xg": "Exclude Graphics/排除圖表 (xg)",
    "xm": "Exclude Multipanel/排除多格圖 (xm)",
}
