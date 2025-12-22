# 子法：DDD 架構規範

> 父法：CONSTITUTION.md 第一章

## 第 1 條：目錄結構

```
src/
├── Domain/                    # 領域層（核心）
│   ├── Entities/              # 實體
│   ├── ValueObjects/          # 值物件
│   ├── Aggregates/            # 聚合根
│   ├── DomainServices/        # 領域服務
│   ├── DomainEvents/          # 領域事件
│   └── Repositories/          # Repository 介面（僅介面）
│
├── Application/               # 應用層
│   ├── UseCases/              # 用例
│   ├── DTOs/                  # 資料傳輸物件
│   ├── Services/              # 應用服務
│   └── Interfaces/            # 外部服務介面
│
├── Infrastructure/            # 基礎設施層
│   ├── Persistence/           # DAL 資料存取
│   │   ├── Repositories/      # Repository 實作
│   │   ├── DbContext/         # 資料庫上下文
│   │   └── Migrations/        # 資料遷移
│   ├── ExternalServices/      # 外部服務實作
│   └── Messaging/             # 訊息佇列
│
└── Presentation/              # 呈現層
    ├── API/                   # REST API
    ├── GraphQL/               # GraphQL（可選）
    └── CLI/                   # 命令列介面
```

## 第 2 條：依賴方向

```
Presentation → Application → Domain
                    ↓
              Infrastructure
```

- Domain 不依賴任何外層
- Infrastructure 實作 Domain 定義的介面

## 第 3 條：DAL 規範

### 3.1 Repository 介面（在 Domain 層）
```python
# Domain/Repositories/IUserRepository.py
class IUserRepository(ABC):
    @abstractmethod
    def get_by_id(self, id: UserId) -> Optional[User]: ...
    
    @abstractmethod
    def save(self, user: User) -> None: ...
```

### 3.2 Repository 實作（在 Infrastructure 層）
```python
# Infrastructure/Persistence/Repositories/UserRepository.py
class UserRepository(IUserRepository):
    def __init__(self, db_context: DbContext):
        self._db = db_context
    
    def get_by_id(self, id: UserId) -> Optional[User]:
        # 實際資料庫操作
        ...
```

## 第 4 條：命名慣例

| 類型 | 命名規則 | 範例 |
|------|----------|------|
| Entity | 名詞單數 | `User`, `Order` |
| Value Object | 描述性名詞 | `EmailAddress`, `Money` |
| Repository | `I{Entity}Repository` | `IUserRepository` |
| Use Case | 動詞 + 名詞 | `CreateOrder`, `GetUserById` |
| Domain Event | 過去式 | `OrderCreated`, `UserRegistered` |

---

## 第 5 條：模組化規範

> 依據憲法第 7.3 條「主動重構原則」訂定

### 5.1 檔案長度限制

| 類型 | 建議上限 | 硬性上限 | 超過時動作 |
|------|----------|----------|------------|
| 單一檔案 | 200 行 | 400 行 | 必須拆分 |
| 類別 (Class) | 150 行 | 300 行 | 提取子類別或組合 |
| 函數 (Function) | 30 行 | 50 行 | 提取私有方法 |
| 模組 (目錄) | 10 檔案 | 15 檔案 | 建立子模組 |

### 5.2 複雜度指標

```python
# 圈複雜度 (Cyclomatic Complexity)
# 建議 ≤ 10，硬性上限 15

# ❌ 過於複雜
def process_order(order):
    if order.status == "pending":
        if order.payment:
            if order.payment.verified:
                if order.items:
                    for item in order.items:
                        if item.in_stock:
                            # ... 更多巢狀
                            
# ✅ 重構後
def process_order(order):
    validate_order_status(order)
    verify_payment(order.payment)
    process_items(order.items)
```

### 5.3 模組拆分策略

當 Domain 模組過大時，按 **子領域** 拆分：

```
# Before: 單一 Domain
src/Domain/
├── Entities/
│   ├── User.py
│   ├── Order.py
│   ├── Product.py
│   ├── Payment.py
│   └── Shipping.py  # 太多了！

# After: 按子領域拆分
src/Domain/
├── Identity/           # 身份子領域
│   ├── Entities/
│   │   └── User.py
│   └── ValueObjects/
│       └── Email.py
│
├── Ordering/           # 訂單子領域
│   ├── Entities/
│   │   └── Order.py
│   ├── ValueObjects/
│   │   └── OrderStatus.py
│   └── DomainServices/
│       └── OrderPricing.py
│
├── Catalog/            # 商品目錄子領域
│   └── Entities/
│       └── Product.py
│
└── Shipping/           # 物流子領域
    └── Entities/
        └── Shipment.py
```

### 5.4 Application 層拆分

按 **功能群組** 或 **用例** 拆分：

```
src/Application/
├── Identity/           # 對應 Domain/Identity
│   ├── Commands/
│   │   ├── RegisterUser.py
│   │   └── ChangePassword.py
│   └── Queries/
│       └── GetUserProfile.py
│
├── Ordering/           # 對應 Domain/Ordering
│   ├── Commands/
│   │   ├── CreateOrder.py
│   │   └── CancelOrder.py
│   └── Queries/
│       └── GetOrderHistory.py
```

### 5.5 重構觸發條件

AI 應在以下情況 **主動建議** 重構：

| 觸發條件 | 建議動作 |
|----------|----------|
| 檔案超過 200 行 | 「這個檔案有點長，建議拆分成...」 |
| 函數超過 30 行 | 「這個函數可以提取出...」 |
| 圈複雜度 > 10 | 「這段邏輯較複雜，建議...」 |
| 重複程式碼 | 「發現重複模式，建議抽取為...」 |
| 跨層依賴 | 「這裡違反了 DDD 分層，應該...」 |

---

## 第 6 條：重構安全網

### 6.1 重構前必須

1. ✅ 確保有測試覆蓋（覆蓋率 ≥ 70%）
2. ✅ 執行現有測試確認通過
3. ✅ 記錄重構原因到 `decisionLog.md`

### 6.2 重構後必須

1. ✅ 執行全部測試
2. ✅ 檢查架構是否仍符合 DDD
3. ✅ 更新相關文檔
4. ✅ 更新 `memory-bank/architect.md`

### 6.3 重構模式參考

| 問題 | 重構模式 | 說明 |
|------|----------|------|
| 函數過長 | Extract Method | 提取私有方法 |
| 類別過大 | Extract Class | 提取新類別 |
| 重複程式碼 | Extract Superclass / Trait | 抽取共用邏輯 |
| 過多參數 | Introduce Parameter Object | 建立參數物件 |
| 條件過複雜 | Replace Conditional with Polymorphism | 用多態取代條件 |
| 跨層依賴 | Dependency Injection | 依賴注入 |
