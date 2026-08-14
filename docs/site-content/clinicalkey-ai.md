<!-- Generated from docs/CLINICALKEY_AI_INTEGRATION.md by scripts/build_docs_site.py -->
<!-- markdownlint-configure-file {"MD051": false} -->
<!-- markdownlint-disable MD051 -->

# ClinicalKey AI：Licensed Evidence Data-plane Boundary

| Field | Value |
| --- | --- |
| Status | Default-off application/data-plane adapter; not an MCP source/tool |
| Upstream API | ClinicalKey AI Public API 1.0.0 (OpenAPI 3.0.3) |
| Verified | 2026-08-14 |
| Public base URL | `https://api-us.digital.elsevier.com/knowledge/clinicalkey/ai` |
| Token URL | `https://access.identity.elsevier.com/realms/digital/protocol/openid-connect/token` |

## 結論

ClinicalKey AI 目前**不**註冊成 `unified_search` source，也**不**新增任何
`search_clinicalkey*`、conversation 或 diagnosis MCP tool。

本 repo 第一階段只提供 default-off、credential-gated、zero-persistence 的
application/data-plane adapter，讓取得正式 entitlement 的 operator 可以做合約
驗證與 synthetic integration。它不會寫入 session、cache、pipeline、scheduler、
artifact、notes、Research Chronicle 或 export。

在 Elsevier 書面確認 MCP、retention、multi-user、end-user identity 與 institutional
terms 前，不得把這個 adapter 接到 runtime MCP surface。

## 為什麼不是 literature search source

ClinicalKey AI citations API 是 AI-curated clinical answer/citation RAG，不是完整、
可重現的書目索引：

- 單一問題回傳 curated citations，不宣稱 systematic coverage
- response 可能包含 proprietary chunks、summary 與 copyright metadata
- v2 需要真實 end-user identity/persona
- ClinicalKey/Elsevier 的存取、retention 與 AI-system 條款取決於 operator 的
  entitlement/order form
- differential-diagnosis 路徑還涉及 PHI、BAA、clinical decision safety

因此把它和 PubMed/OpenAlex/S2 records 無差別 merge、rank、persist 或 export，會
同時破壞 evidence semantics、reproducibility 與授權邊界。

## 官方參考

- [ClinicalKey AI Public API](https://developer.digital.elsevier.com/documentation/knowledge_clinicalkey-ai-public)
- [Accessing APIs](https://developer.digital.elsevier.com/Guides/Getting_Started/accessing_apis)
- [Creating credentials](https://developer.digital.elsevier.com/Guides/Getting_Started/creating_credentials)
- [Client Credentials flow](https://developer.digital.elsevier.com/Guides/Authentication_and_Authorization/Using_Credentials/requests_by_flow/ClientCredentials_flow_request)
- [Refreshing access tokens](https://developer.digital.elsevier.com/Guides/Authentication_and_Authorization/Using_Credentials/requests_by_flow/Refreshing-access-tokens)
- [Credential security](https://developer.digital.elsevier.com/Guides/Managing_Credentials/manage_credentials_securely)
- [Rate limits](https://developer.digital.elsevier.com/Guides/Usage-and-rate-limits/Understanding-rate-limits)
- [Rate-limit response headers](https://developer.digital.elsevier.com/Guides/Usage-and-rate-limits/Check-rate-limits-using-API-requests)
- [Handling 429](https://developer.digital.elsevier.com/Guides/Usage-and-rate-limits/Handling-429-response-errors)
- [Elsevier API Service Agreement](https://dev.elsevier.com/api_service_agreement.html)
- [Clinical Solutions terms](https://www.elsevier.com/legal/elsevier-clinical-solutions-terms-and-conditions-of-supply)
- [ClinicalKey AI product safety](https://www.elsevier.support/clinicalkeyai/answer/how-does-clinicalkey-ai-address-product-safety)

「Public API」表示公開的 API documentation，不表示匿名、免費或已授權存取。官方
onboarding 要求 licensed API access；無 Bearer 呼叫 `/healthcheck` 也會得到 401。

## OAuth client-credentials 契約

Token request 為 form-encoded：

```text
grant_type=client_credentials
client_id=<operator secret>
client_secret=<operator secret>
```

Client 必須：

- 依 token response 的 `expires_in`，使用 monotonic clock 與安全 skew
- concurrent callers 共用 single-flight refresh
- 不假設一定有 refresh token；到期時重新執行 client-credentials flow
- 401 只 invalidate token 並 retry 一次
- 不自行猜測 scope
- client secret/access token 僅存在記憶體與 operator secret store/env
- 不把 secret/token 放進 URL、log、exception、artifact 或測試 snapshot

官方頁面對 token 5 或 15 分鐘的文字不一致，所以程式不得硬編任一值。

## Citations endpoints

### v1

`POST /api/v1/citations`

```json
{"question": "a non-PHI clinical evidence question"}
```

除 Bearer token 外沒有 end-user headers。

### v2

`POST /api/v2/citations` 使用相同 body，另要求：

- `End-User-Id`
- `End-User-Persona`
- optional `Secondary-Org-Id`

Persona 沒有公開 enum。不得把 MCP transport session、隨機 tenant hash 或 local
username 冒充 Elsevier end user；mapping 必須由 institution/Elsevier 明確提供。

### Tolerant response parsing

公開 OpenAPI 有 wrapper/unwrapped example、required/property、PMID type 與 citation
map key 不一致。Parser 必須容忍：

- `result` wrapper 有或沒有
- PMID 是 integer 或 string
- citation map keys 是 integer-like strings
- optional/partial references
- error payload 額外或缺少欄位
- `references` 是 map-of-lists、plain list，或每筆外包 `result` / `_source`

目前 adapter 會把 map-of-lists flatten 成一個有順序的 citation batch，依
DOI/PMID/provider identifier 去重，並保留 `provider_reference_count` 與
`dropped_reference_count`。每筆輸出只可能有 `reference_id`、title/container、
authors、DOI、PMID、provider identifier/type、publication date 與已移除 query/
fragment 的 safe href。Question、generated answer 與 raw provider payload 不會
進入回傳 dataclass。

HTTP 2xx 不等於成功：若 body 是 `status="error"` 或其他 documented error
envelope，adapter 會以 sanitized response error fail closed，不回傳空 citation
batch，也不把 provider error text、question 或 licensed content放進 exception。

允許抽取的最小 metadata 只有 DOI、PMID、title、authors、publication date 與必要
provider identifier/href。`chunk_text`、summary、breadcrumbs、content properties、
copyrighted snippets 與原始 licensed payload 必須在 adapter boundary 丟棄。

若未來獲得書面核准，這些 DOI/PMID 仍應再向 PubMed、Crossref 或 OpenAlex取得公開
metadata；final answer 引用原始文獻，而不是引用 ClinicalKey AI 回應。

## Data-governance policy

ClinicalKey AI policy 固定為：

| Dimension | Contract |
| --- | --- |
| Access tier | Licensed clinical evidence |
| Default state | Disabled |
| MCP registration | Forbidden in this phase |
| Retention | Ephemeral / metadata allowlist only |
| Raw response persistence | Forbidden |
| Session/cache/artifact/export | Forbidden |
| Pipeline/scheduler | Forbidden |
| Auto dispatch | Forbidden |
| Systematic coverage claim | Forbidden |
| PHI | Forbidden |
| Training/embedding/vectorization | Forbidden without explicit written rights |

Runtime enablement 必須同時具有：

```text
CLINICALKEY_AI_ENABLED=true
CLINICALKEY_AI_ENTITLEMENT_CONFIRMED=true
CLINICALKEY_AI_CONTRACT_ACKNOWLEDGED=true
CLINICALKEY_AI_CLIENT_ID=...
CLINICALKEY_AI_CLIENT_SECRET=...
```

這些 flags 不是法律授權本身；它們只是 operator 已完成外部審查的 fail-closed
assertion。任何一項缺少時 adapter 必須拒絕執行。

## 明確不實作的 endpoints

### Differential diagnosis

不得實作：

- `/api/v2/differential-diagnosis`
- `/api/v2/differential-diagnosis/streaming`

它們接收 patient summary、EHR/notes context、retrieval context、trace/session IDs，
並需要 `Shared-Key`。這超出 literature research MCP 範圍，涉及 PHI/BAA、臨床
決策、醫材/法規與病人安全。response 中的 `deidentification` boolean 不是資料已
符合 operator 法律義務的保證。

### Conversation 與 article state

`/conversation` 與 `/article` 路徑也不在第一階段，因為它們可能建立 Elsevier
端 history/state 或帶出 proprietary content，容易和本 repo 的 session/persistence
語意混淆。

## Rate limit

ClinicalKey AI 沒有公開固定 RPS。不要從 portal examples 猜 quota。Client 應：

- 以 concurrency 1 起步
- 共用 credential-wide limiter
- 解析 `X-RateLimit-Limit-N`、`Remaining-N`、`Reset-N`
- 429 依 reset/Retry-After bounded cooldown，不 parallel retry
- 403/422 不 retry；401 refresh once；5xx 使用 bounded jitter/circuit breaker

多 worker deployment 若要共用同一 credential，需要 distributed budget；
process-local limiter 不能宣稱是完整的 institution-wide quota enforcement。

## 測試與 live gate

一般 CI 只使用 synthetic fixtures：

- `expires_in`/skew/single-flight
- 401 refresh once，403/422 no retry，429 reset/cooldown
- v2 end-user headers
- wrapper/schema drift、PMID int/string、partial references
- raw chunk stripping與 output allowlist
- secret/token log redaction
- session、artifact、export、pipeline、scheduler 零持久化
- runtime MCP tool count/search group完全不因 enable flags 改變
- HTTP 200 error union fail closed、map-of-lists flatten 與 duplicate/drop counts

Live smoke 必須在獨立 explicit gate 中執行，只能使用 non-PHI synthetic question，
不保存 response；沒有 entitlement secrets 時直接 skip。

## 未來升級條件

只有在 Elsevier/機構以書面確認下列問題後，才重新審查是否接到
`unified_search`：

1. MCP/connector/RAG 使用是否在實際 order/API agreement 允許；
2. single-user 與 multi-user deployment 的 Authorized User 邊界；
3. end-user persona/ID/tenant contract；
4. DOI/PMID metadata retention、rehydration 與 export 權利；
5. PHI/BAA 明確範圍；
6. quota/reset/header 契約。

即使通過，最多也只能是 explicit-only、enrichment-only companion：不 auto、不
單獨 primary search、不提供 systematic coverage、不 persistence，且仍不新增第二個
通用搜尋 tool。
