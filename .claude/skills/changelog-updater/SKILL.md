---
name: changelog-updater
description: Auto-update CHANGELOG.md following Keep a Changelog format. Triggers: CL, changelog, 變更, 版本, version, 更新日誌, whatsnew.
---

# CHANGELOG 更新技能

## 描述
根據變更內容自動更新 CHANGELOG.md。

## 觸發條件
- 「更新 changelog」
- 被 git-precommit 編排器調用

## 法規依據
- 憲法：CONSTITUTION.md 第 7 條
- 格式：Keep a Changelog

## 分類規則

| 類型 | 關鍵字偵測 |
|------|------------|
| Added | 新增、add、feat |
| Changed | 變更、修改、update、change |
| Deprecated | 棄用、deprecate |
| Removed | 移除、刪除、remove、delete |
| Fixed | 修復、fix、bug |
| Security | 安全、security、漏洞 |

## 版本號決定

```
MAJOR.MINOR.PATCH

MAJOR: 重大變更（Breaking Changes）
MINOR: 新功能（向下相容）
PATCH: Bug 修復
```

## 輸出格式

```
📋 CHANGELOG 更新

偵測到的變更：
  - [Added] 新增用戶認證模組
  - [Fixed] 修復登入問題

建議版本：0.2.0 (MINOR - 新功能)

預覽：
## [0.2.0] - 2025-12-15

### Added
- 新增用戶認證模組

### Fixed  
- 修復登入問題
```
