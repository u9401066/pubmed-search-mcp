---
name: test-generator
description: "Generate comprehensive test suites including static analysis, unit tests, integration tests, E2E tests, and coverage reports. Triggers: TG, test, 測試, 寫測試, coverage, 覆蓋率, pytest, unittest, 驗證."
---

# 測試生成技能

## ⚗️ 本專案規範 (CRITICAL)

**所有命令一律透過 `uv run` 執行**，包括測試、lint、type check：

```bash
uv run pytest                        # ⩡ 多核平行測試（預設 -n auto --timeout=60）
uv run ruff check .                 # Lint
uv run ruff format .                # 格式化
uv run mypy src/ tests/             # 型別檢查（含 tests）
uv run pytest --cov                 # 多核 + 覆蓋率
```

> 💡 UV 使用 Rust 實作，比 pip 快 10-100 倍。`uv run` 在毫秒級確認環境後直接執行，幾乎零開銷。
> ⚠️ **永遠不要**直接呼叫 `pytest`、`ruff`、`mypy`。

### ⏱️ 測試執行時間 (CRITICAL - 必讀)

本專案使用 **pytest-xdist** 多核平行測試，規模：**30,000+ 行、2200+ 測試案例、60+ 測試檔案**。

| 指標 | 數值 |
|------|------|
| ⚡ 多核執行時間 (`-n auto`) | **~67 秒** |
| 單核執行時間 | 180~240 秒 |
| 每個測試超時 | 60 秒 (`--timeout=60`) |
| 建議 terminal timeout | **120,000+ ms**（多核）/ 300,000+ ms（單核） |

```bash
# ✅ 推薦：多核平行測試
uv run pytest tests/ -n auto --timeout=60 -q

# ✅ 導向檔案
uv run pytest tests/ -n auto --timeout=60 -q 2>&1 > scripts/_tmp/test_result.txt
# 等待 ~70 秒後再讀取

# ⚠️ 覆蓋率不可搭配 -n auto
uv run pytest tests/ --timeout=60 --cov -q
```

> 💡 `-n auto` 自動偵測 CPU 核心數，每個 worker 為獨立 process，singleton 隔離無衝突。
> ⚠️ `pytest-benchmark` 在 xdist 模式下自動停用。

## 描述
為指定的程式碼自動生成完整測試套件，包含靜態分析、單元測試、整合測試及覆蓋率報告。

## 觸發條件
- 「生成測試」、「寫測試」、「test this」
- 「建立單元測試」、「建立整合測試」
- 「靜態分析」、「type check」
- 「覆蓋率」、「coverage」

---

## 測試金字塔

```
        /\
       /  \      E2E Tests (少量)
      /----\
     /      \    Integration Tests (中等)
    /--------\
   /          \  Unit Tests (大量)
  /------------\
 / Static Analysis (基礎)
```

---

## Python 測試策略

### 1️⃣ 靜態分析 (Static Analysis)

#### 工具配置

| 工具 | 用途 | 配置檔 |
|------|------|--------|
| **mypy** | 類型檢查 | `pyproject.toml` / `mypy.ini` |
| **ruff** | Linting + Formatting (取代 pylint/flake8/black) | `pyproject.toml` |
| **bandit** | 安全性掃描 | `.bandit` |

#### mypy 配置範例
```toml
# pyproject.toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
no_implicit_optional = true

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_defs = false
```

#### ruff 配置範例
```toml
# pyproject.toml
[tool.ruff]
target-version = "py311"
line-length = 88
select = [
    "E",   # pycodestyle errors
    "W",   # pycodestyle warnings
    "F",   # pyflakes
    "I",   # isort
    "B",   # flake8-bugbear
    "C4",  # flake8-comprehensions
    "UP",  # pyupgrade
    "ARG", # flake8-unused-arguments
    "SIM", # flake8-simplify
]
ignore = ["E501"]  # line too long (handled by formatter)

[tool.ruff.isort]
known-first-party = ["src"]
```

### 2️⃣ 單元測試 (Unit Tests)

#### ⚠️ Async 測試規範 (本專案 CRITICAL)

本專案使用 `asyncio_mode = "auto"`。**每次新增測試後必須執行**：

```bash
uv run python scripts/check_async_tests.py
```

規則：
- async 方法的 mock 必須用 `AsyncMock()`（不是 `Mock()`）
- 呼叫 async 方法必須加 `await`
- 測試 async 方法的函數必須是 `async def`
- 不需要 `@pytest.mark.asyncio`（`asyncio_mode = "auto"` 已自動偵測）

#### pytest 配置
```toml
# pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py", "*_test.py"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--strict-markers",
    "--tb=short",
    "-ra",
]
markers = [
    "unit: Unit tests",
    "integration: Integration tests",
    "slow: Slow running tests",
]
filterwarnings = [
    "error",
    "ignore::DeprecationWarning",
]
```

#### 測試結構
```
tests/
├── __init__.py
├── conftest.py           # 共用 fixtures
├── unit/                 # 單元測試
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_domain/      # Domain 層測試
│   ├── test_application/ # Application 層測試
│   └── test_utils/
├── integration/          # 整合測試
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_api/
│   ├── test_database/
│   └── test_external/
└── e2e/                  # 端對端測試
    └── ...
```

#### 單元測試範例
```python
# tests/unit/test_domain/test_user.py
import pytest
from src.domain.entities import User
from src.domain.exceptions import ValidationError


class TestUser:
    """User entity 單元測試"""

    # === Happy Path ===
    def test_create_user_with_valid_data(self):
        """正常建立使用者"""
        user = User(name="Alice", email="alice@example.com")
        assert user.name == "Alice"
        assert user.email == "alice@example.com"

    # === 邊界條件 ===
    def test_create_user_with_minimum_name_length(self):
        """名稱最小長度"""
        user = User(name="A", email="a@b.c")
        assert len(user.name) == 1

    @pytest.mark.parametrize("name,expected", [
        ("A" * 100, 100),
        ("中文名字", 4),
    ])
    def test_name_length_variations(self, name: str, expected: int):
        """名稱長度變化測試"""
        user = User(name=name, email="test@test.com")
        assert len(user.name) == expected

    # === 錯誤處理 ===
    def test_create_user_with_empty_name_raises_error(self):
        """空名稱應拋出 ValidationError"""
        with pytest.raises(ValidationError, match="Name cannot be empty"):
            User(name="", email="test@test.com")

    def test_create_user_with_invalid_email_raises_error(self):
        """無效 email 應拋出 ValidationError"""
        with pytest.raises(ValidationError, match="Invalid email format"):
            User(name="Test", email="not-an-email")

    # === Null/None 處理 ===
    def test_create_user_with_none_name_raises_error(self):
        """None 名稱應拋出 TypeError"""
        with pytest.raises(TypeError):
            User(name=None, email="test@test.com")
```

### 3️⃣ 整合測試 (Integration Tests)

#### API 整合測試
```python
# tests/integration/test_api/test_user_api.py
import pytest
from httpx import AsyncClient
from src.main import app


@pytest.mark.integration
@pytest.mark.asyncio
class TestUserAPI:
    """User API 整合測試"""

    async def test_create_user_endpoint(self, async_client: AsyncClient):
        """POST /users 建立使用者"""
        response = await async_client.post(
            "/api/v1/users",
            json={"name": "Test User", "email": "test@example.com"}
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test User"
        assert "id" in data

    async def test_get_user_endpoint(self, async_client: AsyncClient, created_user):
        """GET /users/{id} 取得使用者"""
        response = await async_client.get(f"/api/v1/users/{created_user.id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(created_user.id)

    async def test_get_nonexistent_user_returns_404(self, async_client: AsyncClient):
        """取得不存在的使用者應返回 404"""
        response = await async_client.get("/api/v1/users/nonexistent-id")
        assert response.status_code == 404
```

#### 資料庫整合測試
```python
# tests/integration/test_database/test_user_repository.py
import pytest
from src.infrastructure.repositories import UserRepository
from src.domain.entities import User


@pytest.mark.integration
class TestUserRepository:
    """UserRepository 整合測試 (實際資料庫)"""

    @pytest.fixture
    def repository(self, db_session):
        return UserRepository(session=db_session)

    async def test_save_and_retrieve_user(self, repository: UserRepository):
        """儲存並取回使用者"""
        user = User(name="Test", email="test@test.com")
        saved_user = await repository.save(user)

        retrieved = await repository.get_by_id(saved_user.id)
        assert retrieved is not None
        assert retrieved.name == "Test"

    async def test_find_by_email(self, repository: UserRepository):
        """透過 email 查詢"""
        user = User(name="Test", email="unique@test.com")
        await repository.save(user)

        found = await repository.find_by_email("unique@test.com")
        assert found is not None
        assert found.email == "unique@test.com"
```

#### conftest.py (整合測試 fixtures)
```python
# tests/integration/conftest.py
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

from src.main import app
from src.infrastructure.database import Base


# === 測試資料庫 ===
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture(scope="session")
def event_loop():
    """建立 event loop for async tests"""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    """建立測試資料庫引擎"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    """建立測試資料庫 session"""
    async_session = sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session
        await session.rollback()


# === HTTP Client ===
@pytest_asyncio.fixture
async def async_client():
    """建立非同步 HTTP 測試客戶端"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
```

### 5️⃣ E2E 測試 (End-to-End Tests)

#### E2E 測試工具選擇

| 工具 | 適用場景 | 特點 |
|------|----------|------|
| **Playwright** | Web UI 測試 | 跨瀏覽器、自動等待、截圖/錄影 |
| **Selenium** | 傳統 Web 測試 | 廣泛支援、成熟穩定 |
| **pytest + httpx** | API E2E | 輕量、快速 |
| **Locust** | 負載/效能測試 | 分散式、Python 原生 |

#### Playwright 配置 (推薦)
```toml
# pyproject.toml
[tool.pytest.ini_options]
markers = [
    "e2e: End-to-end tests (require running application)",
]
```

```python
# tests/e2e/conftest.py
import pytest
from playwright.async_api import async_playwright, Browser, Page


@pytest.fixture(scope="session")
def browser_type():
    """可透過環境變數切換瀏覽器"""
    import os
    return os.getenv("BROWSER", "chromium")  # chromium, firefox, webkit


@pytest.fixture(scope="session")
async def browser(browser_type: str):
    """建立瀏覽器實例 (session 級別)"""
    async with async_playwright() as p:
        browser = await getattr(p, browser_type).launch(
            headless=True,
            slow_mo=100,  # 放慢操作以便觀察
        )
        yield browser
        await browser.close()


@pytest.fixture
async def page(browser: Browser):
    """建立新頁面 (每個測試獨立)"""
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        record_video_dir="test-results/videos",  # 錄製影片
    )
    page = await context.new_page()
    yield page
    await context.close()


@pytest.fixture
def base_url():
    """應用程式 base URL"""
    import os
    return os.getenv("APP_URL", "http://localhost:8000")
```

#### E2E 測試範例
```python
# tests/e2e/test_user_journey.py
import pytest
from playwright.async_api import Page, expect


@pytest.mark.e2e
@pytest.mark.asyncio
class TestUserJourney:
    """使用者旅程 E2E 測試"""

    async def test_user_registration_flow(self, page: Page, base_url: str):
        """測試完整註冊流程"""
        # 1. 前往註冊頁面
        await page.goto(f"{base_url}/register")
        await expect(page).to_have_title("Register")

        # 2. 填寫表單
        await page.fill("input[name='username']", "testuser")
        await page.fill("input[name='email']", "test@example.com")
        await page.fill("input[name='password']", "SecureP@ss123")
        await page.fill("input[name='confirm_password']", "SecureP@ss123")

        # 3. 提交表單
        await page.click("button[type='submit']")

        # 4. 驗證結果
        await expect(page).to_have_url(f"{base_url}/dashboard")
        await expect(page.locator(".welcome-message")).to_contain_text("Welcome, testuser")

    async def test_login_logout_flow(self, page: Page, base_url: str):
        """測試登入登出流程"""
        # 登入
        await page.goto(f"{base_url}/login")
        await page.fill("input[name='email']", "test@example.com")
        await page.fill("input[name='password']", "SecureP@ss123")
        await page.click("button[type='submit']")

        await expect(page.locator(".user-menu")).to_be_visible()

        # 登出
        await page.click(".logout-button")
        await expect(page).to_have_url(f"{base_url}/")

    async def test_create_item_flow(self, page: Page, base_url: str, authenticated_page):
        """測試建立項目流程 (需登入)"""
        await authenticated_page.goto(f"{base_url}/items/new")

        await authenticated_page.fill("input[name='title']", "Test Item")
        await authenticated_page.fill("textarea[name='description']", "Description")
        await authenticated_page.click("button[type='submit']")

        await expect(authenticated_page.locator(".success-toast")).to_be_visible()
```

#### API E2E 測試 (無 UI)
```python
# tests/e2e/test_api_e2e.py
import pytest
import httpx


@pytest.mark.e2e
@pytest.mark.asyncio
class TestAPIEndToEnd:
    """API E2E 測試 - 測試完整 API 流程"""

    @pytest.fixture
    async def client(self, base_url: str):
        async with httpx.AsyncClient(base_url=base_url) as client:
            yield client

    async def test_complete_crud_flow(self, client: httpx.AsyncClient):
        """測試完整 CRUD 流程"""
        # Create
        response = await client.post("/api/v1/items", json={"name": "Test"})
        assert response.status_code == 201
        item_id = response.json()["id"]

        # Read
        response = await client.get(f"/api/v1/items/{item_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Test"

        # Update
        response = await client.put(
            f"/api/v1/items/{item_id}",
            json={"name": "Updated"}
        )
        assert response.status_code == 200

        # Delete
        response = await client.delete(f"/api/v1/items/{item_id}")
        assert response.status_code == 204

        # Verify deletion
        response = await client.get(f"/api/v1/items/{item_id}")
        assert response.status_code == 404
```

---

### 6️⃣ 覆蓋率 (Coverage)

#### pytest-cov 配置
```toml
# pyproject.toml
[tool.coverage.run]
source = ["src"]
branch = true
parallel = true
omit = [
    "*/tests/*",
    "*/__init__.py",
    "*/migrations/*",
]

[tool.coverage.paths]
source = ["src"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if TYPE_CHECKING:",
    "if __name__ == .__main__.:",
    "@abstractmethod",
]
fail_under = 80
show_missing = true
skip_covered = true

[tool.coverage.html]
directory = "htmlcov"

[tool.coverage.xml]
output = "coverage.xml"
```

#### 執行覆蓋率
```bash
# 單元測試覆蓋率（多核 + 覆蓋率）
uv run pytest tests/unit -v --cov=src --cov-report=term-missing --cov-report=html

# 整合測試覆蓋率
uv run pytest tests/integration -v --cov=src --cov-report=xml --cov-append

# 全部測試 + 覆蓋率報告
uv run pytest --cov=src --cov-report=term-missing --cov-report=html --cov-report=xml
```

---

## 測試框架對照表

| 語言 | 單元測試 | 整合測試 | 覆蓋率 | 靜態分析 |
|------|----------|----------|--------|----------|
| **Python** | pytest | pytest + httpx | pytest-cov | mypy, ruff, bandit |
| **JavaScript** | Jest / Vitest | Supertest | c8 / istanbul | ESLint, TypeScript |
| **TypeScript** | Jest / Vitest | Supertest | c8 / istanbul | tsc --noEmit, ESLint |
| **Go** | testing | testing + testcontainers | go test -cover | golangci-lint |
| **Rust** | cargo test | cargo test | cargo-tarpaulin | clippy |

---

## CI 整合 Checklist

生成測試時應同步確認：

- [ ] `pyproject.toml` 包含完整測試配置
- [ ] `requirements-dev.txt` 或 `pyproject.toml` 包含測試依賴
- [ ] CI workflow 包含所有測試階段
- [ ] 覆蓋率門檻已設定（建議 ≥ 80%）
- [ ] 測試報告上傳至 CI artifacts

---

## 測試依賴 (Python)

```toml
# pyproject.toml [project.optional-dependencies] 或 requirements-dev.txt
[project.optional-dependencies]
dev = [
    # Testing - Core
    "pytest>=7.4.0",
    "pytest-cov>=4.1.0",
    "pytest-asyncio>=0.21.0",
    "pytest-xdist>=3.3.0",      # 平行測試
    "pytest-mock>=3.11.0",
    "pytest-timeout>=2.1.0",
    "httpx>=0.24.0",            # Async HTTP client for API tests
    "factory-boy>=3.3.0",       # Test data factories
    "faker>=19.0.0",            # Fake data generation

    # E2E Testing
    "playwright>=1.40.0",       # Browser automation
    "pytest-playwright>=0.4.0", # Playwright pytest plugin
    "locust>=2.20.0",           # Load testing (optional)

    # Static Analysis
    "mypy>=1.5.0",
    "ruff>=0.0.290",
    "bandit[toml]>=1.7.5",

    # Type stubs
    "types-requests",
    "types-python-dateutil",
]
```

---

## 輸出格式

```markdown
## 測試套件生成報告

### 📁 檔案結構
[生成的測試目錄結構]

### 📋 測試清單

#### 靜態分析
- [ ] mypy 類型檢查
- [ ] ruff linting
- [ ] bandit 安全掃描

#### 單元測試 (`tests/unit/`)
- ✅ 正常流程 (Happy Path)
- ✅ 邊界條件 (Edge Cases)
- ✅ 錯誤處理 (Error Handling)
- ✅ Null/None 處理

#### 整合測試 (`tests/integration/`)
- ✅ API 端點測試
- ✅ 資料庫操作測試
- ✅ 外部服務測試 (mocked)

#### E2E 測試 (`tests/e2e/`)
- ✅ 使用者旅程測試
- ✅ 關鍵流程驗證
- ✅ 跨瀏覽器測試 (Playwright)

### 📊 覆蓋率目標
- 單元測試：≥ 90%
- 整合測試：≥ 70%
- 總體覆蓋：≥ 80%

### ⚙️ 執行指令
[相關測試執行命令]
```
