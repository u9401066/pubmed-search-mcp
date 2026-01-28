# Active Context

> 📌 此檔案記錄當前工作焦點，每次工作階段開始時檢視，結束時更新。

## 🎯 當前焦點

- **v0.2.8 Research Timeline System** - Phase 13.1 MVP 實作完成

## 📝 進行中的變更

| 目錄/檔案 | 變更內容 |
|----------|----------|
| `domain/entities/timeline.py` | 新增 - TimelineEvent, ResearchTimeline, MilestoneType |
| `application/timeline/__init__.py` | 新增 - Timeline 模組入口 |
| `application/timeline/milestone_detector.py` | 新增 - 里程碑偵測器 (regex patterns) |
| `application/timeline/timeline_builder.py` | 新增 - 時間軸建構器 |
| `tools/timeline.py` | 新增 - 6 個 MCP 工具 |
| `tools/__init__.py` | 更新 - 註冊 timeline 工具 |
| `pyproject.toml` | 版本 0.2.7 → 0.2.8 |

## ✅ 已實現功能

**Research Timeline System (6 MCP Tools)**:
1. `build_research_timeline` - 從主題建構時間軸
2. `build_timeline_from_pmids` - 從 PMID 列表建構時間軸
3. `analyze_timeline_milestones` - 分析里程碑分佈
4. `get_timeline_visualization` - Mermaid/JSON 視覺化
5. `list_milestone_patterns` - 查看偵測模式
6. `compare_timelines` - 比較多個主題時間軸

**里程碑偵測能力**:
- FDA/EMA 監管批准
- 臨床試驗 Phase 1/2/3/4
- Meta-analysis, Systematic review
- Guidelines, Consensus
- Safety alerts, Label updates
- Landmark studies (by citation count)

## 💡 關鍵發現

- 使用 regex patterns 進行里程碑偵測效率高且透明
- TimelineEvent 使用 frozen=True 保證不可變性
- 可複用 citation_tree.py 的視覺化轉換器模式
- MilestoneType enum 提供清晰的類別定義

## 🔜 下一步

1. ⏳ 更新 README + Copilot instructions
2. ⏳ Git commit + push v0.2.8
3. ⏳ Phase 13.2 - NLP 增強偵測
4. ⏳ Paper 驗證實驗

---
*Last updated: 2026-01-28 - Research Timeline MVP 完成*