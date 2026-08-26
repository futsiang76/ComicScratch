## 项目结构

```
ComicScratch/
├── config.py                 # 配置和常量
├── secrets.py                # API密钥（本地，不提交）
├── AGENTS.md                 # Agent 工作规则
├── GUI_OPTIMIZATION_GUIDE.md # GUI优化说明
├── STRUCTURE.md              # 本文件
├── TODO.md                   # 待办清单
│
├── gui/                      # 图形界面（PyQt6）
│   ├── main_window.py        # 主窗口骨架（~166行，委托到下级模块）
│   ├── scan_tab.py           # 扫描标签页 UI
│   ├── scan_controller.py    # 扫描流程控制（启动/停止/完成回调）
│   ├── scan_thread.py        # 后台扫描线程
│   ├── results_tab.py        # 结果标签页容器
│   ├── results_table.py      # 结果表格填充
│   ├── edit_controller.py    # 编辑辅助（双击编辑/选中编辑）
│   ├── edit_dialog.py        # 编辑元数据对话框
│   ├── title_edit_dialog.py  # 逐卷编辑各卷信息对话框
│   ├── save_handler.py       # 批量保存（XML写入ZIP）
│   ├── xml_editor.py         # XML编辑器（编辑XML按钮 + 批量编辑）
│   ├── dialogs.py            # 独立对话框（XML存在提示）
│   ├── gui_dialogs.py        # GUI交互对话框 + DialogBridge
│   └── utils.py              # 共享工具函数
│
├── models/                   # 数据模型
│   ├── bangumi_fetcher.py    # Bangumi API封装（搜索/详情/数据提取）
│   ├── author_utils.py       # 作者名工具（清洗/拆分/匹配）
│   ├── database.py           # SQLite锁定状态缓存
│   └── edit_state.py         # 编辑状态数据模型
│
├── parsers/                  # 解析器
│   ├── folder_parser.py      # 文件夹名解析
│   └── file_parser.py        # 文件名解析（智能标题/卷数提取）
│
├── processors/               # 业务逻辑处理
│   ├── batch_processor.py    # 批量处理器（核心协调流程）
│   ├── folder_recursive_handler.py  # 文件夹递归扫描
│   ├── folder_processors.py  # re-export 中转（CLI 已移除）
│   ├── scan_processors.py    # 核心扫描逻辑
│   ├── result_builder.py     # 结果字典构建
│   ├── zip_handler.py        # FileHandler（文件添加/验证）
│   ├── zip_operations.py     # ZIP/CBZ操作函数 + XML内容对比
│   ├── seven_zip_handler.py  # 7-Zip命令行操作
│   ├── file_parser.py        # （保留，模块内部使用）
│   ├── xml_generator.py      # ComicInfo.xml 生成器
│   ├── xml_template_handler.py   # XML模板（Bangumi/本地/基础）
│   ├── search_handler.py     # Bangumi搜索
│   ├── selector_handler.py   # 结果选择器
│   ├── match_failure_handler.py  # 匹配失败处理
│   ├── timeout_handler.py    # 超时处理
│   ├── interaction_handler.py    # 用户交互
│   ├── irregular_folder_handler.py  # 不规则文件夹处理
│   ├── single_series_processor.py   # 单系列处理
│   ├── choice_handlers.py    # 用户选择逻辑
│   └── utils.py              # 共享处理工具
│
├── tests/                    # 测试
│   ├── test_bangumi_websearch.py
│   ├── test_dialogs.py
│   ├── test_edit_dialog.py
│   ├── test_main_window.py
│   ├── test_scan_tab.py
│   ├── test_settings.py
│   └── conftest.py
│
└── utils/                    # 旧工具目录（待清理）
```

### 关键架构说明

- **gui/ 负责 UI，processors/ 负责逻辑**，不跨层依赖
- 所有 XML 写入统一经过 `xml_generator.py:generate_comicinfo_xml()`
- 写入前通过 `zip_operations.py:_compare_xml_content()` 比较，内容一致则跳过
- 编辑流程：扫描 → 编辑元数据 → 保存（save_handler.py:save_changes）
- 所有代码文件 ≤450行，超标的下次改到时拆分
