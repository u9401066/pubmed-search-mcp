# Academic retrieval benchmarks 與 PubMed Search MCP 改進紀錄

核對日期：2026-09-09。程式基線：`dbcf0c88c76e6fac30877ff16a9850232e89bd4e`。

後續的引用驗證、文獻去重、全文容錯與快取並行修正，見
[repository 改進與驗證紀錄](REPOSITORY_RELIABILITY_AUDIT.md)。
該輪回歸測試與下列公開 benchmark 結果分開報告；完整 Agent 長跑仍未啟動。

**v0.7.2 整合註記：** 發布版建立在遠端 v0.7.1 的 41-tool 嚴格介面上；下方
`dbcf0c8`、45-tool 工作區及 pilot 數字是同步遠端前的歷史實驗。固定語料 adapter
已適配新版 server-owned container 與 typed search page，產品長跑則需使用重新
prepare 的 manifest。原始 dataset、source baseline 與結果不變；沒有發布版 Agent
得分或整套 MCP 增益的新結論。

PubMed Search MCP 應分別量測「搜尋元件品質」和「Agent 使用工具後的研究成果」。本次完成三輪程式修正，並用公開 BEIR NFCorpus 評估實際 production BM25 函式。獨立測試集 nDCG@10 由 **0.293357 提升至 0.297831**；這不等於 ScholarGym、SciNet 或完整 Agent 的得分提升。

## Benchmark 最新核對

| Benchmark | 核對後版本與範圍 | 對本專案的用途 |
| --- | --- | --- |
| ScholarGym | arXiv 2601.21654 **v3，2026-02-17**；570K 論文、2,536 個標註查詢；分離 planning、invocation、assessment。新版指出查詢規劃與相關性判定都是瓶頸。[論文](https://arxiv.org/abs/2601.21654v3) | 評估相同模型、提示、工具預算下，多輪查詢與選文的貢獻。必須分開 cumulative retrieval recall 和 selection recall。 |
| SciNet（原 SciNetBench） | **v2，2026-05-22；ICML 2026**。最新規模為 **269M 論文、7 領域、8,940 任務**。18M AI 論文是早期版本，不應與新版任務數混用。[論文](https://arxiv.org/abs/2601.03260v2)、[作者程式庫](https://github.com/tsinghua-fib-lab/SciNet)、[ICML 名錄](https://icml.cc/Downloads/2026) | 選 Medicine/Biology 子集，評估 citation edges、引用語境及演化路徑；語義分群或時間排序不能直接當作引用關係。 |
| ResearchArena | 最早預印本為 2024；正式為 **Findings of EMNLP 2025**。12M 全文與 7.9K survey，mind-map 是 bonus task。提供建置環境程式，並不直接重分發所有全文。[ACL](https://aclanthology.org/2025.findings-emnlp.303/) | 分開評估文獻發現、選擇和組織；報告寫得流暢不能取代相關文獻覆蓋率。 |
| LitSearch | **EMNLP 2024**，597 個 ML/NLP 文獻查詢，包含引用衍生與作者撰寫查詢。[ACL](https://aclanthology.org/2024.emnlp-main.840/) | 作為跨域泛化測試；須接官方 corpus，不能只用即時 PubMed 查詢後與其成績比較。 |
| HiSciBench | arXiv **2512.22899，2025**；五層科研能力、六學科、8,735 實例。[論文](https://arxiv.org/abs/2512.22899)、[官方資料與評測](https://huggingface.co/ScienceOne-AI/HiSciBench/blob/main/README.md) | L2/L3 驗證讀文與證據存取，L4 驗證綜述；其餘層級不能直接歸因於搜尋 MCP。 |
| CSMeD | **NeurIPS 2023 Datasets and Benchmarks**，整合九個集合、325 個 medicine/computer-science systematic reviews，另有 CSMeD-FT。[論文](https://proceedings.neurips.cc/paper_files/paper/2023/hash/4962a23916103301b27bde29a27642e8-Abstract-Datasets_and_Benchmarks.html) | 更符合高召回初篩：按 review 切分、評估漏篩與達到目標召回率所需閱讀量，避免同一 review 跨 train/test。 |
| EvidenceBench（生醫） | **COLM 2025**。原始集合 426 個實例；EvidenceBench-100k 為 107,461 個實例。候選池是單篇論文的句子，評估假說相關證據／aspects。[作者程式庫](https://github.com/EvidenceBench/EvidenceBench) | 用於全文證據擷取；不能拿來替代文獻層級的初篩召回率。 |

原清單還應補上 **AstaBench**：其 PaperFindingBench 衡量內容與 metadata 約束下的找文，LitQA2-FullText-Search 隔離檢索能力，ScholarQA-CS2 則評估綜述與引用覆蓋。這種拆分比單一「研究品質總分」更適合定位 MCP 問題。[Ai2 官方說明](https://allenai.org/asta/bench)

另一個與 PubMed 更直接相關的補充是 **PaperSearchQA（EACL 2026）**：提供 16M PubMed abstracts、60K 訓練 QA，以及 PaperSearchQA/BioASQ 評測環境。適合測量 search-and-reason，但 QA 正確率仍受 Agent 模型影響，不能直接視為 MCP 檢索 recall。[官方專案](https://jmhb0.github.io/PaperSearchQA/)

## 實際發現與三輪修正

原有 `tests/benchmarks/test_benchmarks.py` 衡量 container、格式化、cache 與 query parsing 的速度，沒有 qrels 驅動的文獻品質指標。新增 `retrieval_metrics.py` 與 `scripts/benchmark_retrieval.py` 後，使用同一份固定 corpus 與 relevance judgments 評估 BM25，輸出逐查詢結果與檔案 SHA-256。

### 第一輪：修正相關性詞彙與 BM25 長度

原本 query tokenization 會把 `[MeSH Terms]`、`[Title/Abstract]` 和 `AND` 等檢索語法當成相關性詞彙，也會忽略 `AI`、`RA`、`MS`、`T2` 等短詞。計算 corpus 平均長度時排除短詞，計算單篇長度時卻計入短詞，造成正規化不一致。

現在 query 移除欄位標籤與布林運算子、去除重複詞；document frequency、文件長度與欄位計分使用相同 tokenizer，保留兩字元詞並排除一組常見英文停用詞。非 BM25 的 overlap fallback 也使用相同詞彙規則。既有 BM25 的 k1、b、title/MeSH 權重沒有依 benchmark 答案調參。

這仍是 lexical reranking。布林排除、片語和欄位資格由檢索後端執行；tokenizer 不是完整 PubMed Boolean evaluator，也沒有解決縮寫歧義、同義詞或所有基因命名變體。

### 第二輪：修正多輪合併的重複票與缺席票

Pipeline RRF 原本對同一清單中的每個 duplicate 都加分，可能使單一來源重複回傳的文章超越多個查詢共同找到的文章。另一個 RRF 實作則會讓不在該 ranking 中的文章仍取得一張「末位票」，且同清單重複 ID 會覆寫最早順位。

現在 pipeline 共用 application ranking 模組：每個清單先按 identity 保留第一筆，重排唯一項目的順位，每篇文獻每個清單只投一票，沒有出現的文獻貢獻為零，輸出亦保持唯一。這消除兩個實作的行為差異；跨獨立清單的支持仍然累加。Identity 仍依既有 canonical key，跨來源識別碼不完整的合併問題不在本次範圍。

### 第三輪：在 pipeline 截斷前恢復查詢相關性

原本 pipeline 最後呼叫 `ResultAggregator.rank()` 沒有傳入 query，relevance 因此退化成中性分數；即使找到符合查詢的文章，也可能在最終 limit 截斷時被排除。

現在從最終輸出節點的 search ancestors 收集成功執行後保存的實際 query，包含 PICO／expand 衍生的查詢，再傳入排序。失敗節點、無關 DAG 分支與 `stop_at` 之後的節點不參與。沒有 search ancestor 的純 details/citation pipeline 保留無查詢排序。

最初的 12 個回歸案例全部可在原版重現失敗；第一輪修復其中 9 個，第二輪再修復 2 個，第三輪修復最後的 query-before-limit 案例。另補充 ancestry、duplicate output、metrics 與 dataset loader 驗證。本次不新增 MCP 工具或變更參數契約。

## 公開資料實測

採用 **BEIR 版 NFCorpus**：3,633 篇 documents、324 個 dev queries、323 個 test queries。這和 NFCorpus 原始 full-text 發行版規模不同。原始標註來自網站引用／連結關係，並非專家逐篇重新判斷，因此測得的是該資料集的 relevance 定義。[BEIR 資料清單](https://github.com/beir-cellar/beir)、[NFCorpus 原始說明與使用條款](https://www.cl.uni-heidelberg.de/statnlpgroup/nfcorpus/)

這項元件實驗對每個查詢的完整 3,633 篇 BEIR title/text 執行 production `bm25_score()`，從完整語料庫統計 DF/平均長度，以 ID 排序打破同分。沒有以 qrels 選候選文獻、沒有依 relevance labels 擴展 query；元件實驗不使用 LLM。Dev 結果先檢視，test 結果在修正決策完成後檢視。下方另有使用本機 Codex 登入的 Agent 試跑，並非官方 leaderboard。

| Split / 指標 | 修改前 | 修改後 | 絕對差 |
| --- | ---: | ---: | ---: |
| dev nDCG@10 | 0.261919 | 0.264292 | +0.002373 |
| dev Recall@100 | 0.197763 | 0.199752 | +0.001989 |
| test nDCG@10 | 0.293357 | 0.297831 | +0.004474 |
| test Precision@10 | 0.206502 | 0.209598 | +0.003096 |
| test Recall@100 | 0.235765 | 0.236265 | +0.000500 |
| test MRR@10 | 0.499296 | 0.506462 | +0.007166 |

test nDCG@10 相對提高約 **1.53%**。以 query 為單位的 paired bootstrap（10,000 次，seed 20260909），差值的 95% percentile interval 為 **[0.001049, 0.008004]**。49 個 query 改善、33 個下降、241 個不變，所以不能宣稱每個搜尋都變好。test Recall@100 interval 為 **[-0.000810, 0.002008]**，仍涵蓋零；召回改善不能作為確定結論。這是單資料集的探索性比較，沒有跨資料集泛化保證。

完整彙總、四項主要指標的逐查詢配對、資料與程式 fingerprints 儲存在 [機器可讀評測紀錄](reports/academic_retrieval_benchmark_2026-09-09.json)。BM25 實測不涵蓋 balanced 多維排序、pipeline RRF 或 Agent 行為；後兩項修正目前的證據是確定性的行為回歸測試。

### 指標定義

- nDCG 使用 **linear relevance gain**（grade 本身），與 trec_eval 的常見設定一致；不要混用 `2^grade - 1` 的結果。
- Recall 的分母是該 query 的全部正例 qrels，包含未返回的正例；不能只對候選池計算。
- Precision 分母固定為 k；空結果計零，不從 macro average 移除。
- 未標註文件 gain=0，另外輸出 `judged@k`；不把「未標註」解釋成已證實不相關。
- 重複輸出 ID 直接拒絕評分，避免灌高命中數；資料缺失的 qrels reference 也報錯。

### 重現

下載僅需首次執行；資料放在 repo 外，依資料集原始條款使用，不將 corpus 打包進產品。

```bash
curl -fL https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/nfcorpus.zip -o /tmp/pubmed-nfcorpus.zip
uv run python -m zipfile -e /tmp/pubmed-nfcorpus.zip /tmp/pubmed-retrieval-data
uv run python scripts/benchmark_retrieval.py /tmp/pubmed-retrieval-data/nfcorpus --split dev --output /tmp/nfcorpus-dev.json
uv run python scripts/benchmark_retrieval.py /tmp/pubmed-retrieval-data/nfcorpus --split test --output /tmp/nfcorpus-test.json
```

可加 `--query-limit 10` 作快速 smoke；輸出會標記 subset，不應與完整 split 的分數比較。完整 JSON 含排序後 IDs、逐 query metrics、split、corpus size、qrels/corpus/query SHA-256。

重現修改前的 production 實作可使用隔離 checkout，並將本次新增的 evaluator 複製過去；不要修改工作中的來源碼：

```bash
git worktree add --detach /tmp/pubmed-benchmark-before dbcf0c88c76e6fac30877ff16a9850232e89bd4e
cp scripts/benchmark_retrieval.py /tmp/pubmed-benchmark-before/scripts/
cp src/pubmed_search/application/search/retrieval_metrics.py /tmp/pubmed-benchmark-before/src/pubmed_search/application/search/
PYTHONPATH=/tmp/pubmed-benchmark-before/src uv run python /tmp/pubmed-benchmark-before/scripts/benchmark_retrieval.py /tmp/pubmed-retrieval-data/nfcorpus --split test --output /tmp/nfcorpus-before.json
```

## 如何驗證「使用 repo」是否有效

必須區分兩個問題：**使用 PubMed Search MCP 是否幫助 Agent 完成研究**，以及
**這次修改是否優於原本的 MCP**。上面的 NFCorpus 比較只回答 BM25 元件版本差異；
它沒有執行 Agent，也沒有測量使用／不使用 MCP 的差異。

### 產品層級的三組配對實驗

| 組別 | Agent 可用能力 | 對照目的 |
| --- | --- | --- |
| A：原生 Codex | 內建 web search、讀網頁、shell／直接 PubMed API 存取，自行規劃、搜尋、讀文和選文 | 使用者原本已有的研究能力 |
| B：修改前完整套件 | 保留 A 全部原生能力，再增加原版 PubMed Search MCP 全工具與隨附研究 skills | B−A 衡量安裝原套件的增益 |
| C：修改後完整套件 | 保留 A 全部原生能力，再增加修改後 MCP 與隨附研究 skills | C−B 衡量修改效果；C−A 衡量目前套件增益 |

**A 不是另寫一個簡化搜尋工具，也不是禁止搜尋的裸模型。** B/C 不能移除 A 的
內建搜尋來強迫依賴 MCP。三組都實際執行自主多輪決策；B/C 的 query expansion、
多來源搜尋、全文、引用工具、排序與 session 能力保持可用，使用與否由 Agent 決定。

產品實驗保留原生線上搜尋，因此無法同時宣稱完全固定索引與語料。需要兩條分開報告的
實驗：線上 A/B 衡量實際安裝套件的效果；固定 corpus 對照則定位 query planning、
排序及選文機制。後者須共用 backend、snapshot 和資料存取範圍，不能代替前者。

固定核心任務提示、模型版本與生成設定；各組提供對應的工具 schema／必要使用說明，
完整保存其差異。若連 repo skills／工作流提示一起啟用，所得結論是整套產品組合的效果；
要將效果歸因於 server 程式，還需要另做相同工作流提示下的對照。

每個題目使用乾淨、彼此隔離的 session。各組可以生成不同查詢並走不同研究路徑；
把查詢序列寫死只能測 replay／pipeline，無法評估自主 query planning。

### 固定環境必須對查詢作出真實回應

目前 `tests/fixtures/offline_unified_mcp_server.py` 的搜尋 adapter 忽略 query，
固定回傳一篇測試文章；這適合測 MCP 契約、partial success 與 artifact recovery，
**不能當成搜尋品質或 Agent 決策 benchmark**。

新的評測環境需讓任意合法查詢在凍結索引上得到確定性結果；read 依 document ID
取得原文，references 依凍結引用圖返回鄰居。使用完整 MCP server 與實際 Agent loop，
透過既有 source injection 邊界替換外部資料來源。所有 enrichment、全文及 citation
操作也只能讀同一 snapshot；不能讓某組繞到即時網路取得額外證據。

### 用相同資源比較品質，也比較達到品質的成本

只限制「MCP tool call 次數」不公平：一次 `unified_search` 可能展開多個來源或查詢，
而 A 的一次 search 只做一次底層檢索。每次實驗應同時記錄並執行限制：

- LLM 輸入／輸出 tokens、模型成本與總耗時。
- 底層 search 次數、實際讀取的文件／段落數、citation graph 查詢量。
- MCP calls、重試、失敗、cache hits 與是否因預算停止。

主要比較固定底層搜尋／閱讀與 token 預算下的品質，另報告品質隨資源使用量的曲線。
冷啟動比較使用一致的空 cache；若評估 session 復用，作為獨立情境報告。
失敗與空結果保留在分母內，預算耗盡也必須明確記錄。

### 哪些結果足以支持「有效」

| 層次 | 主要問題 | 指標 |
| --- | --- | --- |
| 發現文獻 | 在預算內多找到多少相關研究？ | cumulative retrieval Recall@budget、nDCG@k |
| 選文 | 找到之後有沒有錯誤丟棄重要研究？ | selected precision/recall/F1、gold discard rate；retrieval 與 selection 分開 |
| 引用證據 | 引用的原文是否真的支持論述或關係？ | claim-evidence support、證據段落定位、supports/contradicts 判斷；DOI 存在與內容支持分開 |
| 綜述與效率 | 涵蓋哪些研究面向，花費多少資源？ | aspect coverage、未支援 claim 比例、成本、耗時、成功率 |

NFCorpus 可用於文獻層級評測，但沒有提供完整的 claim-support／citation-context
gold labels；引用語境階段須接 EvidenceBench、SciNet 的適合子集，或另外建立盲評標註。
不能從文獻 ID 命中率推論引用語境正確率。

題目按 dev/test 分離，test 的答案與標註不可交給 Agent。預先指定主要指標、
資源預算及有實用意義的最小改善幅度；每題配對比較，多次執行以涵蓋模型隨機性，
並以題目為單位估計信賴區間，避免把同題的重跑當成獨立題目。
需要 LLM／人工評分的報告隱藏組別並隨機排列。

同等資源下品質改善，或達到相近品質時成本下降，才支持 repo 的實用效果。
總分之外還要揭露下降的題型、漏篩與引用錯誤；結果只適用於測過的模型、資料與任務。
下方已實作兩種 Agent 評測入口；目前只做小型 A/B pilot，尚未完成完整 split、多次重跑
或 C 組的產品比較。不能把元件改善比例當成整套產品的改善比例。

### 產品 A/B：原生搜尋與完整套件

入口為 `scripts/benchmark_product_harness.py`。使用公開
[PaperSearchQA test split](https://huggingface.co/datasets/jmhb/PaperSearchQA) 的 5,000 題資料，
按 question SHA-256 排序選取 pilot 題目，不按答案、難度或成績選題。
這是從 PubMed abstracts 生成的 factoid QA，含答案別名和 originating PMID；
不是專家窮盡標註的相關文獻集合。[作者資料與方法](https://jmhb0.github.io/PaperSearchQA/)

兩組使用同一 Codex 模型、reasoning effort、原生 system instructions 與任務提示，
均保留 live web search、shell 和網路 API。每題建立空白 workspace，交替 A/B 執行順序。
B 啟動指定舊版本的原始 production entrypoint，沒有注入假資料、裁剪工具或關閉搜尋擴展。
原版 `.claude/skills/pubmed-*` 與 `pipeline-persistence` 完整複製到 Codex 可讀的
`.agents/skills/`，包括相對引用檔；並保存檔案 hash。這是 **Codex 上的 MCP + packaged skills**
效果，不包含只有 Copilot／Cline 才會執行的客戶端 hooks，也不包含外部 Zotero 套件。

答案與來源 PMID 僅交給外部 scorer，Agent 只收到問題。兩組禁止查閱 benchmark 答案庫。
任務檔隔離不等於 OS 層級的答案存取隔離；執行 trace 仍需稽核是否讀取題庫或答案來源。

主要指標：

- **Answer exact match**：lowercase、移除 ASCII punctuation／英文冠詞、合併空白後，
  與任一 gold alias 完整相等；不是 substring 命中。正規化依作者
  [EM scorer](https://github.com/jmhb0/PaperSearchQA/blob/main/search-r1/verl/utils/reward_score/qa_em.py)
  的定義，輸出解析改用 JSON schema。
- **Source PMID hit**：最後最多五篇引用是否包含題目原始來源 PMID。這不是全面 retrieval recall，
  也不是引用內容支持率；引用別篇同樣有用的文章仍可能在此指標得零。
- 同時報告成功率、原生 web／MCP／shell 呼叫、tokens 與耗時。失敗保留在分母。

目前硬限制只有每次執行 wall time；token／底層 API 次數只記錄而未實施相同上限。
因此結果是相同時間上限下的產品效果，不能宣稱相同 token 成本下的效率改善。
線上網路漂移、單次模型隨機性及很小樣本量都限制推論；不與官方固定 16M corpus 成績比較。

**2026-09-09 已完成三題產品 pilot**：Codex CLI 0.153.0、`gpt-6-astra`、xhigh，
每組每題最多 300 秒；B 使用 `dbcf0c88c76e6fac30877ff16a9850232e89bd4e`。
六次皆正常完成。B 每題實際讀取 `pubmed-quick-search` skill，總共呼叫五次 production MCP；
沒有強迫 B 放棄原生搜尋。完整逐題輸出、資源統計和 hash 見
[產品 A/B 實測紀錄](reports/native_codex_product_benchmark_2026-09-09.json)。

| 指標 | A 原生 Codex | B 原版完整套件 | B−A |
| --- | ---: | ---: | ---: |
| 嚴格答案 EM | 2/3（66.7%） | 2/3（66.7%） | 0 百分點 |
| 原始來源 PMID 命中 | 1/3（33.3%） | 1/3（33.3%） | 0 百分點 |
| 平均耗時 | 38.73 秒 | 46.20 秒 | +19.3% |
| 輸入 tokens 合計，含 cached | 275,292 | 328,951 | +19.5% |
| cached input tokens 合計 | 183,936 | 212,608 | +28,672 |
| 輸出 tokens 合計 | 1,236 | 1,750 | +514 |

**此 pilot 沒有顯示正向產品增益；也不足以證明套件無效或兩者等價。**
三題全部配對差值為零，使 bootstrap interval 退化成 `[0, 0]`；這不能反映未測題型
與模型重跑的不確定性，不作正式推論。這類短 factoid 題尚未涵蓋多篇文獻整合、
引用追溯、複雜選文與 session 續接的預期價值。

人工檢視第一題發現兩組都回答 thyroglobulin；A 把答案寫成 Markdown 連結，B 附帶
`(Tg)` 縮寫，與 gold aliases 的嚴格完整字串不符，因此都得零分。原始分數保留，
沒有事後擴充答案清單。這也說明 EM 不能直接當成科學語意正確率；正式評測需預先規定
答案格式，並另做隱藏組別的語意／證據支持判斷。來源 PMID 未命中也不表示其他引用無效。

```bash
# 使用前述隔離 checkout；產品實驗直接執行原版 source，不需複製新 evaluator 到舊版。
uv run python scripts/benchmark_product_harness.py /tmp/pubmed-product-benchmark-data/papersearchqa-test.json \
  --repo-root /tmp/pubmed-benchmark-before \
  --revision-label dbcf0c88c76e6fac30877ff16a9850232e89bd4e \
  --output-dir /tmp/pubmed-product-ab --model gpt-6-astra --effort xhigh \
  --query-limit 3 --timeout 300
```

輸入 JSON 為官方 test parquet 的完整 row array。一次性轉換可用
`uv run --with pyarrow python` 讀取作者 parquet，再將 `table.to_pylist()` 存成 JSON；
不需要把 pyarrow 加進產品依賴。需要已登入的 Codex CLI；本次沒有讀取或複製登入密鑰。
原始 events／網頁與 MCP 輸出留在指定輸出目錄，repo 僅保存彙總與 fingerprints。

### 完整 5,000 題的準備狀態（尚未啟動）

使用者指定本輪**只完成完整設定與驗證，不啟動長跑**。已建立
[完整 manifest](reports/papersearchqa_full_manifest_2026-09-09.json) 和
[準備驗證紀錄／可執行 argv](reports/papersearchqa_full_preflight_2026-09-09.json)。
本輪模型呼叫數為 **0**，`progress.json` 的狀態為 `prepared`、attempts 為 0。

v0.7.2 整合與 lockfile 更新後，已另建
[發布版 preflight](reports/papersearchqa_v072_preflight_2026-09-09.json)，
重新通過 `--resume --prepare-only`。新舊實驗皆維持 0 次執行，原版 B 仍固定在
`dbcf0c8`；發布版 preflight 不是原生 Codex 與 v0.7.2 的效果比較。

| 設定 | 值 |
| --- | --- |
| 題庫 | 官方 PaperSearchQA test 的 5,000 題完整 row array |
| 對照 | 原生 Codex vs 原生 Codex＋原版 production MCP＋packaged skills |
| 原版版本 | `dbcf0c88c76e6fac30877ff16a9850232e89bd4e`，來源 hash 已比對 |
| 模型 | `gpt-6-astra`，xhigh；同一 CLI 與 Python 環境 |
| 執行量 | 每題每組一次，共 10,000 次；原生能力兩組都保留 |
| 主要比較 | 排除已檢視的前三題 pilot，剩餘 4,997 題；三題仍執行及另存 |
| 單次時間上限 | 300 秒 |
| 硬 token／API 總額度 | 尚未設置；每批可按完成的配對題數暫停 |
| 帳戶限額／執行基礎設施故障 | 保存 attempt 並暫停，該組保持 pending，續跑只補缺少結果 |
| 任務逾時／無效答案 | 保留為零分的任務結果，計入品質與成本，不自動重抽答案 |

這是 **PaperSearchQA 全題庫上的線上產品對照**，並不代表所有 academic deep research
benchmarks 已備妥，也不是官方固定語料 leaderboard。嚴格 EM 和來源 PMID 指標的範圍
仍如上文；完整跑完也不能單靠這兩項推論引用語境、系統性回顧或長篇綜述品質。

依三題 pilot 粗估，單次完整 A/B 循序執行約 118 小時、10.07 億 input tokens（含 cached）、
498 萬 output tokens。估算來自極小樣本，並非費用報價或執行時間保證；目前未啟動這些用量。
Codex 的使用與 credits 規則依帳戶而異；本 runner 只讀取
[官方 non-interactive JSON events](https://learn.chatgpt.com/docs/non-interactive-mode)
中回報的 usage，不假設訂閱額度或付費 credits 足夠。

長跑 runner 已具備：

- `--all`：選取完整題庫；`--prepare-only`：驗證並保存設定，完全不呼叫模型。
- `--resume`：核對資料、來源、skills、模型、CLI／Python、評分器和依賴 hash；設定改變即拒絕混算。
- `--batch-size 100`：每次完成最多 100 個新的配對題目後暫停。下次以相同命令續跑，已完成組別不重跑。
- `--repeats N`：需要時對每題各組重跑 N 次。先在題內平均，再以題目為單位做 paired bootstrap。
  改 N 會形成不同實驗，不能在原 manifest 中途改動。
- JSON 檢查點採 atomic replace，並以單一 writer lock 防止兩個 runner 同時寫同一實驗。
  每次 attempt 的 trace、結果與成本都保存；失敗不覆寫。無完整 usage 的中斷標記為 unknown。
  長跑的 process groups 和檔案鎖限 POSIX 環境；相關測試在非 POSIX 上跳過，評分 helper
  的一般匯入不依賴 `fcntl`，避免影響 Windows CI。
- 執行 workspace 與外部 scorer／result 檔分開；只交付問題，gold answer／source PMID 不進入提示。
  這仍是操作層隔離，不能宣稱有 OS 層級防讀答案的完整沙箱。

準備的 v2 任務提示明確要求答案欄只有一個標準名稱，引用放在其他欄位，降低 pilot 的
Markdown／附加縮寫問題；gold aliases 和評分公式沒有改動，先前 pilot 分數不重新計算。

本機完整資料、原版 checkout 與執行紀錄保存在持久目錄：

```text
/home/eric/.local/share/pubmed-search-mcp/benchmarks/papersearchqa-2026-09-09/
  assets/papersearchqa-test.json
  assets/baseline-dbcf0c8/
  full-ab/manifest.json
  full-ab/progress.json
  full-ab/summary.json
```

以下只驗證既有完整設定，**不啟動模型**：

```bash
BENCHMARK_ROOT=/home/eric/.local/share/pubmed-search-mcp/benchmarks/papersearchqa-2026-09-09
uv run python scripts/benchmark_product_harness.py "$BENCHMARK_ROOT/assets/papersearchqa-test.json" \
  --repo-root "$BENCHMARK_ROOT/assets/baseline-dbcf0c8" \
  --revision-label dbcf0c88c76e6fac30877ff16a9850232e89bd4e \
  --output-dir "$BENCHMARK_ROOT/full-ab" --model gpt-6-astra --effort xhigh \
  --all --repeats 1 --development-query-count 3 --timeout 300 --resume --prepare-only
```

日後決定執行時，將最後的 `--prepare-only` 換成 `--batch-size 100`，每次最多執行
100 個新的配對題目；移除 `--prepare-only` 而不設 batch-size 則會嘗試跑完全部剩餘題目。
本輪**沒有執行這兩個啟動版本**。Resume 會核對 evaluator hash，因此修改相關程式後需重新
建立實驗，或使用保留的相同 evaluator，不能將不同 protocol 的結果接在一起。

### 固定語料：機制試跑，不代表原生 Codex 的產品基準

入口為 `scripts/benchmark_agent_harness.py` 與 `scripts/benchmark_agent_server.py`。
共用 BEIR NFCorpus 的 SQLite FTS5 BM25 OR-term 索引；基本組提供 search/read，
repo 組接原版 unified_search、讀文與 session。真實 Codex 自主決定查詢與選文，
不預寫搜尋軌跡；每題限制六次底層 search、120 次文件 exposure（重讀也計入）。
server 封鎖外部 socket，模型無 web／shell 工具；qrels 不交給工具端。

2026-09-15 的審查補強了評測完整性：corpus 要求唯一的非空字串 ID，避免數字／字串
轉換產生 ID 碰撞；budget／limit 必須為正整數，非法查詢參數不先扣額度。
audit 沿用共用原子寫檔工具。跨版本執行前會比對兩邊的 corpus adapter，內容不同就拒絕
啟動；請在隔離的評測 checkout 放置相同 adapter，再比較產品 source hash。
線上配對 runner 的 resume 同時驗證 protocol 型別、已知執行狀態與每次 trace hash，
資源統計也套用相同檢查。這些是離線可靠性驗證，沒有產生新的模型評分或 benchmark 增益。

這個診斷 profile 明確關閉 OA enrichment、自動放寬與 deep expansion，且只留 PubMed
adapter 可實作的搜尋、讀文和 session 工具，所以**不能以它回答「完整套件比原生 Codex 好多少」**。
數字 transport IDs 為合成 ID，並非真正 PMID；scorer 還原至 NFCorpus ID。
`retrieval_recall` 是底層取得的 candidate pool recall，未必全部呈現在 MCP 截斷後的回覆中；
`gold_discard_rate` 包含 server 截斷與 Agent 選文造成的損失，不能全部歸因於 Agent 判斷。

2026-09-09 的三題 dev 診斷 pilot：兩組 candidate recall 均為 0.634568、selected recall
均為 0.144444、selected F1 均為 0.206607；nDCG@10 基本組 0.376406、原版 repo
0.369072。這僅證實可執行、可配對評分，沒有顯示此窄 profile 的品質增益。
[固定語料診斷紀錄](reports/frozen_agent_diagnostic_2026-09-09.json)

```bash
mkdir -p /tmp/pubmed-benchmark-before/src/pubmed_search/infrastructure/evaluation
cp src/pubmed_search/infrastructure/evaluation/*.py /tmp/pubmed-benchmark-before/src/pubmed_search/infrastructure/evaluation/
uv run python scripts/benchmark_agent_harness.py /tmp/pubmed-retrieval-data/nfcorpus \
  --repo-root /tmp/pubmed-benchmark-before --revision-label dbcf0c88 \
  --output-dir /tmp/pubmed-frozen-ab --model gpt-6-astra --query-limit 3 --timeout 240
```

### 更完整的公開 Agent benchmark

AstaBench 的 PaperFindingBench、LitQA2-FullText-Search／LitQA2 與 ScholarQA 適合接續
評估找文、全文解答與綜述。若保留原生 web + 完整 PubMed MCP，依作者工具規則應歸入
**Custom**；只有將文獻存取限制在官方 date-restricted Asta MCP、在其上包裝我們介面時，
才符合 **Custom Interface**。不能將完整線上產品試驗包裝成 Standard 或 Custom Interface。
官方資料需 HF 帳戶接受 gated license，工具另需 ASTA_TOOL_KEY；目前未執行此套件。
[官方存取條件與工具分類](https://github.com/allenai/asta-bench#agent-tooling-categories)

## 接下來最值得做的改進

以下是後續優先順序；固定語料與產品 A/B runner 已完成 pilot，其餘不屬於已測得的成果。

| 優先順序 | 建議改進與既有落點 | 驗收方式 |
| --- | --- | --- |
| 1 | 擴大原生 Codex／完整套件的配對樣本與重跑；接 PaperFindingBench／LitQA2／ScholarQA 等較長工作流。固定 corpus 診斷另補全文與引用 snapshot。 | 預先登記主要指標與實用改善門檻，報告 quality、成本與題型；正式 test 排除已檢視的 pilot 題。產品 Custom 與固定 corpus 機制實驗分開。 |
| 2 | 在 application 層增加可評估的多輪 stopping/selection policy。根據每輪新增 unique evidence、重複比例和未覆蓋 PICO concept 做 query rewrite；重試僅限失敗來源。 | 固定 call budget 比較一次搜尋、固定多輪、adaptive 多輪；不能因為多呼叫十倍 API 而將所有增益歸因於規劃能力。保留選文與丟棄理由，計算 gold discard rate。 |
| 3 | 先取較大 candidate pool，再引入 query-aware reranker；與目前 BM25、balanced、RRF 分別做 ablation。使用 title/abstract 不足時才讀全文。 | NFCorpus/BioASQ 與 Asta retrieval 子集的 nDCG、recall、判斷成本；CSMeD 固定高 recall 目標下比較 screening workload，且不直接以 citation count 排除低引用正例。 |
| 4 | 在既有 citation tree/chronicle 上保存真正的 directed citation edge、來源與 supporting paragraph；將 co-mention、supports、contradicts 和僅相似分群分開。 | SciNet Medicine/Biology 的 edge/path/context accuracy；每條關係可回查文本，無語境時標 unknown。完整路徑正確率與單節點命中率分開。 |
| 5 | 將全文段落位置與 claim-evidence mapping 串接既有 fulltext、reference verification、chronicle/export。 | EvidenceBench 的 evidence/aspect coverage；ScholarQA-CS2/ResearchArena 的主題覆蓋、引用 precision/recall、未支援 claim 比例。格式與 mind-map 美觀度分開計分。 |

現有 `expected_recall`／`estimated_recall` 是策略啟發式估計，沒有 gold qrels，不可作為 benchmark recall。資料 snapshot、PMID/DOI identity、Agent 模型版本、prompt、工具預算、錯誤與每輪選文紀錄都必須一同固定，才有辦法持續比較。

## 回歸驗證

新增品質測試納入一般 pytest，因此既有 pre-push pytest gate 會執行，不必再增加一套獨立 hook。公開 corpus 評測則依上面的命令另跑，不在 commit 時下載資料。

```bash
uv run pytest -q tests/test_benchmark_retrieval.py tests/test_retrieval_metrics.py tests/test_retrieval_quality_regressions.py tests/test_ranking_algorithms.py tests/test_result_aggregator.py tests/test_pipeline.py
uv run pytest -q
uv run mypy src/ tests/
uv run python scripts/check_async_tests.py
uv run ruff check .
uv run ruff format --check .
git diff --check
```

修改前全套測試為 4,154 passed、38 skipped、1 failed；唯一失敗為 `tests/test_fulltext_urls.py::TestURLFormats::test_europe_pmc_pdf_url`，外部 Europe PMC 回傳 HTTP 520。這個 integration 測試直接請求固定 URL，不經過本次修改的搜尋／排序程式；不能把它列成新回歸，也不能因此宣稱全套測試全綠。最後一次結果見下方驗證紀錄。

- 修改後 `uv run pytest -q`：**4,183 passed、37 skipped、1 failed**，失敗仍是同一個 Europe PMC HTTP 520。Skipped 數會受外部可用性影響。
- `uv run pytest -q -m 'not integration'`：**4,163 passed、28 skipped、30 deselected**，無失敗。
- 新增 evaluator／品質回歸測試：**28 passed**。
- `uv run mypy src/ tests/`：通過，385 source files。
- Ruff lint、format check（417 files）、async/sync checker：通過。

新增 Agent 評測後的驗證：`uv run pytest -q -m 'not integration'` 為 **4,177 passed、
28 skipped、30 deselected**；隨後新增產品 runner 測試，相關測試加文件／entrypoint 檢查
與搜尋品質回歸共 **62 passed**。`uv run mypy src/ tests/` 通過（391 files），Ruff lint／format
（426 files）及 async checker 通過。新增工具僅存在於評測 launcher，不變更產品 MCP registry。

完整評測準備功能加入後，最新非整合回歸為 **4,199 passed、28 skipped、30 deselected**。
評測相關測試 **36 passed**，涵蓋 5,000 題零模型呼叫準備、分批續跑、額度暫停、逾時／中斷、
重複執行統計、資料驗證及 manifest／trace 不一致檢查。Mypy **393 files**、Ruff lint／format
**428 files**、async checker 通過。此輪沒有重新執行依賴外網的 integration suite；
先前 Europe PMC HTTP 520 的紀錄仍保留，不能宣稱所有外網整合測試通過。
