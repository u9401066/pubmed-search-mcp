# PubMed Search MCP Optimization Follow-up

日期: 2026-06-05

## 已落地優化

1. `ResultAggregator.rank`
   - BM25 可用時，不再先跑 heuristic relevance 再覆寫。
   - 仍保留 quality、recency、impact、source trust、entity match 等 dimension scoring。

2. `CacheStore.warmup` / `JsonFileCacheBackend`
   - 新增 backend 批次寫入 API。
   - JSON backend 在同一把 lock 內更新多筆 entry，最後只 `_save()` 一次。
   - `ArticleCache.put_many()` 可直接受益，不需改 application API。

3. `PipelineExecutor` article type normalization
   - canonical article type map 與 alias map 改為 lazy cached read-only mapping。
   - 保留既有 alias、fuzzy matching、diagnostics 語意。

4. `UnifiedArticle.merge_from` / `to_dict`
   - keywords、MeSH terms、sources 改用 set-assisted dedup，保留原始順序與 exact matching。
   - `to_dict()` 只讀一次 `best_oa_link`。

5. `unified_formatting._format_as_json`
   - 極小 `max_response_chars` 時提前走既有 truncated payload 路徑。
   - 避免 response 明顯會被截斷時仍對所有 article 做完整 `to_dict()`。

## 新增防回歸測試

- `tests/test_performance_optimizations.py`
  - BM25 ranking 不呼叫 heuristic relevance。
  - ArticleCache JSON `put_many()` 只觸發一次 physical save。
  - Pipeline article type alias map cached 且 read-only。
  - `merge_from()` order-preserving dedup 不走 repeated list membership。
  - `to_dict()` 只讀一次 `best_oa_link`。
  - tiny capped structured output 不序列化所有 article。

## 驗證

使用 standalone `uv`:

```powershell
C:\Users\Ericlab\.local\bin\uv.exe run ruff check src/pubmed_search/application/search/result_aggregator.py src/pubmed_search/shared/cache_substrate.py src/pubmed_search/application/pipeline/executor.py src/pubmed_search/domain/entities/article.py src/pubmed_search/presentation/mcp_server/tools/unified_formatting.py tests/test_performance_optimizations.py
C:\Users\Ericlab\.local\bin\uv.exe run ruff format --check src/pubmed_search/application/search/result_aggregator.py src/pubmed_search/shared/cache_substrate.py src/pubmed_search/application/pipeline/executor.py src/pubmed_search/domain/entities/article.py src/pubmed_search/presentation/mcp_server/tools/unified_formatting.py tests/test_performance_optimizations.py
C:\Users\Ericlab\.local\bin\uv.exe run mypy src/pubmed_search/application/search/result_aggregator.py src/pubmed_search/shared/cache_substrate.py src/pubmed_search/application/pipeline/executor.py src/pubmed_search/domain/entities/article.py src/pubmed_search/presentation/mcp_server/tools/unified_formatting.py tests/test_performance_optimizations.py
C:\Users\Ericlab\.local\bin\uv.exe run pytest tests/test_performance_optimizations.py tests/test_cache_substrate.py tests/test_result_aggregator.py tests/test_session.py tests/test_pipeline.py tests/test_unified_article.py tests/test_article_extended.py tests/test_unified_tools.py -q -o addopts="" --maxfail=1
C:\Users\Ericlab\.local\bin\uv.exe lock --check
C:\Users\Ericlab\.local\bin\uv.exe run python scripts/perf/complexity_scan.py --target rank_articles --target session_cache_lookup --target article_to_dict --json-output scripts/_tmp/complexity/post_optimization_hotspots.json --markdown-output scripts/_tmp/complexity/post_optimization_hotspots.md
```

結果:

- Ruff check: pass
- Ruff format check: pass
- Mypy focused check: pass
- Focused pytest: 443 passed
- `uv lock --check`: pass
- Post-optimization scanner: selected hot paths remained linear

## 未執行項目

- 未跑全量 `uv run pytest -q`，因為 repo 預設 xdist 且本輪明確要求小心 OOM。
- 本輪用單程序聚焦測試覆蓋修改周邊功能面。
