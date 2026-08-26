# ComicScratch - Agent Operating Rules

## 项目定位（008 合并项目）

- **008 = 006 扫描 + 007 封面改图 的合并产物**（2026-08-06 拍板）
- 来源：
  - **006 ComicInfoScratcher**：漫画扫描（PyQt6 GUI + Bangumi/manhuagui/ComicVine 三源）→ 生成 ComicInfo.xml 写入 zip/cbz
  - **007 zipCoverCropper**：ZIP 封面改图（Tkinter UI + 智能封面检测 + 裁剪记忆系统）
- **原则：不动 006/007 现有代码**，008 独立演进；当前目录是完整可运行副本
- 当前阶段 **P1（骨架）**：只做「扫描 → 结果页」跑通，复用 006 全部核心（gui/processors/models/parsers/utils/tests）
- 后续阶段计划：
  - **P2 封面展示**：结果页/详情页展示 zip 内封面
  - **P3 裁剪交互**：封面裁剪 UI（继承 007 智能封面检测 + 裁剪能力）
  - **P4 记忆系统**：裁剪记忆 / 偏好记忆
- **P1 期间不要在 008 做 P2+ 的功能**，只聚焦扫描链路

## Token Optimization

- 优先节约 Token。
- 搜索优先于读取。读取优先于修改。修改优先于重构。
- 超过400行的文件，先搜索函数/类/关键字定位，再读取相关片段。
- 除非明确要求，否则不要打开整个文件。
- 复用已有上下文，不重复分析已明确内容，不反复读取同一文件。

## File Modification Strategy

- 最小必要修改，优先局部修改。
- 避免无意义重构、格式化整个文件、修改无关代码。

## Temporary Files

除非明确要求，不创建：分析报告、调研报告、GUI优化报告、Review报告、临时Markdown文件。
不创建一次后又删除的临时文件。

## Testing

仅在需要验证功能时创建测试代码。除非用户要求，不创建大量测试文件/项目/演示。
回归基线：`python3 -m pytest tests/ -q`（108 项，源自 006）。

## Git Workflow

- 提交前：1. git diff 2. 检查改动范围 3. 确认无无关修改
- Commit Message：Conventional Commits（feat:/fix:/refactor:/docs:/test:）
- 未经用户明确要求：不执行 git push、不执行 force push
- **secrets.py 含真实 API key：只用于本地运行，git 必须忽略，绝不 commit**
- Github Token 位置：H:\obsidian-vault\AI-Dev\Github-Tokens.md（.gitignore已排除）
  - Obsidian同步：futsiang76
  - VSCode编程：Futsiang（本项目使用此账号）

## Large Files（>400行）

| 文件 | 行数 | 关键类/函数 |
|------|------|------------|
| gui/edit_dialog.py | ~452 | EditDialog（元数据编辑对话框，含导航按钮） |
| processors/scan_processors.py | ~436 | 核心扫描逻辑 |
| processors/batch_processor.py | ~428 | BatchProcessor（批量扫描主流程） |
| processors/zip_operations.py | ~354 | add_file_to_zip, _compare_xml_content |
| gui/title_edit_dialog.py | ~354 | TitleEditDialog（逐卷编辑） |
| gui/gui_dialogs.py | ~351 | DialogBridge + 多结果/无结果对话框 |
| processors/single_series_processor.py | ~343 | 单系列处理 |
| models/bangumi_fetcher.py | ~341 | BangumiFetcher（API搜索/详情） |
| processors/match_failure_handler.py | ~335 | 匹配失败处理 |
| processors/folder_recursive_handler.py | ~333 | 文件夹递归扫描 |
| processors/selector_handler.py | ~321 | 结果选择器 |
| processors/xml_template_handler.py | ~304 | XML模板（Bangumi/本地/基础） |

操作策略：搜索定位→局部读取→局部修改。超标文件下次改到时顺便拆。

## General Principles

Search before Read. Read before Edit. Edit minimally. Preserve existing architecture. Minimize token consumption.

## 技术选型 License 原则（项目强制约束）

**本项目采用 GPL-3.0**（因依赖 PyQt6，见 README License 段）。

**引入任何新依赖前必须经过 John 确认**，重点是 License 对未来收费/商业化决策的影响：

- MIT / Apache-2.0 / BSD / LGPL → 宽松，未来可闭源收费，一般可直接用
- GPL / AGPL → 传染性，会强制整个项目保持开源 → **默认不引入，确需引入必须先说明影响，John 拍板**
- 不确定 License 的依赖 → 先查清楚再报，不擅自引入

执行者（coder / OpenHands / programmer / 小开）在本项目引入新依赖前，先自查 License 并写入变更简报；违反本原则的引入视为任务未完成。

## Project Quick Reference

- 管理文档 → `H:\obsidian-vault\ComicScratch\`
  - GUI优化说明.md — GUI设计说明
  - 人机联调问题汇总.md — 联调待办
  - 用户设置持久化：user_config.json（项目根，已 gitignore）为唯一用户层配置；出厂默认在 config.py DEFAULT_SETTINGS；scan_ignore_dirs 为扫描忽略目录通配符规则
- STRUCTURE.md — 本目录下的目录结构一览（其中 DECISIONS.md 条目一并移除）
- 来源项目：`F:\MyProject\006_ComicInfoScratcher\`、`F:\MyProject\007_zipCoverCropper\`（只读，不修改）

## 公共 assets

- 跨项目复用素材（GIF/图片/图标等）统一放 `H:/obsidian-vault/_assets/`（如 loading-gifs/ 下有小猫加载动画 loading_cat1.gif / loading_cat2.gif；png-icons/ 下有 45 个透明 PNG icon：alarm/calendar/email/HR/law/halalIndonesia 等，PPT/编程界面 UI 通用）
- 新项目需要动画/图片素材时，先查 `H:/obsidian-vault/_assets/` 再决定新建
