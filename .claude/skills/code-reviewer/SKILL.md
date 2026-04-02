---
name: code-reviewer
description: "Comprehensive code review checking quality, security, and best practices. Triggers: CR, review, 審查, 檢查, check, 看一下, PR, code review, 品質."
---

# 程式碼審查技能

## 描述
對程式碼進行全面審查，檢查品質、安全性和最佳實踐。

## 觸發條件
- 「review 這段程式碼」
- 「檢查程式碼」
- 「code review」

## 審查項目

### 1. 程式碼品質
- 命名是否清晰
- 函數長度是否合理（建議 < 50 行）
- 是否遵循 DRY 原則
- 複雜度是否過高

### 2. 安全性
- SQL 注入風險
- XSS 漏洞
- 敏感資料暴露
- 權限檢查

### 3. 效能
- N+1 查詢問題
- 不必要的迴圈
- 記憶體洩漏風險

### 4. 可維護性
- 註解是否充足
- 錯誤處理是否完整
- 測試覆蓋率

## 輸出格式

```
## 審查結果

### ✅ 優點
- ...

### ⚠️ 建議改進
- [嚴重程度] 問題描述
  - 位置：第 X 行
  - 建議：...

### 📊 評分
- 品質：X/10
- 安全：X/10
- 效能：X/10
```
