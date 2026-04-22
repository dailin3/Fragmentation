# Fragmentation 项目开发经验

## 项目概述

Fragmentation 是一个日记到知识片段的自动提取系统。目标是从原始日记中自动识别有价值的信息，分类到知识树中，生成结构化的知识笔记。

## 技术栈

- **语言**: Python 3.9
- **数据库**: SQLite (5 表：topics, subdomains, notes, diary_processed, clarification_sessions)
- **AI**: DeepSeek API (deepseek-chat)
- **接口**: MCP Server (FastMCP) + CLI (argparse)
- **模板**: Markdown 模板 + 知识树 Markdown 文件

## 开发过程

### 第一阶段：碎片化与聚合

最初系统是把日记拆成小片段（fragment），分散存在 `02-fragment/` 下。随着碎片增多，出现了两个问题：
1. 同主题的碎片分布在不同日期，无法关联
2. 短片段太多，信息密度不够

解决方案：
- 关键词白名单过滤（keep.txt，184 个关键词）
- AI 语义聚合：按关键词分组，让 DeepSeek 判断哪些片段可合并
- 聚合生成 gather 文件，无法聚合的移入 meaningless

结果：~866 个 fragment 最终聚合为 124 个 gather 文件，108 个移入无意义。

### 第二阶段：整体重构

旧系统痛点：
- 脚本零散（batch.py, phase2_merge.py, phase3_short.py, refine_keywords.py 等）
- 没有统一入口
- 知识树缺少主题/子领域概念
- 笔记扁平分布在 `02-fragment/`

重构目标：以**知识树**为核心，三层架构

```
上层: MCP Server (AI 接入) + CLI (人类调试)
中层: 7 个工具函数 (extract_knowledge, ask_clarification, add_subdomain 等)
底层: NoteStore, TreeStore, DiaryParser, Database
```

### 第三阶段：提取规则

用户编写了 `extract_rules.md`，定义了 7 类值得提取的信息和 5 类不应提取的内容，让 AI 有明确的提取标准。

## 学到的经验

### 1. API Key 加载的坑

`.env` 中正确配置了 API key，但 `os.environ.setdefault()` 不会覆盖系统环境中已有的值。如果环境中有一个无效的同名变量（如 3 个字符），它优先于 `.env` 中的有效值。

**修复**: 改用 `os.environ[key] = value` 直接覆盖。

**教训**: 配置加载不要用 `setdefault`，要用直接赋值。调试时注意区分"环境变量不存在"和"环境变量已存在但值错误"。

### 2. Python 版本兼容性

项目要求 Python 3.9 兼容。MCP SDK 需要 Python 3.10+。两个环境需要分开管理。

代码中避免使用 Python 3.10+ 的语法：
- 不用 `dict | None`，用 `Optional[dict]`
- 不用 `match/case`
- 不用 walrus operator `:=` 在 lambda 中

### 3. AI 提取质量的观察

- AI 分类准确率较高，能正确归入现有主题/子领域
- 负向规则基本遵守：空日记返回空结果
- 但部分笔记信息密度偏低（一句话成一条笔记）
- 单篇日记可能拆出 5-7 条笔记，有过度拆分倾向
- 改进方向：prompt 中强化信息密度要求，或增加单篇笔记数量上限

### 4. 架构设计的经验

- 模板化的笔记生成让 Obsidian 可以直接使用
- tree/ 目录文件作为知识树的单一真相来源，DB 是索引，冲突时 MD 优先
- CLI + MCP 双接口适合当前场景：人调试用 CLI，AI 用 MCP
- 澄清会话（ClarificationSession）让 AI 可以主动提问获取上下文

### 5. 数据库设计的经验

在第三阶段重构中，DB 从单纯的笔记缓存升级为完整的处理追踪系统：

- **diary_processed 表** 记录每篇日记的处理状态（success/needs_clarification/skipped/error），包括生成的笔记数量和关联的澄清会话 ID。这使得批量处理时可以跳过已处理的日记，也方便排查失败原因。
- **clarification_sessions 表** 替代了原来的 sessions.json，将澄清会话统一管理到数据库中。消除了 JSON 文件与 DB 两套存储的不一致性。
- **Tree 同步** 通过 `sync_topics_from_tree` 和 `sync_subdomains_from_tree` 方法保持 tree/ 目录和 DB 的一致性。Tree 操作（add_topic, add_subdomain）同时写文件 + 写 DB。
- **AI 请求重试** 内置 3 次重试，每次失败记录 error 级别日志。错误同时在 diary_processed 表中标记为 error 状态。
- **extract_knowledge 自动管理 DB** 函数内部自动创建/关闭 DB 连接，所有路径（success/needs_clarification/error）都记录处理状态。

### 6. 开发工具链

- Subagent-driven development 适合多任务并行执行
- 设计文档 + 实现计划的流程保证了开发的有序性
- 每个功能先写测试再实现（TDD）保证了代码质量
- 12/12 测试全部通过

### 7. Async 并发处理

- `ai_client.py` 同时提供同步 `call_ai()` 和异步 `call_ai_async()` 两个版本
- `extract_knowledge.py` 对应提供同步 `extract_knowledge()` 和异步 `extract_knowledge_async()`
- `batch-extract` CLI 命令使用 `asyncio.Semaphore(5)` 限制并发度，并发处理所有未处理日记
- MCP Server 的 `extract_knowledge_tool` 已改为 async def，天然支持并发请求
- SQLite 连接由每个协程独立创建，Semaphore 保护数据库不被并发写冲突

## 当前状态

- 406 篇原始日记
- 知识树：11 个主题，149 子领域
- 提取规则：7 类正向 + 5 类负向
- 10 篇测试提取：16 条笔记
- MCP Server 7 个工具（含 async），CLI 8 个命令（含 batch-extract）
- 46 个单元测试（unit/integration/smoke/edge）
- DB 5 表：topics, subdomains, notes, diary_processed, clarification_sessions
- AI 请求 3 次自动重试 + 错误日志
- 同步 + 异步双版本 AI 调用，batch-extract 支持 5 并发处理

## 待改进方向

1. **跨日记聚合** - 同主题笔记合并为长期知识总结
2. **去重机制** - 新日记与已有笔记重复时追加而非新建
3. **信息密度** - prompt 优化，避免一句话笔记
4. ~~批量处理~~ - 已完成：batch-extract 支持 5 并发
