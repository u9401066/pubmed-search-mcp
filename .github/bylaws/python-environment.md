# Python 環境管理子法

> 依據憲法第 7.2 條「環境即程式碼」訂定

---

## 第 1 條：套件管理器優先順序

```
uv > pip-tools > pip
```

### 1.1 uv 優先原則
1. **新專案必須使用 uv** 作為套件管理器
2. uv 速度比 pip 快 10-100 倍
3. 原生支援 lockfile 和虛擬環境

### 1.2 降級條件
僅在以下情況可使用 pip：
- 舊專案遷移成本過高
- CI 環境不支援 uv
- 特殊依賴衝突

---

## 第 2 條：虛擬環境規範

### 2.1 必須使用虛擬環境
```bash
# ✅ 正確
uv venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# ❌ 禁止全域安裝
pip install package  # 在系統 Python 中
```

### 2.2 虛擬環境位置
```
project/
├── .venv/           # 虛擬環境（gitignore）
├── pyproject.toml   # 專案配置
└── uv.lock          # 依賴鎖定（版控）
```

### 2.3 Python 版本
- 新專案使用 Python 3.11+
- 版本在 `pyproject.toml` 中明確指定

---

## 第 3 條：依賴管理

### 3.1 檔案結構
```
pyproject.toml       # 主要依賴定義（必須）
uv.lock              # 依賴鎖定檔（必須，納入版控）
requirements.txt     # 相容性匯出（可選，CI 用）
```

### 3.2 pyproject.toml 範本
```toml
[project]
name = "my-project"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.104.0",
    "sqlalchemy>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",
    "ruff>=0.1.0",
    "mypy>=1.5.0",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
dev-dependencies = [
    "pytest>=7.4.0",
    "ruff>=0.1.0",
]
```

### 3.3 常用 uv 指令
```bash
# 初始化專案
uv init my-project
cd my-project

# 建立虛擬環境
uv venv

# 安裝依賴
uv pip install -e ".[dev]"
uv sync  # 根據 uv.lock 同步

# 新增依賴
uv add fastapi
uv add --dev pytest

# 移除依賴
uv remove package-name

# 更新依賴
uv lock --upgrade

# 匯出 requirements.txt（相容 CI）
uv pip compile pyproject.toml -o requirements.txt
```

---

## 第 4 條：專案初始化流程

### 4.1 新專案（使用 uv）
```bash
# 1. 建立專案
uv init my-project
cd my-project

# 2. 設定 Python 版本
uv python pin 3.11

# 3. 安裝開發依賴
uv add --dev pytest ruff mypy

# 4. 建立目錄結構
mkdir -p src/domain src/application src/infrastructure src/presentation
mkdir -p tests/unit tests/integration tests/e2e
touch src/__init__.py tests/__init__.py

# 5. 初始化 Memory Bank
mkdir memory-bank
touch memory-bank/{activeContext,progress,decisionLog,productContext,projectBrief,systemPatterns,architect}.md
```

### 4.2 現有專案遷移
```bash
# 1. 從 requirements.txt 遷移
uv pip compile requirements.txt -o requirements.lock
uv venv
uv pip sync requirements.lock

# 2. 建立 pyproject.toml
uv init --no-workspace

# 3. 遷移依賴
uv add $(cat requirements.txt | grep -v "^#" | tr '\n' ' ')

# 4. 鎖定依賴
uv lock
```

---

## 第 5 條：CI/CD 整合

### 5.1 GitHub Actions 使用 uv
```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Install uv
        uses: astral-sh/setup-uv@v4
        with:
          version: "latest"
      
      - name: Set up Python
        run: uv python install 3.11
      
      - name: Install dependencies
        run: uv sync --all-extras
      
      - name: Run tests
        run: uv run pytest
```

### 5.2 Docker 使用 uv
```dockerfile
FROM python:3.11-slim

# 安裝 uv（從官方映像複製）
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./

# 安裝依賴（不使用虛擬環境）
RUN uv pip install --system --no-cache -r pyproject.toml

COPY . .
CMD ["python", "-m", "src.main"]
```

### 5.3 uvx 工具執行（類似 npx）
```bash
# 臨時執行工具（不安裝）
uvx ruff check .
uvx black --check .
uvx mypy src/

# 執行特定版本
uvx ruff@0.1.0 check .
```

---

## 第 6 條：常見問題

### Q1: uv 和 pip 可以混用嗎？
A: 不建議。混用可能導致依賴衝突。若必須，先用 `uv pip` 取代 `pip`。

### Q2: 為什麼不用 Poetry/Pipenv？
A: uv 比 Poetry 快 10-100 倍，且與 pip 完全相容。Poetry 的 resolver 較慢。

### Q3: Windows 支援如何？
A: uv 完整支援 Windows。安裝：`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`

### Q4: 如何處理私有套件？
A: 在 `pyproject.toml` 中設定：
```toml
[tool.uv]
index-url = "https://pypi.org/simple"
extra-index-url = ["https://your-private-pypi.com/simple"]
```

---

## 附錄：快速參考卡

| 操作 | uv 指令 | pip 對應 |
|------|---------|----------|
| 建立 venv | `uv venv` | `python -m venv .venv` |
| 安裝套件 | `uv add package` | `pip install package` |
| 安裝開發依賴 | `uv add --dev package` | `pip install package` |
| 安裝全部 | `uv sync` | `pip install -r requirements.txt` |
| 更新 lock | `uv lock` | `pip-compile` |
| 執行命令 | `uv run pytest` | `pytest` |
| 查看依賴 | `uv pip list` | `pip list` |

---

*本子法版本：v1.0.0*
*依據：憲法第 7.2 條*
