# MCP Visual Data Retrieval Enhancement Specification

> **Version**: 1.1.0  
> **Date**: 2026-02-25  
> **Status**: Draft (Reviewed)  
> **Author**: AI-assisted design  
> **Target**: PubMed Search MCP Server  
> **Last Review**: 2026-02-25

---

## 1. Problem Statement

### 1.1 Current Limitation

現有 PubMed Search MCP Server 在處理文章圖表（figures）時存在明顯缺口：

| 現有工具 | 行為 | 問題 |
|----------|------|------|
| `get_fulltext` | 回傳 markdown 純文字，僅包含 "Figure 1 illustrates..." 等文字引用 | **無圖片 URL、無 caption 結構、無圖片資料** |
| `search_biomedical_images` | 搜尋 Open-i 放射/臨床影像 | **不適用於文章中的架構圖、流程圖、統計圖** |
| `fetch_article_details` | 回傳 metadata（標題、作者、摘要） | **完全不含 figure 資訊** |

### 1.2 Impact

- 研究者無法透過 AI Agent 檢視文章架構圖、實驗結果圖
- 無法進行跨文章的視覺化比較（如比較多篇論文的系統架構）
- 文獻回顧時遺漏重要視覺資訊
- Agent 只能「知道有 Figure 1」卻無法取得或描述其內容

### 1.3 Evidence

以 PMID 40384072（Multi-Agent Approach for Sepsis Management）為例：
- PubMed 網頁可看到 4 張圖片（Figure 1-4）
- 圖片託管於 PMC CDN：`https://cdn.ncbi.nlm.nih.gov/pmc/blobs/{hash}/{pmcid}/{hash}/{filename}.gif`
- `get_fulltext` 僅回傳文中提及 figure 的文字段落
- `search_biomedical_images` 回傳 0 結果

---

## 2. Design Goals

| 優先序 | 目標 | 描述 |
|--------|------|------|
| P0 | **結構化 Figure 擷取** | 從 PMC 文章中擷取 figure metadata（label, caption, image URL） |
| P1 | **增強 get_fulltext** | 在現有全文回傳中嵌入 figure 結構化資料 |
| P2 | **圖片內容分析** | 利用 Vision LLM 描述/分析圖片內容 |
| P3 | **圖表資料提取** | 從 bar chart / table image 中提取數值資料 |

### 2.1 Non-Goals (v1.0)

- 不處理 supplementary materials 中的圖片（未來版本）
- 不處理付費牆後的圖片（僅限 Open Access）
- 不進行圖片的本地儲存或快取（由呼叫端決定）
- 不修改既有 tool 的 breaking change

---

## 3. Data Sources

### 3.1 可用 API 及優先順序

| 優先序 | 來源 | Endpoint | 格式 | Figure 資訊 |
|--------|------|----------|------|-------------|
| 1 | **PMC E-utilities (efetch)** | `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={PMCID}&rettype=xml` | JATS XML | `<fig>` 元素含 `<label>`, `<caption>`, `<graphic xlink:href>` |
| 2 | **Europe PMC REST** | `https://www.ebi.ac.uk/europepmc/webservices/rest/{PMCID}/fullTextXML` | JATS XML | 同上，Europe PMC 有自己的圖片 CDN |
| 3 | **PMC BioC API** | `https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_json/{PMCID}/unicode` | BioC JSON | `passages` with `infon.type = "fig_caption"` |
| 4 | **PMC OA Web Service** | `https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={PMCID}` | XML | 提供文章 tar.gz 包的下載連結（含圖片原檔） |

### 3.2 JATS XML Figure 結構

PMC JATS XML 中 figure 的典型結構：

```xml
<fig id="f1-hir-2025-31-2-209">
  <label>Figure 1</label>
  <caption>
    <title>Architecture and data flow diagram</title>
    <p>Architecture and data flow of the multi-agent sepsis management
       system showing the interaction between three specialized agents.</p>
  </caption>
  <graphic xlink:href="hir-2025-31-2-209f1"
           xmlns:xlink="http://www.w3.org/1999/xlink"/>
</fig>
```

### 3.3 圖片 URL 組合規則

PMC CDN 圖片 URL 格式：

```
https://cdn.ncbi.nlm.nih.gov/pmc/blobs/{blob_hash}/{pmcid_numeric}/{file_hash}/{filename}.{ext}
```

**取得方式**：
- **方法 A**（推薦）：從 PMC OA Web Service 取得文章 package URL，再解析其中的圖片路徑
- **方法 B**：從文章 HTML 頁面的 `<img>` tag 中擷取完整 CDN URL
- **方法 C**：使用 PMC image API（較新）：`https://www.ncbi.nlm.nih.gov/pmc/articles/{PMCID}/figure/{fig_id}/`

Europe PMC 圖片 URL 格式：

```
https://europepmc.org/articles/{PMCID}/bin/{filename}.{ext}
```

---

## 4. New Tool Specifications

### 4.1 Tool: `get_article_figures`

> **優先序**：P0（核心功能）

#### 4.1.1 Description

從 PMC Open Access 文章中擷取所有 figure 的結構化資料，包括 label、caption 和圖片 URL。

#### 4.1.2 Input Schema

```json
{
  "name": "get_article_figures",
  "description": "Get structured figure metadata (label, caption, image URL) from a PMC Open Access article. Returns figures with their captions and direct image URLs.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "pmid": {
        "type": "string",
        "description": "PubMed ID. Will be resolved to PMCID automatically."
      },
      "pmcid": {
        "type": "string",
        "description": "PubMed Central ID (e.g., 'PMC12086443'). Preferred over PMID."
      },
      "include_subfigures": {
        "type": "boolean",
        "default": false,
        "description": "Whether to parse sub-figures (e.g., Figure 3A, 3B, 3C) as separate entries."
      },
      "include_tables": {
        "type": "boolean",
        "default": false,
        "description": "Whether to also extract table images (for tables rendered as images)."
      },
      "include_supplementary": {
        "type": "boolean",
        "default": false,
        "description": "Whether to include supplementary figures."
      }
    },
    "oneOf": [
      {"required": ["pmid"]},
      {"required": ["pmcid"]}
    ]
  }
}
```

#### 4.1.3 Output Schema

```json
{
  "type": "object",
  "properties": {
    "pmid": { "type": "string" },
    "pmcid": { "type": "string" },
    "article_title": { "type": "string" },
    "total_figures": { "type": "integer" },
    "figures": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "figure_id": {
            "type": "string",
            "description": "XML element ID, e.g., 'f1-hir-2025-31-2-209'"
          },
          "label": {
            "type": "string",
            "description": "Display label, e.g., 'Figure 1'"
          },
          "caption_title": {
            "type": ["string", "null"],
            "description": "Figure title from <title> element within <caption>"
          },
          "caption_text": {
            "type": "string",
            "description": "Full caption text from <caption><p> elements"
          },
          "image_url": {
            "type": "string",
            "description": "Direct URL to the figure image (GIF/PNG/JPG)"
          },
          "image_url_large": {
            "type": ["string", "null"],
            "description": "URL to high-resolution version if available"
          },
          "graphic_href": {
            "type": "string",
            "description": "Raw xlink:href from JATS XML, e.g., 'hir-2025-31-2-209f1'"
          },
          "subfigures": {
            "type": ["array", "null"],
            "items": {
              "type": "object",
              "properties": {
                "subfigure_id": { "type": "string" },
                "label": { "type": "string" },
                "caption_text": { "type": "string" },
                "image_url": { "type": ["string", "null"] }
              }
            },
            "description": "Sub-figures if include_subfigures=true and supported"
          },
          "mentioned_in_sections": {
            "type": "array",
            "items": { "type": "string" },
            "description": "Section names where this figure is referenced in text"
          }
        },
        "required": ["figure_id", "label", "caption_text", "image_url"]
      }
    },
    "tables_as_images": {
      "type": ["array", "null"],
      "description": "Table images if include_tables=true"
    },
    "supplementary_figures": {
      "type": ["array", "null"],
      "description": "Supplementary figures if include_supplementary=true"
    },
    "source": {
      "type": "string",
      "enum": ["pmc_efetch", "europepmc", "bioc", "pmc_oa_package"],
      "description": "Which data source was used (first successful)"
    },
    "is_open_access": { "type": "boolean" }
  },
  "required": ["pmcid", "total_figures", "figures", "source", "is_open_access"]
}
```

#### 4.1.4 Example Output

```json
{
  "pmid": "40384072",
  "pmcid": "PMC12086443",
  "article_title": "Multi-Agent Approach for Sepsis Management",
  "total_figures": 4,
  "figures": [
    {
      "figure_id": "f1-hir-2025-31-2-209",
      "label": "Figure 1",
      "caption_title": "Architecture and data flow diagram",
      "caption_text": "Architecture and data flow of the multi-agent sepsis management system showing the interaction between three specialized agents.",
      "image_url": "https://cdn.ncbi.nlm.nih.gov/pmc/blobs/671c/12086443/f00885b1d671/hir-2025-31-2-209f1.gif",
      "image_url_large": null,
      "graphic_href": "hir-2025-31-2-209f1",
      "subfigures": null,
      "mentioned_in_sections": ["Methods", "Results"]
    },
    {
      "figure_id": "f2-hir-2025-31-2-209",
      "label": "Figure 2",
      "caption_title": null,
      "caption_text": "Retrieval-augmented generation approach for integrating clinical guidelines.",
      "image_url": "https://cdn.ncbi.nlm.nih.gov/pmc/blobs/671c/12086443/c25c7a1fd617/hir-2025-31-2-209f2.gif",
      "image_url_large": null,
      "graphic_href": "hir-2025-31-2-209f2",
      "subfigures": null,
      "mentioned_in_sections": ["Methods"]
    }
  ],
  "tables_as_images": null,
  "supplementary_figures": null,
  "source": "pmc_efetch",
  "is_open_access": true
}
```

#### 4.1.5 Implementation Logic

```
get_article_figures(pmid?, pmcid?):
  1. Resolve identifiers
     - If only pmid → call id_converter API to get pmcid
     - If only pmcid → proceed
     - If neither → error

  2. Try Layer 1: PMC efetch XML
     a. GET efetch.fcgi?db=pmc&id={pmcid_numeric}&rettype=xml
     b. Parse JATS XML
     c. For each <fig> element:
        - Extract figure_id from @id attribute
        - Extract label from <label>
        - Extract caption from <caption>/<title> and <caption>/<p>
        - Extract graphic_href from <graphic @xlink:href>
     d. Resolve image URLs:
        - Try PMC CDN pattern
        - Fallback: fetch article HTML page, extract <img> src for each figure
     e. If successful → return results

  3. Try Layer 2: Europe PMC fullTextXML
     a. GET europepmc REST endpoint
     b. Same JATS XML parsing as Layer 1
     c. Use Europe PMC CDN for image URLs

  4. Try Layer 3: BioC JSON
     a. GET BioC API endpoint
     b. Filter passages where infon.type == "fig_caption"
     c. Extract text, but image URLs may not be available
     d. Return with image_url = null where unavailable

  5. Error handling:
     - Article not in PMC → return error with message
     - Article not Open Access → return { is_open_access: false, figures: [] }
     - All layers fail → return error with attempted sources
```

#### 4.1.6 Error Cases

| Scenario | Response |
|----------|----------|
| PMID has no PMCID | `{ error: "no_pmc", message: "Article not available in PMC" }` |
| Article not Open Access | `{ is_open_access: false, total_figures: 0, figures: [] }` |
| PMC XML 無 `<fig>` 元素 | `{ total_figures: 0, figures: [], note: "No figures found in article XML" }` |
| 所有 API 失敗 | `{ error: "source_unavailable", attempted: ["pmc_efetch", "europepmc", "bioc"] }` |
| PMID/PMCID 不存在 | `{ error: "not_found", message: "Article not found" }` |

---

### 4.2 Enhancement: `get_fulltext` — `include_figures` parameter

> **優先序**：P1

#### 4.2.1 Change Description

在現有 `get_fulltext` tool 中新增 `include_figures` 選用參數。

#### 4.2.2 Input Change

```diff
  get_fulltext(
    pmcid: string,
    sections?: string,      // existing
+   include_figures?: boolean  // NEW, default: false
  )
```

#### 4.2.3 Output Change

當 `include_figures=true` 時，在回傳的全文 markdown 中：

**Before（現行行為）：**
```markdown
## Methods
... The architecture of our system is shown in Figure 1. ...
```

**After（增強行為）：**
```markdown
## Methods
... The architecture of our system is shown in Figure 1. ...

---
### 📊 Figures

#### Figure 1
**Caption:** Architecture and data flow of the multi-agent sepsis management system.
**Image URL:** https://cdn.ncbi.nlm.nih.gov/pmc/blobs/671c/12086443/f00885b1d671/hir-2025-31-2-209f1.gif

#### Figure 2
**Caption:** Retrieval-augmented generation approach for integrating clinical guidelines.
**Image URL:** https://cdn.ncbi.nlm.nih.gov/pmc/blobs/671c/12086443/c25c7a1fd617/hir-2025-31-2-209f2.gif
```

#### 4.2.4 Backward Compatibility

- 預設 `include_figures=false`，不影響現有行為
- 新增的 figure section 附加在全文末尾，不修改原有文字段落

---

### 4.3 Tool: `describe_figure`

> **優先序**：P2（需要 Vision LLM 支援）

#### 4.3.1 Description

使用 Vision LLM 對文章中的圖片進行內容描述和分析。適用於無法直接查看圖片的 text-only AI Agent。

#### 4.3.2 Input Schema

```json
{
  "name": "describe_figure",
  "description": "Use Vision LLM to describe and analyze a figure image from a scientific article. Useful for text-only AI agents that cannot view images directly.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "image_url": {
        "type": "string",
        "description": "Direct URL to the figure image. Typically obtained from get_article_figures."
      },
      "caption": {
        "type": "string",
        "description": "Figure caption for context (improves accuracy)."
      },
      "article_context": {
        "type": "string",
        "description": "Brief article context (title + relevant text) to guide interpretation."
      },
      "question": {
        "type": "string",
        "description": "Specific question about the figure, e.g., 'How many agents are in this architecture?' If not provided, generates a general description."
      },
      "detail_level": {
        "type": "string",
        "enum": ["brief", "standard", "detailed"],
        "default": "standard",
        "description": "Level of detail in the description."
      }
    },
    "required": ["image_url"]
  }
}
```

#### 4.3.3 Output Schema

```json
{
  "type": "object",
  "properties": {
    "description": {
      "type": "string",
      "description": "Natural language description of the figure content"
    },
    "figure_type": {
      "type": "string",
      "enum": ["architecture_diagram", "flowchart", "bar_chart", "line_chart",
               "scatter_plot", "heatmap", "table", "photograph", "illustration",
               "box_plot", "forest_plot", "kaplan_meier", "roc_curve", "other"],
      "description": "Detected type of the figure"
    },
    "key_elements": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Key visual elements identified (e.g., ['3 agent boxes', 'RAG pipeline', 'database icon'])"
    },
    "text_in_figure": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Text/labels extracted from within the figure image"
    },
    "answer": {
      "type": ["string", "null"],
      "description": "Answer to the user's specific question, if provided"
    },
    "confidence": {
      "type": "number",
      "minimum": 0,
      "maximum": 1,
      "description": "Confidence score for the description"
    }
  },
  "required": ["description", "figure_type", "key_elements"]
}
```

#### 4.3.4 Implementation Notes

- 需要 MCP Server 內部或外部呼叫 Vision-capable LLM（如 GPT-4o, Claude 3.5 Sonnet）
- 圖片透過 URL 傳遞，不需先下載至本機
- 應設定合理的 token/cost 上限
- `article_context` 和 `caption` 大幅提升準確度，應鼓勵使用

#### 4.3.5 Typical Usage Flow

```
1. figures = get_article_figures(pmid="40384072")
2. for fig in figures:
     desc = describe_figure(
       image_url=fig.image_url,
       caption=fig.caption_text,
       article_context=article.title
     )
     // desc.description → "This architecture diagram shows a multi-agent system with three specialized agents..."
```

---

### 4.4 Tool: `extract_figure_data`

> **優先序**：P3

#### 4.4.1 Description

從圖表圖片（bar chart, line chart, scatter plot）中提取結構化數值資料。

#### 4.4.2 Input Schema

```json
{
  "name": "extract_figure_data",
  "description": "Extract structured numerical data from chart/graph images. Converts visual data representations back into tabular form.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "image_url": {
        "type": "string",
        "description": "Direct URL to the chart image."
      },
      "chart_type": {
        "type": "string",
        "enum": ["bar", "line", "scatter", "box_plot", "forest_plot", "kaplan_meier", "auto"],
        "default": "auto",
        "description": "Type of chart. 'auto' for automatic detection."
      },
      "caption": {
        "type": "string",
        "description": "Figure caption for context."
      }
    },
    "required": ["image_url"]
  }
}
```

#### 4.4.3 Output Schema

```json
{
  "type": "object",
  "properties": {
    "detected_chart_type": { "type": "string" },
    "title": { "type": ["string", "null"] },
    "x_axis": {
      "type": "object",
      "properties": {
        "label": { "type": "string" },
        "values": { "type": "array", "items": {} }
      }
    },
    "y_axis": {
      "type": "object",
      "properties": {
        "label": { "type": "string" },
        "unit": { "type": ["string", "null"] }
      }
    },
    "series": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": { "type": "string" },
          "values": { "type": "array", "items": { "type": "number" } },
          "error_bars": { "type": ["array", "null"] }
        }
      }
    },
    "data_table_markdown": {
      "type": "string",
      "description": "Extracted data formatted as a markdown table"
    },
    "confidence": { "type": "number" },
    "notes": {
      "type": "array",
      "items": { "type": "string" },
      "description": "Extraction caveats or low-confidence areas"
    }
  }
}
```

---

### 4.5 Tool: `compare_figures`

> **優先序**：P3

#### 4.5.1 Description

比較多篇文章的圖片，產生結構化比較分析。適用於系統性文獻回顧。

#### 4.5.2 Input Schema

```json
{
  "name": "compare_figures",
  "description": "Compare figures across multiple articles. Useful for systematic reviews to compare architectures, results, or workflows.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "figures": {
        "type": "array",
        "minItems": 2,
        "maxItems": 6,
        "items": {
          "type": "object",
          "properties": {
            "image_url": { "type": "string" },
            "label": { "type": "string", "description": "Display label, e.g., 'Study A - Fig 1'" },
            "caption": { "type": "string" },
            "article_title": { "type": "string" }
          },
          "required": ["image_url", "label"]
        }
      },
      "comparison_aspect": {
        "type": "string",
        "enum": ["architecture", "results", "workflow", "methodology", "general"],
        "default": "general",
        "description": "What aspect to focus the comparison on."
      },
      "question": {
        "type": "string",
        "description": "Specific comparison question."
      }
    },
    "required": ["figures"]
  }
}
```

#### 4.5.3 Output Schema

```json
{
  "type": "object",
  "properties": {
    "summary": { "type": "string" },
    "comparison_table_markdown": { "type": "string" },
    "similarities": { "type": "array", "items": { "type": "string" } },
    "differences": { "type": "array", "items": { "type": "string" } },
    "individual_descriptions": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "label": { "type": "string" },
          "description": { "type": "string" }
        }
      }
    }
  }
}
```

---

## 5. Implementation Architecture

### 5.1 System Diagram

```
┌──────────────────────────────────────────────────────────────────┐
│                     PubMed Search MCP Server                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐   ┌─────────────────┐   ┌───────────────┐  │
│  │ get_article_     │   │ describe_        │   │ extract_      │  │
│  │ figures (P0)     │   │ figure (P2)      │   │ figure_data   │  │
│  └───────┬─────────┘   └───────┬─────────┘   │ (P3)          │  │
│          │                     │              └───────┬───────┘  │
│          │                     │                      │          │
│  ┌───────▼─────────────────────▼──────────────────────▼───────┐  │
│  │                   Figure Parser Module                      │  │
│  │  ┌──────────┐  ┌──────────────┐  ┌───────────────────────┐ │  │
│  │  │ JATS XML │  │ Image URL    │  │ Vision LLM            │ │  │
│  │  │ Parser   │  │ Resolver     │  │ Adapter (optional)    │ │  │
│  │  └────┬─────┘  └──────┬───────┘  └───────────┬───────────┘ │  │
│  └───────┼───────────────┼───────────────────────┼────────────┘  │
│          │               │                       │               │
├──────────┼───────────────┼───────────────────────┼───────────────┤
│          ▼               ▼                       ▼               │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │                    External APIs                          │    │
│  │                                                          │    │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │    │
│  │  │ PMC efetch  │  │ Europe PMC   │  │ PMC BioC       │  │    │
│  │  │ JATS XML    │  │ fullTextXML  │  │ JSON           │  │    │
│  │  └─────────────┘  └──────────────┘  └────────────────┘  │    │
│  │                                                          │    │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │    │
│  │  │ PMC CDN     │  │ PMC OA       │  │ NCBI ID        │  │    │
│  │  │ (images)    │  │ Web Service  │  │ Converter      │  │    │
│  │  └─────────────┘  └──────────────┘  └────────────────┘  │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

### 5.2 Core Module: Figure Parser

```python
# Pseudocode for the core parsing module

class FigureParser:
    """Parse figures from JATS XML (PMC or Europe PMC)."""

    def parse_jats_xml(self, xml_content: str) -> list[Figure]:
        """Extract <fig> elements from JATS XML."""
        tree = etree.fromstring(xml_content)
        figures = []

        for fig_elem in tree.iter('fig'):
            fig = Figure(
                figure_id=fig_elem.get('id', ''),
                label=self._get_text(fig_elem, 'label'),
                caption_title=self._get_text(fig_elem, 'caption/title'),
                caption_text=self._get_text(fig_elem, 'caption/p'),
                graphic_href=self._get_graphic_href(fig_elem),
            )
            figures.append(fig)

        return figures

    def _get_graphic_href(self, fig_elem) -> str:
        """Extract xlink:href from <graphic> element."""
        graphic = fig_elem.find(
            'graphic',
            namespaces={'xlink': 'http://www.w3.org/1999/xlink'}
        )
        if graphic is not None:
            return graphic.get(
                '{http://www.w3.org/1999/xlink}href', ''
            )
        return ''
```

### 5.3 Core Module: Image URL Resolver

```python
class ImageURLResolver:
    """Resolve graphic_href to actual image URLs."""

    async def resolve(self, pmcid: str, graphic_href: str) -> ImageURLs:
        """
        Multi-strategy URL resolution:
        1. Try PMC CDN pattern (fastest)
        2. Try article HTML page scraping (reliable)
        3. Try PMC OA package metadata (most complete)
        """

        # Strategy 1: PMC CDN direct pattern
        url = await self._try_pmc_cdn(pmcid, graphic_href)
        if url:
            return ImageURLs(standard=url)

        # Strategy 2: Parse article HTML for <img> tags
        url = await self._try_html_scraping(pmcid, graphic_href)
        if url:
            return ImageURLs(standard=url)

        # Strategy 3: PMC OA package
        url = await self._try_oa_package(pmcid, graphic_href)
        if url:
            return ImageURLs(standard=url)

        return ImageURLs(standard=None)

    async def _try_pmc_cdn(self, pmcid: str, graphic_href: str) -> str | None:
        """
        PMC CDN URL requires blob hashes. 
        Fetch from PMC article page meta tags or OA manifest.
        """
        # Fetch article page headers/meta to discover CDN base
        # Pattern: https://cdn.ncbi.nlm.nih.gov/pmc/blobs/{h1}/{pmcid_num}/{h2}/{href}.gif
        ...

    async def _try_html_scraping(self, pmcid: str, graphic_href: str) -> str | None:
        """
        Fetch PMC article HTML and extract <img> src matching graphic_href.
        Most reliable but requires an extra HTTP request.
        """
        html = await fetch(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/")
        # Parse <img> tags where src contains graphic_href
        ...
```

### 5.4 Fallback Chain

```
get_article_figures(pmcid="PMC12086443")
│
├─ Try 1: PMC efetch XML
│  GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
│      ?db=pmc&id=12086443&rettype=xml
│  ├─ Success → parse JATS XML → resolve image URLs → return
│  └─ Fail (HTTP error / empty) → Try 2
│
├─ Try 2: Europe PMC fullTextXML
│  GET https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12086443/fullTextXML
│  ├─ Success → parse JATS XML → resolve image URLs → return
│  └─ Fail → Try 3
│
├─ Try 3: BioC JSON
│  GET https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/
│      pmcoa.cgi/BioC_json/PMC12086443/unicode
│  ├─ Success → extract fig_caption passages → return (may lack image URLs)
│  └─ Fail → Error
│
└─ All failed → return error with attempted sources
```

---

## 6. Rate Limiting & Performance

### 6.1 API Rate Limits

| API | Rate Limit | Notes |
|-----|-----------|-------|
| PMC efetch | 3 req/sec (without API key), 10 req/sec (with key) | Use NCBI API key |
| Europe PMC REST | 不明確，建議 ≤ 5 req/sec | 較寬鬆 |
| BioC API | 不明確，建議 ≤ 3 req/sec | — |
| PMC HTML (scraping) | 盡量避免，≤ 1 req/sec | 不是正式 API |

### 6.2 Caching Strategy

```python
# 快取層級：
# L1: Session cache (同一 session 內的重複請求)
# L2: Disk cache (跨 session，TTL = 24h)

CACHE_CONFIG = {
    "figure_metadata": {
        "ttl": 86400,       # 24 hours
        "key": "figures:{pmcid}",
        "scope": "disk"
    },
    "resolved_image_urls": {
        "ttl": 86400,       # 24 hours (CDN URLs 穩定)
        "key": "imgurl:{pmcid}:{graphic_href}",
        "scope": "disk"
    },
    "vision_descriptions": {
        "ttl": 604800,      # 7 days (Vision analysis 昂貴)
        "key": "vision:{image_url_hash}:{detail_level}",
        "scope": "disk"
    }
}
```

### 6.3 Performance Targets

| Operation | Target Latency | Notes |
|-----------|----------------|-------|
| `get_article_figures` (cached) | < 100ms | From disk cache |
| `get_article_figures` (uncached) | < 3s | efetch + URL resolution |
| `describe_figure` | < 10s | Depends on Vision LLM |
| `extract_figure_data` | < 15s | Depends on Vision LLM + chart parsing |
| `compare_figures` (2 figs) | < 20s | 2x Vision LLM calls |

---

## 7. Integration with Existing Tools

### 7.1 Session Management

`get_article_figures` 的結果應自動存入 session cache，使得：

```python
# 搜尋後取得 figures
figures = get_article_figures(pmid="40384072")

# 後續在同一 session 中可從 cache 取得
cached = get_cached_article(pmid="40384072")
# cached 應包含 figures 欄位
```

### 7.2 MedPaper Integration

在 MedPaper Assistant MCP 中，figure 工具可用於：

```
save_reference_mcp(pmid) 
  → 自動呼叫 get_article_figures 
  → Figure metadata 存入 reference 記錄
  → 寫作時可引用 figure URL

draft_section(section="methods") 
  → 引用相關文獻的架構圖作為比較依據
```

### 7.3 Citation Tree Enhancement

`build_citation_tree` 可增加 figure 預覽：

```json
{
  "pmid": "40384072",
  "title": "Multi-Agent Approach for...",
  "figures_preview": [
    { "label": "Figure 1", "caption_title": "Architecture diagram", "image_url": "..." }
  ],
  "citing_articles": [...]
}
```

---

## 8. Testing Strategy

### 8.1 Test Cases

| Test ID | Description | Input | Expected |
|---------|-------------|-------|----------|
| T01 | Open Access article with figures | `pmcid="PMC12086443"` | 4 figures with URLs |
| T02 | Article with no figures | `pmcid="PMC..."` (text-only) | `total_figures: 0, figures: []` |
| T03 | Article not in PMC | `pmid="99999999"` | `error: "no_pmc"` |
| T04 | Non-OA article | `pmcid="PMC..."` | `is_open_access: false` |
| T05 | Article with subfigures (3A, 3B) | `include_subfigures=true` | Subfigures parsed separately |
| T06 | PMID → PMCID resolution | `pmid="40384072"` | Auto-resolves to PMC12086443 |
| T07 | efetch fails, Europe PMC fallback | Mock efetch failure | Source = "europepmc" |
| T08 | All sources fail | Mock all failures | Error with attempted sources |
| T09 | Rate limiting | 20 concurrent requests | Proper queuing, no 429 errors |
| T10 | `get_fulltext` with `include_figures=true` | Standard OA article | Markdown includes figure section |

### 8.2 Test Articles

| PMCID | 特色 | 用途 |
|-------|------|------|
| PMC12086443 | 4 figures, GIF format | 基本功能測試 |
| PMC7096777 | 多 subfigures | subfigure 解析 |
| PMC11500123 | 含 supplementary figures | supplementary 測試 |
| PMC9999999 | 不存在 | 錯誤處理測試 |

---

## 9. Rollout Plan

### Phase 1: Core Figure Extraction (P0)

- [ ] 實作 `FigureParser` (JATS XML → Figure metadata)
- [ ] 實作 `ImageURLResolver` (graphic_href → CDN URL)
- [ ] 實作 `get_article_figures` tool
- [ ] 加入 session cache 支援
- [ ] 單元測試 + 整合測試
- [ ] 文件更新

### Phase 2: Fulltext Enhancement (P1)

- [ ] `get_fulltext` 新增 `include_figures` 參數
- [ ] Markdown 格式化 figure section
- [ ] 向下相容測試

### Phase 3: Vision Analysis (P2)

- [ ] 選擇 Vision LLM provider（GPT-4o / Claude 3.5 Sonnet）
- [ ] 實作 Vision LLM adapter
- [ ] 實作 `describe_figure` tool
- [ ] Cost monitoring 機制
- [ ] 視覺描述 cache

### Phase 4: Advanced Tools (P3)

- [ ] 實作 `extract_figure_data`
- [ ] 實作 `compare_figures`
- [ ] 圖表類型自動偵測
- [ ] 與 MedPaper Assistant 整合

---

## 10. Open Questions

| # | 問題 | Impact | 建議 |
|---|------|--------|------|
| Q1 | Vision LLM 的 cost 如何計費？由 MCP Server 承擔或 pass-through？ | P2 | 建議 pass-through，每次呼叫顯示 estimated cost |
| Q2 | 圖片是否需要 base64 encode 回傳給 client？ | P0 | 建議只回傳 URL，client 自行決定是否下載 |
| Q3 | 非 OA 文章是否嘗試取得 thumbnail？ | P0 | PMC 有些非 OA 文章仍提供 figure preview，可考慮 |
| Q4 | 是否支援 GIF 動畫圖（偶爾會有）？ | P3 | 低優先，先忽略 |
| Q5 | `compare_figures` 最多支援幾張圖比較？ | P3 | 建議 6 張上限（Vision token cost） |

---

## Appendix A: PMC JATS XML Figure Tag Reference

```xml
<!-- 基本 figure -->
<fig id="fig1">
  <label>Figure 1</label>
  <caption>
    <title>System Architecture</title>
    <p>Overview of the proposed multi-agent system...</p>
  </caption>
  <graphic xlink:href="article-fig1" mimetype="image" mime-subtype="gif"/>
</fig>

<!-- 帶有 subfigures 的 figure group -->
<fig-group id="fig3">
  <label>Figure 3</label>
  <caption><p>Output examples.</p></caption>
  <fig id="fig3a">
    <label>(A)</label>
    <caption><p>Antibiotic recommendations</p></caption>
    <graphic xlink:href="article-fig3a"/>
  </fig>
  <fig id="fig3b">
    <label>(B)</label>
    <caption><p>Guideline compliance check</p></caption>
    <graphic xlink:href="article-fig3b"/>
  </fig>
</fig-group>

<!-- Supplementary figure -->
<supplementary-material id="sup1">
  <label>Supplementary Figure S1</label>
  <caption><p>Additional analysis results.</p></caption>
  <media xlink:href="article-supfig1.pdf" mimetype="application" mime-subtype="pdf"/>
</supplementary-material>
```

## Appendix B: Image URL Resolution Examples

```
# PMC efetch 取得的 graphic_href:
xlink:href = "hir-2025-31-2-209f1"

# 對應的 CDN URL (需要 hash lookup):
https://cdn.ncbi.nlm.nih.gov/pmc/blobs/671c/12086443/f00885b1d671/hir-2025-31-2-209f1.gif

# Europe PMC 替代:
https://europepmc.org/articles/PMC12086443/bin/hir-2025-31-2-209f1.gif

# PMC 文章頁面直連:
https://pmc.ncbi.nlm.nih.gov/articles/PMC12086443/figure/f1-hir-2025-31-2-209/
```

---

## Appendix C: Review Notes (2026-02-25)

> 以下為針對原始 v1.0.0 Draft 的審查結果，列出問題、影響、與具體改善建議。

### C.1 🔴 Critical Issues（必須修正才能實作）

#### C.1.1 安全漏洞：SSRF 風險

**問題**：`describe_figure` 和 `extract_figure_data` 接受任意 `image_url` 參數，攻擊者可利用此輸入讓 MCP Server 對內部網路發起請求 (Server-Side Request Forgery)。

**影響**：OWASP Top 10 — A10:2021 SSRF

**建議**：新增 URL 驗證白名單，僅允許已知安全的 CDN domain：

```python
# infrastructure/sources/figure_client.py
ALLOWED_IMAGE_DOMAINS = frozenset({
    "cdn.ncbi.nlm.nih.gov",
    "europepmc.org",
    "www.ncbi.nlm.nih.gov",
    "pmc.ncbi.nlm.nih.gov",
    "core.ac.uk",
})

def validate_image_url(url: str) -> None:
    """Validate image URL against allowed domains."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Invalid URL scheme: {parsed.scheme}")
    if parsed.hostname not in ALLOWED_IMAGE_DOMAINS:
        raise ValueError(f"Domain not allowed: {parsed.hostname}")
```

#### C.1.2 DDD 架構未對齊

**問題**：Spec 中的 `FigureParser` 和 `ImageURLResolver` 是 flat classes，未對應到專案的 DDD 四層架構。

**影響**：實作時容易放錯位置，違反 `ddd-layer-imports` pre-commit hook。

**建議**：明確映射至 DDD 各層：

```
src/pubmed_search/
├── domain/entities/
│   └── figure.py              # Figure dataclass (P0)
├── application/
│   └── figure/
│       └── figure_service.py   # 組合 parser + resolver 的用例
├── infrastructure/sources/
│   └── figure_client.py        # FigureParser + ImageURLResolver (含 HTTP)
└── presentation/mcp_server/tools/
    └── figure_tools.py         # get_article_figures, describe_figure MCP 工具
```

#### C.1.3 未複用現有 `ImageResult` Entity

**問題**：Spec 定義了全新的 Figure output schema，但專案已有 `domain/entities/image.py` 中的 `ImageResult` dataclass，欄位高度重疊（`image_url`, `thumbnail_url`, `caption`, `label`, `pmid`, `pmcid`）。

**建議**：擴展現有 `ImageResult` 或建立繼承關係：

```python
# domain/entities/figure.py
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass
class ArticleFigure:
    """Figure metadata extracted from article JATS XML."""
    figure_id: str
    label: str
    caption_title: str | None = None
    caption_text: str = ""
    image_url: str | None = None
    image_url_large: str | None = None
    graphic_href: str = ""
    subfigures: list[ArticleFigure] | None = None
    mentioned_in_sections: list[str] = field(default_factory=list)

@dataclass
class ArticleFiguresResult:
    """Result of figure extraction from an article."""
    pmid: str | None = None
    pmcid: str = ""
    article_title: str = ""
    total_figures: int = 0
    figures: list[ArticleFigure] = field(default_factory=list)
    source: str = ""  # pmc_efetch, europepmc, bioc
    is_open_access: bool = True
```

### C.2 🟡 Important Issues（建議修正）

#### C.2.1 未繼承 `BaseAPIClient`

**問題**：Spec 的 pseudocode 直接使用 `httpx` 發請求，但專案所有 API 客戶端都繼承 `BaseAPIClient`，以獲得自動 retry、rate limiting、circuit breaker。

**建議**：

```python
# infrastructure/sources/figure_client.py
from pubmed_search.infrastructure.sources.base_client import BaseAPIClient

class FigureClient(BaseAPIClient):
    _service_name = "PMC_Figures"

    def __init__(self) -> None:
        super().__init__(
            base_url="https://eutils.ncbi.nlm.nih.gov",
            min_interval=0.34,  # 3 req/sec without API key
        )

    async def get_figures(self, pmcid: str) -> ArticleFiguresResult:
        """Multi-source figure extraction with automatic fallback."""
        ...
```

#### C.2.2 Pseudocode 全部是同步，專案是 async-first

**問題**：Section 5.2-5.3 的 pseudocode 混用 sync/async。`parse_jats_xml` 雖然不需 async，但 `ImageURLResolver.resolve` 需要。整體風格不一致。

**建議**：所有涉及 I/O 的方法統一使用 `async def`，並在 pseudocode 中標明。XML 解析等純 CPU 操作保持 sync。

#### C.2.3 現有 Europe PMC JATS XML 解析未被複用

**問題**：`infrastructure/sources/europe_pmc.py` 已有 `parse_fulltext_xml()` 方法解析 JATS XML（擷取 title, abstract, sections, references），但**故意跳過 `<fig>` 元素**。Spec 未提及應在此處擴展。

**建議**：P0 實作時，優先在既有的 `parse_fulltext_xml()` 中新增 `<fig>` 解析邏輯，而非重寫整套 parser：

```python
# 在 europe_pmc.py 的 parse_fulltext_xml 中新增：
def _parse_figures(self, root: Element) -> list[dict]:
    """Extract <fig> elements from JATS XML body."""
    figures = []
    for fig_elem in root.iter("fig"):
        figures.append({
            "figure_id": fig_elem.get("id", ""),
            "label": self._get_text(fig_elem, "label"),
            "caption_title": self._get_text(fig_elem, "caption/title"),
            "caption_text": self._get_text(fig_elem, "caption/p"),
            "graphic_href": self._get_graphic_href(fig_elem),
        })
    return figures
```

#### C.2.4 `describe_figure` 與現有 `analyze_figure_for_search` 功能重疊

**問題**：專案已有 `analyze_figure_for_search` tool（`presentation/mcp_server/tools/vision_search.py`），它接受圖片 URL 並透過 MCP `ImageContent` 回傳給 Agent 的 Vision 能力分析。Spec 的 `describe_figure` (P2) 功能高度重疊。

**建議**：
- **方案 A**（推薦）：擴展現有 `analyze_figure_for_search` 增加 `mode="describe"` 參數，而非新增獨立 tool
- **方案 B**：若堅持新增，明確區分定位：
  - `analyze_figure_for_search` → 「從圖片產生搜尋查詢」
  - `describe_figure` → 「產生圖片的結構化描述」

#### C.2.5 Caching 方案與專案現況不符

**問題**：Section 6.2 提到 L2 Disk Cache (`TTL=24h`)，但專案目前**沒有 disk cache 基礎設施**。既有的 cache 全部是 session-level in-memory。

**建議**：
- P0 階段先只用 session cache（與現有架構一致）
- 如需 disk cache，應在 `shared/` 層新增通用 cache 模組，而非 figure-specific
- 修正 Section 6.2 為：

```python
CACHE_STRATEGY = {
    "phase_1": "session cache only (consistent with existing tools)",
    "phase_2": "evaluate disk cache need based on usage patterns",
}
```

#### C.2.6 PMC CDN URL 解析缺乏可行方案

**問題**：Section 3.3 的 CDN URL 格式 `https://cdn.ncbi.nlm.nih.gov/pmc/blobs/{blob_hash}/{pmcid_numeric}/{file_hash}/{filename}.{ext}` 需要兩個 hash 值，但 Spec 未說明如何取得這些 hash。Section 5.3 的 `_try_pmc_cdn` 方法內容為 `...`。

**影響**：這是 P0 的核心功能，不能留空。

**建議**：明確採用可行的 URL 解析策略優先序：

```
策略 1（推薦）: Europe PMC CDN — URL 格式確定性高
  https://europepmc.org/articles/{PMCID}/bin/{graphic_href}.jpg
  （需實測 .gif / .jpg / .png 的副檔名規則）

策略 2: PMC HTML Page Scraping — 可靠但需額外 HTTP 請求
  GET https://pmc.ncbi.nlm.nih.gov/articles/{PMCID}/
  解析 HTML 中 <img> src 屬性取得完整 CDN URL

策略 3: PMC OA Web Service — 提供完整 tar.gz 包含圖片清單
  GET https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi?id={PMCID}
  解析 XML 取得圖片檔案列表和 FTP/HTTPS 下載路徑
```

#### C.2.7 MCP `ImageContent` 回傳格式未提及

**問題**：MCP 協定原生支援 `ImageContent` 類型回傳，可直接在支援的 client 中顯示圖片。Spec 只回傳 URL 字串，未利用此能力。

**建議**：在 `get_article_figures` 的 tool 實作中，考慮支援 MCP `ImageContent`：

```python
# presentation/mcp_server/tools/figure_tools.py
from mcp.types import ImageContent, TextContent

async def get_article_figures(pmcid: str, return_thumbnails: bool = False) -> list:
    results = [TextContent(type="text", text=json.dumps(figures_metadata))]
    if return_thumbnails:
        for fig in figures:
            results.append(ImageContent(
                type="image",
                data=base64_thumbnail,
                mimeType="image/gif",
            ))
    return results
```

### C.3 🟢 Minor Issues（品質改善）

#### C.3.1 測試文章 ID 需驗證

**問題**：Section 8.2 的測試文章 PMCID（`PMC11500123`, `PMC9999999`）可能不存在或特性不符描述。

**建議**：實作前需實際查詢確認，替換為已驗證的 real articles。建議加入 PMCID 驗證腳本。

#### C.3.2 `get_fulltext` include_figures 的放置位置

**問題**：Section 4.2.3 將 figures 放在全文末尾的獨立 section。但更理想的做法是在文中引用 figure 的段落**就地**插入 figure metadata。

**建議**：提供兩種模式：
- `include_figures="append"` — 附加在末尾（向下相容，簡單）
- `include_figures="inline"` — 在引用位置就地插入（更好的閱讀體驗）

#### C.3.3 工具數量同步

**問題**：新增 4 個 tools（`get_article_figures`, `describe_figure`, `extract_figure_data`, `compare_figures`）後，需同步更新多份文件。

**建議**：實作時必須遵循專案的 tool-sync 流程：
1. 更新 `tool_registry.py` 的 `TOOL_CATEGORIES`
2. 執行 `uv run python scripts/count_mcp_tools.py --update-docs`
3. 確認 `copilot-instructions.md`、`instructions.py` 等 6 個文件自動同步

#### C.3.4 `FulltextResult.has_figures` 欄位已存在但未使用

**問題**：`infrastructure/sources/fulltext_download.py` 的 `FulltextResult` 已定義 `has_figures: bool = False`，但從未被設定。

**建議**：P0 實作時一併 populate 此欄位，在 fulltext 解析中設定 `has_figures = len(figures) > 0`。

#### C.3.5 Vision LLM 配置缺失

**問題**：`describe_figure` (P2) 和 `extract_figure_data` (P3) 依賴 Vision LLM，但 Spec 未說明：
- Vision LLM 的配置方式（環境變數? config file?）
- 未配置時的 graceful degradation
- 支援哪些 provider

**建議**：

```python
# 建議配置格式（透過環境變數）
VISION_LLM_PROVIDER=openai        # openai | anthropic | none
VISION_LLM_MODEL=gpt-4o           # 具體模型
VISION_LLM_API_KEY=sk-xxx          # API key
VISION_LLM_MAX_TOKENS=1000         # 每次呼叫上限
VISION_LLM_MONTHLY_BUDGET=50.00    # 月費上限 (USD)

# 未配置時的行為：
# - describe_figure → 回傳 {error: "vision_not_configured", ...}
# - compare_figures → 僅回傳 caption-based 文字比較
```

### C.4 建議實作優先序調整

原始 Rollout Plan → 建議調整：

| 階段 | 原始 | 建議調整 |
|------|------|----------|
| P0 | `get_article_figures` | ✅ 維持，但先整合到既有 `europe_pmc.py` 的 XML parser |
| P1 | `get_fulltext` + `include_figures` | ✅ 維持，可與 P0 同時實作 |
| P2 | `describe_figure` (新 tool) | ⚠️ 改為擴展 `analyze_figure_for_search`，避免工具膨脹 |
| P3 | `extract_figure_data` + `compare_figures` | ⚠️ 保留設計但延後，先驗證 P0-P1 的使用模式 |

### C.5 改善摘要

| 類別 | 數量 | 重點 |
|------|------|------|
| 🔴 Critical | 3 | SSRF 防護、DDD 對齊、Entity 複用 |
| 🟡 Important | 7 | BaseAPIClient、async、XML parser 複用、工具重疊、cache、URL 解析、MCP ImageContent |
| 🟢 Minor | 5 | 測試 ID、inline figures、tool-sync、has_figures 欄位、Vision LLM 配置 |
