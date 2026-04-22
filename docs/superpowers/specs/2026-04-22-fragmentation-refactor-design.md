# Fragmentation 重构设计文档

**日期**: 2026-04-22
**状态**: 待审批
**分支**: refactor-all-flows

## 背景

现有项目存在大量历史脚本（batch.py、phase2_merge.py、phase3_short.py、refine_keywords.py 等），结构零散、没有统一入口。旧 DB schema 缺少主题/子领域概念，笔记扁平分布在 02-fragment/。

重构目标：以**知识树**为核心，构建三层架构，让 AI 能自动从日记中提取有效信息、挂到知识树对应节点、并在需要时向用户提问获取上下文。

---

## 架构

```
┌─────────────────────────────────────────────┐
│           上层 (Interface)                    │
│  MCP Server (AI 接入)   CLI (人类调试)        │
│  7 个 tool 共享中层逻辑                        │
├───────────────────────────────────────────────┤
│           中层 (Knowledge Tree)               │
│  extract_knowledge  ask_clarification        │
│  add_subdomain      check_subdomain          │
│  check_note         query_tree               │
│  tree_sync                                   │
├───────────────────────────────────────────────┤
│           底层 (Storage)                      │
│  NoteStore  TreeStore  DiaryParser  AIClient  │
├───────────────────────────────────────────────┤
│           数据层                               │
│  01-diary/  02-notes/  tree.md               │
│  extract_rules.md  模板文件  fragments.db      │
└───────────────────────────────────────────────┘
```

---

## 数据库表设计

### topics
| 字段 | 类型 | 说明 |
|------|------|------|
| name | TEXT PK | 主题名，如 "技术学习" |
| description | TEXT | 主题介绍 |
| created_at | TEXT | 创建时间 |

### subdomains
| 字段 | 类型 | 说明 |
|------|------|------|
| name | TEXT PK | 子领域名，如 "C++" |
| topic | TEXT | 所属主题 |
| description | TEXT | 子领域介绍 |
| created_at | TEXT | 创建时间 |

### notes
| 字段 | 类型 | 说明 |
|------|------|------|
| filename | TEXT PK | 文件名 |
| topic | TEXT | 所属主题 |
| subdomain | TEXT | 所属子领域 |
| keyword | TEXT | 主关键词 |
| source | TEXT | 来源日记路径 |
| content | TEXT | 笔记正文 |
| file_path | TEXT | 02-notes/ 中的路径 |
| created_at | TEXT | 创建时间 |

---

## 文件结构

```
01-diary/                 原始日记（只读输入）
02-notes/                 生成的笔记（Obsidian 格式）
  └── {topic}/
        └── {subdomain}/
              └── {filename}.md
tree.md                   知识树 Markdown
extract_rules.md          用户定义"什么信息值得提取"

模板：
  templates/
    note.md               笔记模板
    subdomain.md          子领域介绍模板
    domain.md             领域介绍模板

代码：
  src/
    storage/              底层
    logic/                中层
    mcp_server.py         MCP 接口
    cli.py                CLI 接口
  tests/
```

### tree.md 结构

```markdown
# Knowledge Tree

## 技术学习
- 子领域: C++ — 面向对象编程语言，系统级开发...
- 子领域: Python — 脚本语言，数据处理...

## 认知与成长
- 子领域: 学习 — 学习方法、效率提升...
```

---

## 核心工作流

### extract_knowledge

```
1. 读取输入 Markdown（01-diary/xxx.md）
2. 读取 tree.md 获取知识树
3. 读取 extract_rules.md 获取提取规则
4. 发送 DeepSeek：日记 + 知识树 + 提取规则
5. AI 返回有效信息片段（含来源标注）、目标主题/子领域、关键词
6. 套用 note.md 模板生成笔记 → 写入 02-notes/{topic}/{subdomain}/
7. 如果需要澄清：返回问题列表，创建会话
8. 如果无法装入现有树：返回 add_subdomain 请求
```

### 模板内容

**note.md**：
```markdown
---
origin: "{{SOURCE_DATE}}"
topic: "{{TOPIC}}"
subdomain: "{{SUBDOMAIN}}"
keyword: "{{KEYWORD}}"
created: "{{NOW_DATE}}"
---

{{CONTENT}}
```

**subdomain.md**：
```markdown
---
topic: "{{TOPIC}}"
created: "{{NOW_DATE}}"
---

## 子领域介绍
{{DESCRIPTION}}
```

**domain.md**：
```markdown
---
created: "{{NOW_DATE}}"
---

## 主题介绍
{{DESCRIPTION}}
```

---

## MCP 工具定义

所有工具遵循 JSON-RPC 2.0 + inputSchema 格式。

| Tool | 输入 | 返回 |
|------|------|------|
| `extract_knowledge` | file_path (string) | 提取结果或澄清请求 |
| `ask_clarification` | session_id (string), answers (string[]) | 继续处理结果 |
| `add_subdomain` | name, topic, description | 审核结果 |
| `check_subdomain` | topic, subdomain | 问题列表 |
| `check_note` | file_path | 问题列表 |
| `query_tree` | topic, subdomain (optional) | 树结构/介绍 |
| `tree_sync` | 无 | 同步状态 |

### 示例：extract_knowledge

```json
{
  "name": "extract_knowledge",
  "description": "从指定的 Markdown 日记文件中提取有效信息，生成知识笔记并写入 02-notes/",
  "inputSchema": {
    "type": "object",
    "properties": {
      "file_path": {
        "type": "string",
        "description": "01-diary/ 中要处理的日记文件路径"
      }
    },
    "required": ["file_path"]
  }
}
```

---

## 会话管理

```python
class ClarificationSession:
    session_id: str
    original_file: str
    questions: list[str]
    answers: list[str]
    status: "pending" | "answered" | "completed"
```

extract_knowledge 发现需要澄清时返回 `"needs_clarification"` 状态 + 问题列表。调用者回答后通过 `ask_clarification` 继续。

---

## 日志

```
logs/
  extract.log      提取操作日志（成功/失败/澄清）
  tree_changes.log 知识树变更日志（新增/修改/删除）
  sessions.log     会话记录（问题与回答）
```

每次 extract_knowledge 执行写入 extract.log，包含：来源文件、提取结果、生成笔记路径。tree_sync 变更写入 tree_changes.log。

## 双链

双链仅用于元信息中标注归属关系：
- note 归属 subdomain
- subdomain 归属 domain

当前不加双链，后续统一添加。
