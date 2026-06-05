# PubMed Search MCP Repo Complexity Analysis

日期：2026-06-05

## 摘要

這次分析使用三層方法：零新依賴的 empirical Big-O scanner、`ruff` 結構複雜度掃描、以及三個只讀 subagent 分區審查。整體結論是：目前最值得優先處理的不是單一演算法災難，而是工具層與 presentation 層責任過大、序列化前才裁切 payload、以及少數 list membership / repeated tokenization 常數成本在大 N 時被放大。

核心資料處理路徑大多接近線性。`ResultAggregator.aggregate`、`ResultAggregator.rank`、`UnifiedArticle.to_dict`、RIS export、session in-memory lookup 在 synthetic N-scaling 下都呈現穩定線性訊號。真正需要警戒的是 opt-in MMR、多來源 deep-search fanout、fulltext/presentation fallback 重複建 payload、session JSON backend batch write，以及幾個超大 register/tool 函式。

## 方法與限制

- Scanner：`scripts/perf/complexity_scan.py`
- 測試：`tests/test_complexity_scan.py`
- 原始 JSON：`scripts/_tmp/complexity/full_scan.json`
- 靜態掃描：`scripts/_tmp/complexity/ruff_complexity.txt`
- 命令皆使用 standalone `uv 0.11.19`，並避免 xdist：`-o addopts=""`

Empirical Big-O 是經驗估計，不是數學證明。低於數毫秒的函式容易受 lazy import、GC、Windows timer、async event loop、設定讀取干擾。報告中只有 `R^2` 高的項目才作為主要結論；低信心項目只作為「需要專門 benchmark」訊號。

## 工具鏈狀態

- `uv`：已用 `C:\Users\Ericlab\.local\bin\uv.exe` 升級到 `0.11.19`
- `ruff`：`0.14.14`
- `pytest`：`9.0.3`
- `mypy`：`2.1.0`
- `uv lock --check` 通過
- `tests/test_complexity_scan.py -q -o addopts=""`：4 passed
- `tests/test_profiling.py -q`：20 passed

注意：`uv self update` 不能更新 PATH 上的 Python Scripts 版 uv；目前可靠的是 standalone uv 路徑。

## Empirical N-Scaling 結果

| Target | 路徑 | 結論 | R2 | 樣本摘要 |
|---|---|---:|---:|---|
| `aggregate_deduplicate` | `application/search/result_aggregator.py` | linear | 1.000 | N=20 0.098ms 到 N=800 1.226ms |
| `rank_articles` | `application/search/result_aggregator.py` | linear | 1.000 | N=20 1.317ms 到 N=800 49.170ms |
| `article_to_dict` | `domain/entities/article.py` | linear | 1.000 | N=20 0.065ms 到 N=800 1.248ms |
| `export_ris` | `application/export/formats.py` | linear | 0.997 | N=20 0.087ms 到 N=800 2.220ms |
| `session_cache_lookup` | `application/session/manager.py` | linear | 0.996 | N=20 0.076ms 到 N=800 1.520ms |
| `format_unified_results` | `presentation/mcp_server/tools/unified_formatting.py` | low-confidence | 0.266-0.702 | 計時受 lazy/config/async noise 影響 |
| `pipeline_filter` | `application/pipeline/executor.py` | low-confidence | 0.401-0.718 | 大 N 呈上升，但低 N 噪音大 |

解讀：

- 去重目前證實接近線性，Union-Find 架構方向正確。
- Ranking 在目前 synthetic corpus 與 MMR off 下呈線性；理論上 BM25 + RRF 仍含 `N log N` 排序項，但在 N<=800 時 tokenization/score 常數主導。
- `format_unified_results` 和 `pipeline_filter` 不是沒有問題，而是簡單 wall-clock fitting 不足以定性；要拆成更小 target，例如 OpenURL loop、JSON cap serializer、article type normalization。

## 靜態熱點

`ruff --select C901,PLR0911,PLR0912,PLR0915` 回報 200 個 complexity findings。最大檔案與最大符號高度集中在 presentation/tool registration 與 application service。

最大檔案：

| Lines | File |
|---:|---|
| 1272 | `src/pubmed_search/presentation/mcp_server/tools/europe_pmc.py` |
| 1001 | `src/pubmed_search/presentation/mcp_server/tools/discovery.py` |
| 914 | `src/pubmed_search/application/pipeline/executor.py` |
| 886 | `src/pubmed_search/application/search/result_aggregator.py` |
| 845 | `src/pubmed_search/domain/entities/article.py` |
| 840 | `src/pubmed_search/presentation/mcp_server/tools/unified_formatting.py` |
| 819 | `src/pubmed_search/infrastructure/sources/fulltext_download.py` |
| 785 | `src/pubmed_search/application/reference_verification/service.py` |
| 783 | `src/pubmed_search/application/search/query_analyzer.py` |
| 775 | `src/pubmed_search/application/export/notes.py` |

最大符號：

| Lines | Symbol |
|---:|---|
| 1009 | `register_europe_pmc_tools` |
| 982 | `PipelineExecutor` |
| 859 | `FulltextDownloader` |
| 830 | `register_discovery_tools` |
| 803 | `ReferenceVerificationService` |
| 698 | `QueryAnalyzer` |
| 661 | `ResultAggregator` |
| 614 | `SessionManager` |
| 598 | `UnifiedArticle` |
| 593 | `EuropePMCClient` |

## 主要發現

### 1. Ranking/aggregation

`ResultAggregator.aggregate` 是健康的，實測線性。風險在 `rank` 的重複 tokenization 與 MMR。

- BM25 開啟時，`rank` 先算 `_calculate_dimension_scores()`，其中 relevance 會 regex/tokenize；後面 BM25 又覆寫 relevance，形成無效工作。
- BM25 corpus 與每篇 `bm25_score` 都會 tokenize，同一篇文章可能被處理兩次。
- RRF 每個有效 dimension 各 sort 一次，理論成本 `O(D*N log N)`。
- MMR opt-in 但危險；若 `top_k=N`，可退化到平方到三次方級別。

低風險優化：

- BM25 on 時跳過原始 `_calculate_relevance`，直接注入預算好的 relevance。
- 在一次 rank 呼叫內 cache canonical article key。
- BM25 query terms 預先 tokenize；若可接受，corpus 保存 per-article terms/tf map。
- MMR 強制吃 `max_results/top_k`，並維護 remaining article 的 current max similarity。

### 2. Formatting/serialization

`unified_formatting.py` 是最大「繞路」區之一。靜態掃描中 `_format_unified_results` 是 327 行且 complexity 60，`_format_as_json`、`_serialize_with_response_cap` 也都偏大。

主要問題：

- JSON path 先 materialize 全部 article payload，最後才套 response cap。
- `_serialize_with_response_cap` 先完整 serialize，超限後又多次重新 serialize preview。
- Markdown loop 內做 OpenURL config/link 檢查，會隨文章數放大。
- next tools、provenance、markdown、JSON cap、compact mode 混在同一層。

低風險優化：

- 在 payload build 前決定 compact/cap，不要先建完整 payload。
- 拆成 `NextActionBuilder`、`UnifiedMarkdownRenderer`、`UnifiedStructuredRenderer`、`ResponseCapSerializer`。
- OpenURL config hoist 到 loop 外；固定 badge maps 改 module constants。
- structured output 以 generator/preview builder 先裁 article count，再 serialize。

### 3. Pipeline

Pipeline DAG 本身有 `MAX_PIPELINE_STEPS=20` 限制，所以圖排序不是瓶頸。風險在 executor 類別太大、filter/merge/report 責任混雜。

主要問題：

- `PipelineExecutor` 982 行，包含 validate、DAG、search、PICO、details、merge、filter、ranking。
- `_action_filter` 是線性，但 article type normalization 與診斷組裝可以拆。
- `validator.validate_and_fix` 多 pass，每步重建 earlier IDs。
- report generator 會對 articles/steps 多次掃描。

低風險優化：

- 把 filter predicate builder 抽出，article type alias/valid map 用 module-level cache。
- `validate_and_fix` 用 rolling `earlier_ids`。
- `PipelineExecutor` 拆成 `PipelinePlanner`、`PipelineStepDispatcher`、`PipelineArticleFilters`。
- report 的 `_format_article` 拆 metadata/type/link 小函式。

### 4. Session/cache

Empirical in-memory lookup 是線性的，沒有明顯演算法問題。但 JSON backend 實務上可能很貴。

主要問題：

- `JsonFileCacheBackend.set_entry()` 若每 key 重寫整個 cache，`put_many(W)` 會變成 `O(W*C)` disk serialization。
- `get_session_summary()`、history/PMID 類函式有多次掃描機會。

低風險優化：

- `put_many()` 做 batch write，一次更新多筆後寫一次 JSON。
- `get_session_summary()` 只算一次 cached PMIDs，再切前 20。
- session index 與 session file 寫入時機分離，避免普通 mutation 寫多份狀態。

### 5. Export

RIS export 實測線性且很快；問題主要是函式複雜度與大 payload memory。

主要問題：

- `export_ris`、`export_bibtex`、`export_medline` 都有高 complexity。
- 所有 export 都全量建立字串，memory 為 `O(output_bytes)`。
- BibTeX fallback `_convert_to_latex` 多次 replace，字串長時常數成本高。

低風險優化：

- 用 shared field extraction helpers 減少 RIS/BibTeX/MEDLINE 分支重複。
- 大型 export 可提供 iterator/stream builder。
- BibTeX escape 改 translation table 或單次 regex。

### 6. Fulltext / Europe PMC

`europe_pmc.py` 是全 repo 最大檔案，presentation 層承擔太多 fallback 與 payload 建構。

主要問題：

- `get_fulltext` 先走 `FulltextService`，又在 presentation 內自行跑 downloader fallback。
- structured artifact、markdown artifact、inline response 多路徑重複 render。
- fulltext JSON builder 會一次打包 content、sections、links、figures、provenance。

低風險優化：

- PDF fallback 移回 application fulltext service/policy registry。
- 建立單一 `FulltextPayloadBuilder`，artifact 與 inline response 共用中間模型。
- fulltext inline cap 先裁剪，再建 response。

## 優先處理順序

1. `unified_formatting.py` response cap / structured serialization：最容易降低記憶體峰值，也最貼近 MCP 使用體感。
2. `ResultAggregator.rank` BM25 重複 tokenization / relevance 覆寫：低風險，容易用 benchmark 驗證。
3. `SessionManager` JSON backend batch write：對大量保存/匯出工作流很有價值。
4. `europe_pmc.py` fulltext payload builder：降低 presentation 繞路，改善大文檔處理。
5. `PipelineExecutor` filter/validator/report 拆分：主要改善可維護性與測試隔離。
6. Export shared helpers：降低 complexity findings，但效能不是第一瓶頸。

## 後續 Benchmark 建議

新增更細 target：

- `rank_bm25_tokenization`: BM25 on/off、query terms、abstract tokens。
- `rank_mmr`: N=20/50/100/150/200、top_k=10/50/N。
- `response_cap_json`: article count、payload bytes、max_response_chars。
- `fulltext_payload`: fulltext chars、section count、figure count、artifact enabled。
- `session_json_put_many`: cache size C、write batch W，使用 tmp dir。
- `export_bibtex_escape`: text bytes 與 unicode density。

所有命令都應採用：

```powershell
& 'C:\Users\Ericlab\.local\bin\uv.exe' run pytest tests/test_complexity_scan.py -q -o addopts=""
& 'C:\Users\Ericlab\.local\bin\uv.exe' run python scripts/perf/complexity_scan.py --json-output scripts/_tmp/complexity/full_scan.json
```

避免：

- 不要用 xdist 跑 benchmark。
- 不要一次跑全測試當作 Big-O scan。
- 不要把 `scripts/_tmp/complexity/*.json` 提交。

## 結論

目前 repo 的核心資料演算法並沒有整體性的 `O(N^2)` 崩壞；多數可測核心路徑是線性的。真正拖慢維護與大 payload 行為的是「presentation 層先完整建資料、最後才裁切」、「大型 register/tool 函式把服務、fallback、render 混在一起」、「少數內層 list membership/tokenization 重複」。下一步若要實際優化，我建議先做 `unified_formatting.py` 的 response cap serializer，因為它最能同時降低記憶體峰值、改善 MCP 大回應、也讓後續 benchmark 更乾淨。
