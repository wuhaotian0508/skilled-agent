# Claude Code 使用技巧

> 版本：2.1.71（基于官方文档，命令行标志适用于当前最新版）  
> 官方文档：https://docs.anthropic.com/en/docs/claude-code/cli-reference

---

## 一、基本命令

```bash
claude                        # 启动交互式会话
claude "解释这个项目"          # 带初始提示启动
claude -p "解释这个函数"       # 非交互模式，输出后退出（SDK 模式）
claude -c                     # 继续当前目录最近一次会话
claude -v                     # 查看版本号
claude update                 # 更新到最新版本
```

---

## 二、`--dangerously-skip-permissions` 详解

### 是什么

跳过所有工具使用的权限确认弹窗，让 Claude 无需每次询问即可执行命令（bash、文件读写等）。

### 使用方式

```bash
# 直接跳过所有权限
claude --dangerously-skip-permissions -c

# 配合初始提示直接运行
claude --dangerously-skip-permissions "重构整个 utils 模块"

# 非交互模式 + 跳过权限（用于脚本/CI）
claude -p --dangerously-skip-permissions "运行测试并修复所有报错"

# 推荐：设置 alias 避免反复输入
# 加入 ~/.bashrc 或 ~/.zshrc
alias clauded="claude --dangerously-skip-permissions"
```

### 与 `--allow-dangerously-skip-permissions` 的区别

```bash
# --dangerously-skip-permissions：立即激活，跳过所有权限
claude --dangerously-skip-permissions

# --allow-dangerously-skip-permissions：允许但不立即激活，可与 --permission-mode 组合
claude --permission-mode plan --allow-dangerously-skip-permissions
```

### 安全使用建议

1. **不要在包含敏感文件的目录使用**：API keys、生产配置、重要数据集
2. **使用 Docker 隔离环境**：
   ```bash
   docker run -it -v $(pwd):/workspace alpine bash
   # 在容器内安装并运行 claude --dangerously-skip-permissions
   ```
3. **先用 `~/.claude/settings.json` 预授权常用命令**，减少使用频率：
   ```json
   {
     "permissions": {
       "allow": [
         "Bash(git:*)", "Bash(python:*)", "Bash(npm:*)",
         "Bash(ls:*)", "Bash(grep:*)", "Bash(find:*)",
         "Write(*)", "Update(*:*)"
       ],
       "deny": []
     }
   }
   ```
4. **任务前先 git commit**，方便出错回滚
5. **任务范围要明确**：给 Claude 清晰的边界，避免 scope creep

### 风险说明

- Claude 可能删除或修改不在预期范围内的文件
- 可能清理被认为是"临时"的文件（包括数据集）
- 超出预期的 scope creep（尝试修改不相关的配置文件）

---

## 三、会话管理

### 继续和恢复会话

```bash
claude -c                          # 继续当前目录最近的会话
claude -c -p "检查类型错误"        # 非交互模式继续会话

claude -r "auth-refactor"          # 按名称恢复会话
claude -r "abc-123" "继续这个PR"   # 按 session ID 恢复并给出任务
claude --resume                    # 弹出交互式选择器选择历史会话

claude -n "feature-auth"           # 给当前会话命名（方便后续 resume）
```

### Fork 会话

```bash
# 从现有会话分叉，创建新 session ID（不修改原会话）
claude --resume auth-refactor --fork-session
```

### Git Worktree 并行会话

```bash
# 在隔离的 git worktree 中开启会话，互不干扰
claude -w feature-auth             # 自动创建 .claude/worktrees/feature-auth

# 同时在多个 worktree 中并行运行 Claude
claude -w fix-bug-123 &
claude -w add-feature-456 &
```

---

## 四、非交互/自动化模式（Print Mode）

```bash
# 基本 print 模式
claude -p "生成单元测试" 

# 管道输入
cat error.log | claude -p "分析这个错误"
cat main.py | claude -p "找出所有 bug"

# 控制输出格式
claude -p "query" --output-format text         # 纯文本（默认）
claude -p "query" --output-format json         # JSON 格式
claude -p "query" --output-format stream-json  # 流式 JSON

# 限制 token/费用/轮数
claude -p --max-budget-usd 2.00 "query"        # 最多花 2 美元
claude -p --max-turns 5 "query"                # 最多 5 轮对话

# 结构化 JSON 输出（按 schema 验证）
claude -p --json-schema '{"type":"object","properties":{"result":{"type":"string"}}}' "query"

# 极简启动（不加载 hooks/MCP/plugins，适合脚本）
claude --bare -p "query"
```

---

## 五、权限与工具控制

### 预授权特定工具

```bash
# 允许特定 git 命令无需确认
claude --allowedTools "Bash(git log *)" "Bash(git diff *)" "Read"

# 禁止某些工具
claude --disallowedTools "Bash(rm *)" "Edit"

# 只使用指定工具集
claude --tools "Bash,Edit,Read"   # 只允许这三类工具
claude --tools ""                  # 禁用所有工具（纯对话）
```

### Permission Mode

```bash
# Plan 模式：只分析和规划，不执行写操作（安全探索代码库）
claude --permission-mode plan

# 结合跳过权限
claude --permission-mode plan --allow-dangerously-skip-permissions
```

---

## 六、模型与性能配置

```bash
# 指定模型
claude --model claude-sonnet-4-6
claude --model sonnet    # 最新 sonnet 别名
claude --model opus      # 最新 opus 别名

# 设置思考深度（effort）
claude --effort low      # 快速响应
claude --effort medium   # 默认
claude --effort high     # 更深入思考
claude --effort max      # 最大（仅 Opus 4.6）

# 过载时自动 fallback 到备用模型
claude -p --fallback-model sonnet "query"

# Debug 模式（诊断问题）
claude --debug
claude --debug "api,mcp"    # 只过滤 api 和 mcp 相关日志
```

---

## 七、System Prompt 自定义

```bash
# 替换整个系统提示
claude --system-prompt "你是一个 Python 专家，只用 Python 回答"

# 从文件加载系统提示
claude --system-prompt-file ./my-prompt.txt

# 在默认提示基础上追加（推荐，保留原有能力）
claude --append-system-prompt "所有代码都要加中文注释"
claude --append-system-prompt-file ./style-rules.txt
```

---

## 八、多目录访问

```bash
# 让 Claude 可以访问额外目录
claude --add-dir ../shared-lib ../utils

# 同时访问多个项目目录
claude --add-dir /data/project-a /data/project-b
```

---

## 九、MCP（Model Context Protocol）集成

```bash
# 从配置文件加载 MCP servers
claude --mcp-config ./mcp.json

# 只使用指定配置的 MCP（忽略全局配置）
claude --strict-mcp-config --mcp-config ./mcp.json

# 使用 MCP 工具处理权限提示（非交互模式）
claude -p --permission-prompt-tool mcp_auth_tool "query"

# 管理 MCP servers
claude mcp
```

---

## 十、远程控制与协作

```bash
# 启动 Remote Control 服务端（从 claude.ai 或 Claude app 远程控制）
claude remote-control --name "My Project"

# 交互式会话 + 远程控制
claude --remote-control "My Project"

# 在本地终端继续 web 会话
claude --teleport

# 在 claude.ai 创建新的 web 会话
claude --remote "修复登录 bug"
```

---

## 十一、内置斜杠命令（交互模式）

在交互式 Claude Code 会话中使用：

| 命令 | 说明 |
|------|------|
| `/help` | 显示所有可用命令 |
| `/clear` | 清除对话历史 |
| `/resume` | 显示历史会话，选择恢复 |
| `/rename <name>` | 重命名当前会话 |
| `/compact` | 压缩对话历史节省 token |
| `/cost` | 显示当前会话消耗的 token 和费用 |
| `/model` | 查看或切换当前模型 |
| `/permissions` | 查看当前权限设置 |

---

## 十二、实用工作流

### 理解新代码库

```bash
cd /path/to/project
claude
# 然后在会话中：
# "给我一个这个代码库的整体概览"
# "主要的架构模式是什么？"
# "认证是怎么实现的？"
```

### 自动化修复+测试循环

```bash
claude -p --dangerously-skip-permissions \
  "运行 pytest，修复所有失败的测试，确保全部通过"
```

### 批量代码审查

```bash
git diff HEAD~5 | claude -p "审查这些改动，找出潜在问题"
```

### 定时任务（cron）

```bash
# 每天自动生成日报
0 18 * * * cd /project && claude -p --bare "总结今天的 git commits 并写成日报" > daily-report.md
```

### 管道处理

```bash
# 分析日志
tail -100 app.log | claude -p "这些日志里有什么问题？"

# 代码审查
cat *.py | claude -p "找出所有可能的安全漏洞"

# 生成文档
cat api.py | claude -p "为这个文件生成 API 文档，输出 Markdown"
```

---

## 十三、`~/.claude/settings.json` 配置

全局配置文件，对所有项目生效：

```json
{
  "model": "claude-sonnet-4-6",
  "permissions": {
    "allow": [
      "Bash(git:*)",
      "Bash(python:*)",
      "Bash(python3:*)",
      "Bash(npm:*)",
      "Bash(npx:*)",
      "Bash(ls:*)",
      "Bash(grep:*)",
      "Bash(find:*)",
      "Bash(curl:*)",
      "Bash(mkdir:*)",
      "Bash(touch:*)",
      "Bash(mv:*)",
      "Bash(cp:*)",
      "Bash(echo:*)",
      "Bash(cat:*)",
      "Bash(head:*)",
      "Bash(tail:*)",
      "Write(*)",
      "Update(*:*)"
    ],
    "deny": [
      "Bash(rm -rf *)"
    ]
  }
}
```

项目级配置放在 `<project>/.claude/settings.json`，覆盖全局配置。

---

## 十四、认证管理

```bash
claude auth login              # 登录 Anthropic 账号
claude auth login --console    # 用 API Key 方式登录（按用量计费）
claude auth login --sso        # SSO 登录（企业）
claude auth status             # 查看登录状态（JSON）
claude auth status --text      # 查看登录状态（可读文本）
claude auth logout             # 退出登录
```

---

## 十五、版本与更新

```bash
claude -v              # 查看当前版本
claude update          # 更新到最新版本
```

当前版本 2.1.71 需要通过 npm 安装：

```bash
npm install -g @anthropic-ai/claude-code
```
