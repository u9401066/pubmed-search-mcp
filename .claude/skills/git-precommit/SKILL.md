---
name: git-precommit
description: "Orchestrate pre-commit workflow including Memory Bank sync, README/CHANGELOG/ROADMAP updates, and MCP tool count sync. Triggers: GIT, gc, push, commit, 提交, 準備 commit, 要提交了, git commit, pre-commit, 推送."
---

# Git 提交前工作流（編排器）

## 描述
協調多個 Skills 完成 Git 提交前的所有準備工作。
本專案同時使用 **pre-commit framework** 自動執行程式碼品質檢查，以及 **AI orchestrator** 處理文檔同步。

## 🔄 自演化循環 (Self-Evolution Cycle)

本專案的品質守門是一個自我演化的閉迴系統：

```
┌─────────────────────────────────────────────────────────────┐
│                自演化循環 (Self-Evolution Cycle)          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ① Instructions (copilot-instructions.md)                   │
│       │ 定義規範、引導 AI 使用 Skills                       │
│       ▼                                                      │
│  ② Skills (SKILL.md 檔案)                                   │
│       │ 確保建構完整、創建新 Hook                          │
│       ▼                                                      │
│  ③ Hooks (.pre-commit-config.yaml + scripts/hooks/)         │
│       │ 自動執行檢查、自動修正                            │
│       ▼                                                      │
│  ④ Validate (check_evolution_cycle.py)                       │
│       │ 驗證 ①②③ 的一致性                                  │
│       ▼                                                      │
│  ⑤ Feedback → 更新 Instructions & Skills                     │
│       │ 處理驗證失敗、補齊文檔、更新套件版本                │
│       └────→ 回到 ①（循環完成）                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 循環觸發時機

| 事件 | 觸發動作 |
|------|----------|
| 新增 Hook | Skill 創建 hook → evolution-cycle 驗證文檔及 instruction 是否同步 |
| 修改 Instruction | evolution-cycle 驗證 skill/hook 是否仍一致 |
| `pre-commit autoupdate` | 套件版本更新 → 自動演化 |
| 驗證失敗 | 報告不一致處，強制修復後才能 commit |

## 架構：雙層防護 + 自演化

```
┌─────────────────────────────────────────────────────────────┐
│                   Git Commit 防護架構                        │
├──────────────────────┬──────────────────────────────────────┤
│  Layer 1: 自動化     │  Layer 2: AI 編排器                   │
│  (pre-commit hooks)  │  (agent orchestrator)                │
├──────────────────────┼──────────────────────────────────────┤
│  ✅ ruff + ruff-format│  ✅ Memory Bank 同步                  │
│  ✅ bandit security  │  ✅ CHANGELOG 更新                    │
│  ✅ vulture deadcode │  ✅ ROADMAP 更新                      │
│  ✅ deptry deps      │  ✅ README 更新                       │
│  ✅ file-hygiene     │  ✅ 架構文檔檢查                      │
│  ✅ commit-size-guard│  ✅ Commit 訊息建議                   │
│  ✅ file-hygiene     │                                      │
│  ✅ commit-size-guard│                                      │
│  ✅ async-test-checker│                                      │
│  ✅ tool-count-sync  │                                      │
│  ✅ skills-frontmatter│                                     │
│  ✅ evolution-cycle  │                                      │
│  ✅ future-annotations│                                      │
│  ✅ no-print-in-src  │                                      │
│  ✅ ddd-layer-imports│                                      │
│  ✅ no-type-ignore-bare│                                    │
│  ✅ docstring-tools  │                                      │
│  ✅ no-env-inner-layers│                                    │
│  ✅ source-counts-guard│                                    │
│  ✅ todo-scanner     │                                      │
│  ✅ yaml/toml/json   │                                      │
│  ✅ no large files   │                                      │
│  ✅ no debug stmts   │                                      │
│  ✅ no private keys  │                                      │
│  ✅ BOM / symlinks   │                                      │
│  ✅ case conflicts   │                                      │
│  ✅ Windows names    │                                      │
│  ✅ mixed line ending│                                      │
│  ✅ no-commit-to-branch│                                    │
│  ✅ name-tests-test  │                                      │
│ ── Pre-push ──────── │                                      │
│  ✅ mypy (pre-push)  │                                      │
│  ✅ semgrep (pre-push)│                                     │
│  ✅ pytest (pre-push) │                                     │
├──────────────────────┼──────────────────────────────────────┤
│  🔧 自動修復：       │  🔧 自動修復：                        │
│  trailing whitespace │  tool-count-sync (auto-stage)        │
│  end-of-file newline │                                      │
│  ruff --fix          │                                      │
│  ruff format         │                                      │
│  future-annotations  │                                      │
└──────────────────────┴──────────────────────────────────────┘
```

## 開發者設定 (一次性)

```bash
uv sync                                         # 安裝所有依賴 (含 pre-commit)
uv run pre-commit install                       # 安裝 pre-commit hook
uv run pre-commit install --hook-type pre-push  # 安裝 pre-push hook (跑測試)
```

## Hook 自動演化 (Auto-Evolution)

### 套件版本更新
```bash
uv run pre-commit autoupdate                   # 更新所有 hook 版本 (ruff, pre-commit-hooks 等)
uv run pre-commit run --all-files              # 驗證更新後所有 hook 正常
```

### 循環一致性驗證
```bash
uv run python scripts/hooks/check_evolution_cycle.py  # 手動執行一致性檢查
```

此腳本驗證：
- 所有 hook ID 都在 instruction 和 skill 中被文檔化
- 所有 hook 引用的腳本檔案都存在
- CONTRIBUTING.md 的 hook 表格與 .pre-commit-config.yaml 一致
- pyproject.toml 的 addopts 強制多核
- Skill 文檔引用了正確的 hook 基礎設施

### 新增 Hook 的完整流程

當需要新增一個 hook 時，必須完成整個循環：

1. **創建 hook 腳本** → `scripts/hooks/<name>.py`
2. **註冊到 .pre-commit-config.yaml** → 加入 hook 定義
3. **更新 copilot-instructions.md** → Pre-commit Hooks 區塊
4. **更新本 SKILL.md** → 架構圖 Layer 1 列表
5. **更新 CONTRIBUTING.md** → hooks 表格
6. **執行驗證** → `uv run python scripts/hooks/check_evolution_cycle.py`
7. **確認通過** → evolution-cycle hook 自動在下次 commit 時檢查

> ⚠️ 如果只做了步驟 1-2 而沒有 3-5，evolution-cycle hook 會在 commit 時報錯。

> 💡 建議每月執行一次 `autoupdate`，自動取得最新的 ruff 規則、安全性檢查等。

## 觸發條件
- 「準備 commit」「要提交了」「git commit」

## 法規依據
- 憲法：CONSTITUTION.md 第三章
- 子法：.github/bylaws/git-workflow.md

## AI 編排器執行流程

當 AI agent 被要求「準備 commit」時，執行以下額外步驟：

```
┌─────────────────────────────────────────────────┐
│          AI Pre-Commit Orchestrator             │
├─────────────────────────────────────────────────┤
│  Step 1: memory-sync     [必要] Memory Bank 同步 │
│  Step 2: pre-commit-run  [必要] 執行所有 hooks   │
│  Step 3: readme-update   [可選] README 更新      │
│  Step 4: changelog-update[可選] CHANGELOG 更新   │
│  Step 5: roadmap-update  [可選] ROADMAP 更新     │
│  Step 6: arch-check      [條件] 架構文檔檢查     │
│  Step 7: commit-prepare  [最終] 準備提交         │
└─────────────────────────────────────────────────┘
```

> Step 2 會執行 `uv run pre-commit run --all-files`，涵蓋 ruff、file hygiene、tool docs sync 等所有自動化檢查。mypy 和 semgrep 已移至 pre-push 階段以防 OOM。

## 必要步驟：MCP 工具數量同步

由 pre-commit hook `tool-count-sync` 自動處理。也可手動執行：

```bash
uv run python scripts/count_mcp_tools.py --update-docs
```

此腳本會自動更新：
- `README.md` - 工具數量
- `README.zh-TW.md` - 工具數量
- `.github/copilot-instructions.md` - 工具數量 + 完整列表
- `src/.../TOOLS_INDEX.md` - 完整工具索引

## 參數

| 參數 | 說明 | 預設 |
|------|------|------|
| `--skip-readme` | 跳過 README 更新 | false |
| `--skip-changelog` | 跳過 CHANGELOG 更新 | false |
| `--skip-roadmap` | 跳過 ROADMAP 更新 | false |
| `--skip-hooks` | 跳過 pre-commit hooks | false |
| `--dry-run` | 只預覽不修改 | false |
| `--quick` | 只執行必要步驟 (memory-sync + hooks) | false |

## 使用範例

```
「準備 commit」           # 完整流程
「快速 commit」           # 等同 --quick
「commit --skip-readme」  # 跳過 README
```

## 跳過特定 Hook

```bash
SKIP=mypy git commit -m "quick fix"         # 跳過 mypy (較慢)
git commit --no-verify -m "emergency"       # 跳過所有 hooks (慎用!)
```

## 輸出格式

```
🚀 Git Pre-Commit 工作流

[1/7] Memory Bank 同步 ✅
  └─ progress.md: 更新 2 項
  └─ activeContext.md: 已更新

[2/7] Pre-commit Hooks ✅
  └─ ruff lint: passed (auto-fixed 3 issues)
  └─ ruff format: passed
  └─ mypy: passed
  └─ file hygiene: passed
  └─ tool docs sync: passed (2 files updated)

[3/7] README 更新 ✅
  └─ 新增功能說明

[4/7] CHANGELOG 更新 ✅
  └─ 添加 v0.2.0 條目

[5/7] ROADMAP 更新 ⏭️ (無變更)

[6/7] 架構文檔 ⏭️ (無結構性變更)

[7/7] Commit 準備 ✅
  └─ 建議訊息：feat: 新增用戶認證模組

📋 Staged files:
  - src/auth/...
  - docs/...

準備好了！確認提交？
```

## Hook 設定檔案

| 檔案 | 用途 |
|------|------|
| `.pre-commit-config.yaml` | pre-commit hooks 定義 |
| `pyproject.toml [tool.ruff]` | ruff lint + format 規則 |
| `pyproject.toml [tool.mypy]` | mypy type check 規則 |
| `pyproject.toml [tool.pytest] addopts` | 強制多核測試 |
| `pyproject.toml [tool.bandit]` | bandit 安全掃描規則 |
| `pyproject.toml [tool.deptry]` | deptry 依賴衛生規則 |
| `vulture_whitelist.py` | vulture 死碼掃描白名單 |
| `scripts/hooks/check_file_hygiene.py` | 檔案衛生檢查 |
| `scripts/hooks/check_tool_sync.py` | MCP 工具文檔同步 |
| `scripts/hooks/check_skills_frontmatter.py` | `.claude/skills` YAML frontmatter 驗證 |
| `scripts/hooks/check_evolution_cycle.py` | 自演化循環一致性驗證 |
| `scripts/hooks/check_commit_size.py` | Commit 檔案數限制 (≤30) |
| `scripts/hooks/check_future_annotations.py` | future annotations 強制 |
| `scripts/hooks/check_no_print.py` | 禁止 src/ 使用 print() |
| `scripts/hooks/check_ddd_layers.py` | DDD 層級依賴檢查 |
| `scripts/hooks/check_type_ignore.py` | 禁止裸 type: ignore |
| `scripts/hooks/check_docstring_tools.py` | MCP tool docstring 檢查 |
| `scripts/hooks/check_env_config.py` | 禁止內層使用 os.environ |
| `scripts/hooks/check_source_counts.py` | 確保每來源 API 回傳量顯示 |
| `scripts/hooks/check_todo_scanner.py` | TODO/FIXME 掃描 |
| `scripts/check_async_tests.py` | async/sync 測試一致性 |
