# Fragmentation

日记到知识片段的自动提取系统。

## 架构

```
01-diary/           原始日记 (Markdown)
  └── 按日期命名，如 20250315.md

src/                源代码
  ├── cli.py        CLI 入口 (7 个命令)
  ├── mcp_server.py MCP Server (7 个工具)
  ├── config.py     配置
  ├── logic/        业务逻辑
  │   ├── extract_knowledge.py   核心提取
  │   ├── ask_clarification.py   澄清对话
  │   ├── add_subdomain.py       新增子领域
  │   ├── check_subdomain.py     子领域健康检查
  │   ├── check_note.py          笔记质量检查
  │   ├── query_tree.py          知识树查询
  │   └── tree_sync.py           Tree ↔ DB 同步
  └── storage/      存储层
      ├── db.py         SQLite 数据库
      ├── note_store.py 笔记文件写入
      ├── tree_store.py  知识树文件管理
      ├── diary_parser.py 日记解析
      ├── logger.py      日志
      └── schema.sql     数据库 Schema

02-notes/           提取后的知识笔记 (扁平目录)
  ├── tree/          知识树索引 (topic + subdomain 文件)
  └── *.md           按 {关键词}-{日期}.md 命名的笔记

fragments.db        SQLite 数据库 (topics, subdomains, notes, diary_processed)
```

## 安装

```bash
# 需要 Python 3.13+
uv sync
```

## 使用

### 提取单篇日记

```bash
uv run python -m src.cli extract-knowledge 01-diary/20250315.md
```

### 批量提取所有未处理的日记

```bash
uv run python -m src.cli batch-extract
# 遇到错误继续处理
uv run python -m src.cli batch-extract --skip-errors
```

批量处理完成后会显示详细结果：
- 成功/跳过/待澄清/错误的数量
- 跳过的日记列表（AI 请求创建的新 subdomain）
- 错误的日记列表及原因
- 待澄清的日记列表及 session ID

### 子领域管理

```bash
# 添加新子领域
uv run python -m src.cli add-subdomain "Haskell" "编程语言" "纯函数式编程语言"

# 检查子领域健康
uv run python -m src.cli check-subdomain "编程语言" "Python"
# 不传参数时检查全部
uv run python -m src.cli check-subdomain

# 检查笔记质量
uv run python -m src.cli check-note 02-notes/指针学习-2025-03-15.md
```

### 知识树查询

```bash
# 查询全部
uv run python -m src.cli query-tree

# 按主题查询
uv run python -m src.cli query-tree --topic "编程语言"

# 按子领域查询
uv run python -m src.cli query-tree --topic "编程语言" --subdomain "Python"
```

### Tree ↔ DB 同步

```bash
uv run python -m src.cli tree-sync
```

以 tree 文件为基准同步到数据库（冲突时 tree 优先）。

## AI 自动创建子领域

提取过程中，如果 AI 发现内容应该属于一个不存在的子领域，会自动创建：
1. AI 请求新 subdomain → 系统自动创建到知识树和数据库
2. 创建完成后自动重新提取该日记
3. 新的 subdomain 立即生效

## MCP Server

```bash
uv run python -m src.mcp_server
```

暴露 7 个工具给 AI 调用：
- `extract_knowledge_tool` — 从日记提取知识
- `ask_clarification_tool` — 处理澄清会话
- `add_subdomain_tool` — 添加子领域
- `check_subdomain_tool` — 检查子领域健康
- `check_note_tool` — 检查笔记质量
- `query_tree_tool` — 查询知识树
- `tree_sync_tool` — 同步 tree 与数据库

## 测试

```bash
uv run pytest tests/ -v
```

## 处理统计

查看当前处理进度：

```python
from src.storage.db import Database
db = Database()
print(db.get_processing_stats())
db.close()
# 输出: {'success': 403, 'skipped': 0, 'error': 1, 'needs_clarification': 2}
```
