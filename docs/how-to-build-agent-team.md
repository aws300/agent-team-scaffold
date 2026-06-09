# How to Build an Agent Team

> 基于 Anthropic 工程博客 2024–2026 三篇核心文章，系统整理多 Agent 团队的设计模式、工程实践与落地建议。
>
> **文档定位：** 一份可直接用于团队评审、Prompt 设计与架构决策的参考手册。
>
> **整理时间：** 2026-06-09

---

## TL;DR

- **多 Agent 团队不是 Agent 数量的简单堆叠**，而是不同角色之间的**关注点分离**与**对抗式协作**。
- **每个 Agent 团队都应至少包含一个"挑战者（Evaluator / Critic）"角色**，独立于生成者，专门挑刺。这是 Anthropic 工程团队 2026 年 3 月文章中明确论证的核心结论。
- 三种最有效的基础模式：**Orchestrator-Workers**（主从分发）、**Evaluator-Optimizer**（生成-评估循环）、**Parallelization with Voting**（并行 + 投票）。
- 多 Agent 系统在 Anthropic 内部研究评测中**性能比单 Agent 高 90.2%**，代价是 **token 使用量约 15 倍**。
- 团队中**让 Agent 评价自己的输出几乎总是失败的** —— 必须用独立 Context 的挑战者。

---

## 目录

- [1. 核心问题：为什么需要"挑战者"角色？](#1-核心问题为什么需要挑战者角色)
- [2. Anthropic 三篇核心文章解读](#2-anthropic-三篇核心文章解读)
  - [2.1 《Building Effective Agents》（2024-12-19）— 基础理论](#21-building-effective-agents20241219-基础理论)
  - [2.2 《How we built our multi-agent research system》（2025-06-13）— 工程实战](#22-how-we-built-our-multi-agent-research-system20250613-工程实战)
  - [2.3 《Harness design for long-running application development》（2026-03-24）— 挑战者模式深化](#23-harness-design-for-long-running-application-development20260324-挑战者模式深化)
- [3. 关键设计模式速查表](#3-关键设计模式速查表)
- [4. 让"挑战者"真正生效：8 条工程实践](#4-让挑战者真正生效8-条工程实践)
- [5. 多 Agent 团队的成本与边界](#5-多-agent-团队的成本与边界)
- [6. 决策清单：你的项目该不该上多 Agent？](#6-决策清单你的项目该不该上多-agent)
- [7. 参考文献](#7-参考文献)

---

## 1. 核心问题：为什么需要"挑战者"角色？

> **来自 Anthropic 工程博客（2026-03-24）：**
>
> > "When asked to evaluate work they've produced, agents tend to respond by confidently praising the work — even when, to a human observer, the quality is obviously mediocre."
> >
> > 中译：当让 Agent 评价自己产出时，它们倾向于自信地夸赞自己的工作 —— 即使在人类看来质量明显平庸。

这一结论解释了为什么"自我反思"在实践中往往失效：

| 现象 | 根因 |
|---|---|
| Agent 写完代码自评"质量优秀" | 同一 Context 内难以"反向思考" |
| 反思 prompt 收效有限 | 模型对自己的输出有 positive bias |
| 长任务越走越偏，自己却察觉不到 | Context 累积让批判视角被淹没 |

> **解决方案（Anthropic 原文）：**
>
> > "Tuning a standalone evaluator to be skeptical turns out to be far more tractable than making a generator critical of its own work."
> >
> > 中译：让一个独立的评估者保持挑剔，比让生成者对自己的工作保持苛刻，要可行得多得多。

**结论：** 在 Agent 团队中显式引入一个"挑战者"角色（独立 Context、独立 Prompt、独立工具），是性能突破的必需品而非可选项。

---

## 2. Anthropic 三篇核心文章解读

### 2.1 《Building Effective Agents》（2024-12-19）— 基础理论

📄 **原文：** <https://www.anthropic.com/engineering/building-effective-agents>

这是 Anthropic 所有 Agent 工程文章的奠基之作。**核心主张是反框架的**：

> "We've worked with dozens of teams building LLM agents across industries. Consistently, the most successful implementations use simple, composable patterns rather than complex frameworks."
>
> 中译：我们与数十个跨行业的 LLM Agent 团队合作过。始终如一的发现是：**最成功的实现使用的是简单、可组合的模式，而非复杂框架**。

#### 关键概念区分

| 术语 | 定义 |
|---|---|
| **Workflow** | LLM 与工具按**预定义代码路径**协作的系统 |
| **Agent** | LLM **动态决定流程和工具使用**的系统 |
| **Agentic System** | 上述两者的统称 |

> **何时不该用 Agent？**
>
> > "When building applications with LLMs, we recommend finding the simplest solution possible, and only increasing complexity when needed. This might mean not building agentic systems at all."
> >
> > Agent 用延迟和成本换取更好的任务表现，要权衡这笔交易是否值得。

#### 五种基础模式

##### 模式一：Prompt Chaining（提示链）

把任务拆成固定的连续步骤，每步处理上一步的输出，可在中间加程序化检查（gate）。

- **何时使用：** 任务可被清晰拆解为固定子任务时
- **典型场景：** 先写大纲 → 校验大纲 → 基于大纲写正文

##### 模式二：Routing（路由）

对输入分类后导向专门的下游处理。

- **何时使用：** 任务有明显类别区分，且分类可被准确执行
- **典型场景：**
  - 客服请求路由（一般咨询 / 退款 / 技术支持）
  - 简单问题路由到 Haiku，复杂问题路由到 Sonnet/Opus

##### 模式三：Parallelization（并行化）

两种变体：

- **Sectioning（分区）**：把任务拆成可独立运行的子任务
- **Voting（投票）**：同一任务跑多次得到多样输出再聚合

> **典型场景（原文）：**
>
> - **Sectioning：** 一个模型实例处理用户查询，另一个并行筛查内容是否不当
> - **Voting：** 多个不同 prompt 评审同一段代码寻找漏洞

##### 模式四：Orchestrator-Workers（主从分发）

中央 LLM 动态拆解任务、分发给 worker LLM、汇总结果。

> **与 Parallelization 的关键区别（原文）：**
>
> > "The key difference from parallelization is its flexibility — subtasks aren't pre-defined, but determined by the orchestrator based on the specific input."
> >
> > 子任务不是预定义的，而是由 orchestrator 根据具体输入决定。

- **典型场景：** 编码产品（每次任务影响的文件数和修改性质都不可预测）

##### 模式五：Evaluator-Optimizer（评估器-优化器）⭐ 挑战者模式的鼻祖

一个 LLM 生成响应，另一个 LLM 评估并反馈，形成循环。

> **何时使用（原文）：**
>
> > "Two signs of good fit are, first, that LLM responses can be demonstrably improved when a human articulates their feedback; and second, that the LLM can provide such feedback."
> >
> > 两个适配信号：(1) 当人类清晰反馈时 LLM 输出可以明显改善；(2) LLM 自己也能产出这种反馈。

- **典型场景：**
  - 文学翻译（评估器指出翻译捕捉不到的细微之处）
  - 复杂搜索（评估器决定是否需要更多搜索轮次）

---

### 2.2 《How we built our multi-agent research system》（2025-06-13）— 工程实战

📄 **原文：** <https://www.anthropic.com/engineering/multi-agent-research-system>

#### 关键性能数据

> "We found that a multi-agent system with Claude Opus 4 as the lead agent and Claude Sonnet 4 subagents outperformed single-agent Claude Opus 4 by 90.2% on our internal research eval."
>
> 多 Agent（Opus 4 主 + Sonnet 4 从）在 Anthropic 内部研究评测中比单 Agent Opus 4 **高出 90.2%**。

> "In our data, agents typically use about 4× more tokens than chat interactions, and multi-agent systems use about 15× more tokens than chats."
>
> Agent 比普通聊天用 token **多 4 倍**；多 Agent 比聊天**多 15 倍**。

#### 多 Agent 性能的归因

> "Three factors explained 95% of the performance variance in the BrowseComp evaluation. Token usage by itself explains 80% of the variance, with the number of tool calls and the model choice as the two other explanatory factors."
>
> 在 BrowseComp 测评上，**仅 token 用量本身就解释 80% 的性能差异**，工具调用次数和模型选择共同贡献剩余部分。

🔑 **言下之意：** 多 Agent 之所以有效，**很大程度上是因为它打破了单 Context 窗口的天花板**，把工作分给多个独立 Context 的 subagent，从而合法地花更多 token。

#### 架构总览

```
用户查询
   │
   ▼
┌─────────────────┐
│ LeadResearcher  │ ← 规划 + 决定 subagent 数量
└──────┬──────────┘
       │ spawn (并行)
       ▼
┌─────┬─────┬─────┐
│ Sub1│ Sub2│ Sub3│ ← 每个独立 Context、独立工具调用
└──┬──┴──┬──┴──┬──┘
   │     │     │
   └─────┴─────┘
       │ 汇报
       ▼
┌─────────────────┐
│ LeadResearcher  │ ← 综合 → 决定是否继续
└──────┬──────────┘
       │ 完成
       ▼
┌─────────────────┐
│ CitationAgent   │ ← 加引用
└──────┬──────────┘
       ▼
   最终结果
```

#### 8 条核心 Prompting 原则（原文逐条整理）

1. **Think like your agents** — 通过 Console 用真实 prompt 和工具运行模拟，逐步观察 Agent 行为，才能建立准确的心智模型。

2. **Teach the orchestrator how to delegate** — 每个 subagent 任务都需要明确：**目标、输出格式、工具/数据源指引、清晰的任务边界**。
   > **失败案例：** Lead 说"研究半导体短缺"，结果一个 subagent 研究 2021 汽车芯片危机，另两个重复研究 2025 供应链。

3. **Scale effort to query complexity** — 在 prompt 里嵌入明确的扩展规则：
   - 简单事实查询：1 个 Agent，3-10 次工具调用
   - 直接对比：2-4 个 subagent，每个 10-15 次调用
   - 复杂研究：10+ subagent，明确分工

4. **Tool design and selection are critical** — Agent-工具接口的重要性等同于人机接口。
   > "An agent searching the web for context that only exists in Slack is doomed from the start."

5. **Let agents improve themselves** — Claude 4 是优秀的 prompt 工程师。给它 prompt 和失败案例，它能诊断原因并提建议。Anthropic 用一个"工具测试 Agent"来重写 MCP 工具描述，**结果使后续 Agent 任务完成时间下降 40%**。

6. **Start wide, then narrow down** — 先广后深，模拟人类研究者。Agent 默认倾向写超长超具体的查询，要在 prompt 里反向引导。

7. **Guide the thinking process** — 用 extended thinking 模式作为可控的草稿板：lead 用思考来规划方法，subagent 用 interleaved thinking 评估工具结果。

8. **Parallel tool calling transforms speed and performance** — Anthropic 引入两层并行：
   - Lead 一次 spawn 3-5 个 subagent
   - 每个 subagent 一次调用 3+ 个工具
   - **复杂查询研究时间下降 90%**

#### 生产环境的硬核教训

> **Subagent 输出到文件系统（避免 "game of telephone"）：**
>
> > "Direct subagent outputs can bypass the main coordinator for certain types of results, improving both fidelity and performance."
> >
> > 让 subagent 把工作存到外部存储（如文件系统），只把轻量引用传回协调者。这避免了在对话历史里反复复制大块输出造成的信息损耗。

> **状态可观测性是必需品：**
>
> > "We monitor agent decision patterns and interaction structures — all without monitoring the contents of individual conversations, to maintain user privacy."
> >
> > 监控 Agent 的决策模式和交互结构，而不是对话内容本身（隐私考虑）。

> **同步执行的瓶颈：** 当前 lead Agent 同步等待 subagent 完成才推进，导致 lead 无法实时引导 subagent，subagent 之间也无法协调。异步执行会带来更高并行度，但状态一致性、错误传播是新挑战。

---

### 2.3 《Harness design for long-running application development》（2026-03-24）— 挑战者模式深化

📄 **原文：** <https://anthropic.com/engineering/harness-design-long-running-apps>

> 作者：Prithvi Rajasekaran（Anthropic Labs 团队）

这是迄今**最直接论证"挑战者"角色必要性**的文章，灵感来自 GAN（生成对抗网络）。

#### 两个根本洞察

##### 洞察一：自评失效是结构性问题

> "Agents tend to respond by confidently praising the work — even when, to a human observer, the quality is obviously mediocre. This problem is particularly pronounced for subjective tasks like design, where there is no binary check equivalent to a verifiable software test."

##### 洞察二：分离生成与评判远比"让生成者更挑剔"容易

> "Tuning a standalone evaluator to be skeptical turns out to be far more tractable than making a generator critical of its own work. And once that external feedback exists, the generator has something concrete to iterate against."

#### 三 Agent 架构

```
用户简短 prompt（1-4 句话）
       │
       ▼
   ┌─────────┐
   │ Planner │ ← 把简短 prompt 扩展成完整产品 spec
   └────┬────┘
        │
        ▼
   ┌─────────┐ ◄──── feedback ─────┐
   │Generator│                     │
   │（写代码）│                     │
   └────┬────┘                     │
        │ 完成 sprint              │
        ▼                          │
   ┌─────────┐                     │
   │Evaluator│ ─── 详细 critique ──┘
   │（挑刺者）│
   └─────────┘
```

#### 让"挑战者"工作的关键工程

##### 关键 1：把主观判断变成可打分的标准

Anthropic 在前端设计场景给 Evaluator 设了 **4 个评分维度**，并明确权重：

| 维度 | 含义 | 权重 |
|---|---|---|
| **Design quality** | 设计是否是连贯整体而非零件拼凑 | 高 |
| **Originality** | 是否有定制决策（vs 模板/AI 默认/库默认） | 高 |
| **Craft** | 排版、间距、对比度等技术执行 | 低（默认就达标） |
| **Functionality** | 可用性（独立于美学） | 低（默认就达标） |

> 原文加权理由：
>
> > "Claude already scored well on craft and functionality by default. But on design and originality, Claude often produced outputs that were bland at best. The criteria explicitly penalized highly generic 'AI slop' patterns."

##### 关键 2：给 Evaluator 真正的工具，让它"亲自体验"

> "I gave the evaluator the Playwright MCP, which let it interact with the live page directly before scoring each criterion and writing a detailed critique. The evaluator would navigate the page on its own, screenshotting and carefully studying the implementation before producing its assessment."

挑战者**必须能跑代码、点击 UI、查数据**，而不是只看代码静态文本。

##### 关键 3：用 few-shot 示例校准评估者

> "I calibrated the evaluator using few-shot examples with detailed score breakdowns. This ensured the evaluator's judgment aligned with my preferences, and reduced score drift across iterations."

##### 关键 4：硬阈值而非软建议

每个评分维度设硬性阈值。**任一维度不达标 → sprint 失败 → generator 拿到具体 bug 列表去修**。

##### 关键 5：迭代节奏

> "I ran 5 to 15 iterations per generation, with each iteration typically pushing the generator in a more distinctive direction as it responded to the evaluator's critique."

#### 真实失败案例：Evaluator 一开始也很糟

> "Out of the box, Claude is a poor QA agent. In early runs, I watched it identify legitimate issues, then talk itself into deciding they weren't a big deal and approve the work anyway. It also tended to test superficially, rather than probing edge cases."

**调优循环：** 读 evaluator 日志 → 找它判断与人类不一致的地方 → 更新 QA prompt → 反复。

#### 真实成果：retro game maker

同样的 prompt（"Create a 2D retro game maker..."）在两种架构下：

| 维度 | 单 Agent 运行 | 三 Agent 运行 |
|---|---|---|
| 计划展开 | 简单实现 | 16 个特性 / 10 个 sprint |
| Sprite 编辑器 | 简陋 | 干净的工具面板、调色板、缩放 |
| 实际能玩游戏吗？ | ❌ 角色不响应输入 | ✅ 可以玩 |
| 含 AI 辅助功能？ | ❌ | ✅ 内置 Claude 集成 |

#### 核心警句（值得贴在墙上）

> "Every component in a harness encodes an assumption about what the model can't do on its own, and those assumptions are worth stress testing — both because they may be incorrect, and because they can quickly go stale as models improve."
>
> 中译：架构里的每一个组件都隐含了一个"模型自己做不到 X"的假设。这些假设值得被压力测试 —— 既因为它们可能是错的，也因为它们随着模型升级会迅速过时。

---

## 3. 关键设计模式速查表

| 模式 | Anthropic 官方名称 | 适用场景 | 主要风险 |
|---|---|---|---|
| 顺序拆解 | Prompt Chaining | 任务可清晰拆成固定步骤 | 错误级联 |
| 分类路由 | Routing | 输入有明显类别 | 分类错误成本高 |
| 并行投票 | Parallelization (Voting) | 需要多视角验证 | token 成本 |
| 主从分发 | Orchestrator-Workers | 子任务数量/性质不可预测 | 协调复杂度 |
| **生成-评估循环** | **Evaluator-Optimizer** | **质量需要反复打磨** | **收敛慢、成本高** |
| 三角架构 | Planner + Generator + Evaluator | 长时间自主任务 | 工程复杂度大 |

---

## 4. 让"挑战者"真正生效：8 条工程实践

> 综合三篇 Anthropic 文章 + 实战经验

### ① 挑战者必须独立 Context

不能是同一个 Agent 切换 prompt 角色 —— 那会变成自我夸赞。**新开 session 或独立 subagent**。

### ② 写明确的、可量化的评分维度

不要问"这个好吗？"，要问"这个是否符合维度 1、维度 2、维度 3 的标准？"。每个维度给清晰定义和正反例。

### ③ 给挑战者真实工具

- 代码评审 → 给它跑测试、跑 linter、跑应用的能力
- UI 评审 → 给它 Playwright MCP，让它**真的点击页面**
- 数据评审 → 给它查询数据库的能力
- 文档评审 → 给它访问引用源的能力

### ④ Prompt 显式注入"挑剔"姿态

```text
You are a skeptical reviewer. Your job is to find what is wrong,
missing, or weak. Praise should be reserved for what genuinely deserves it.
Default to skepticism. List specific failures with line numbers and reproduction steps.
```

### ⑤ 用 Few-shot 示例校准

给 5-10 个"差工作 + 你期望的批评"配对，让 evaluator 对齐你的标准。

### ⑥ 用文件系统通信，避免 "game of telephone"

让 evaluator 把 critique 写到文件里，generator 读取并响应；避免在对话历史中反复复制大块文本。

### ⑦ 设硬阈值而非软建议

```text
Each criterion has a pass/fail threshold.
If ANY criterion fails, the sprint fails.
The generator must address every fail before resubmitting.
```

### ⑧ 加 tracing 和检查点

- 长任务必须有可观测性（OpenTelemetry / Langfuse / 自建）
- 在关键节点设人类干预检查点
- 监控 Agent 决策模式（不是对话内容）以保护隐私

---

## 5. 多 Agent 团队的成本与边界

### Token 成本（Anthropic 实测数据）

| 系统类型 | Token 用量（相对值）|
|---|---|
| 普通 Chat | 1× |
| 单 Agent（带工具） | ~4× |
| 多 Agent 系统 | ~15× |

> **经济学意义：**
>
> > "For economic viability, multi-agent systems require tasks where the value of the task is high enough to pay for the increased performance."
> >
> > 多 Agent 系统经济上能成立，前提是任务价值足够高，足以覆盖性能提升带来的成本。

### 不适合多 Agent 的场景（原文）

> "Some domains that require all agents to share the same context or involve many dependencies between agents are not a good fit for multi-agent systems today. For instance, most coding tasks involve fewer truly parallelizable tasks than research, and LLM agents are not yet great at coordinating and delegating to other agents in real time."

不适合：
- 所有 Agent 必须共享同一上下文的任务
- Agent 之间有大量实时依赖的任务
- 大多数编码任务（真正可并行的部分有限）

适合：
- 高价值的、需要广度搜索/探索的任务
- 信息量超过单 Context 窗口的任务
- 需要使用大量异质工具的任务

---

## 6. 决策清单：你的项目该不该上多 Agent？

按顺序回答以下问题：

- [ ] **任务单价值 ≥ token 成本的 15× 提升吗？**
  - 否 → 用单 Agent + 优化 prompt
- [ ] **任务有明显的并行子任务吗？**
  - 否 → 用单 Agent + 工具
- [ ] **质量评判是主观的或多维的吗？**
  - 是 → **必须加挑战者角色**
- [ ] **任务时长 > 1 小时吗？**
  - 是 → 加 planner 角色 + 检查点
- [ ] **失败的代价高吗？**
  - 是 → 加投票或多挑战者
- [ ] **你能写出明确的评分标准吗？**
  - 否 → 先做这个，否则 evaluator 不可能有效

---

## 7. 参考文献

### Anthropic 官方文章（按发表时间）

1. **Building Effective Agents** — Anthropic Engineering, 2024-12-19
   <https://www.anthropic.com/engineering/building-effective-agents>
   *提出 5 种基础模式，奠定了"简单 + 可组合 > 复杂框架"的设计哲学。*

2. **How we built our multi-agent research system** — Anthropic Engineering, 2025-06-13
   作者：Jeremy Hadfield, Barry Zhang, Kenneth Lien, Florian Scholz, Jeremy Fox, Daniel Ford
   <https://www.anthropic.com/engineering/multi-agent-research-system>
   *Research 功能的多 Agent 架构落地实录，含 8 条 prompting 原则。*

3. **Harness design for long-running application development** — Anthropic Engineering, 2026-03-24
   作者：Prithvi Rajasekaran (Anthropic Labs)
   <https://anthropic.com/engineering/harness-design-long-running-apps>
   *GAN 启发的 generator-evaluator 模式，论证"挑战者角色"的必要性。*

### 相关延伸阅读

- **Our framework for developing safe and trustworthy agents** — Anthropic, 2025-08
  <https://anthropic.com/news/our-framework-for-developing-safe-and-trustworthy-agents>

- **Building Effective AI Agents (Resources)** — Anthropic 资源页（含案例研究）
  <https://resources.anthropic.com/building-effective-ai-agents>

- **Anthropic Cookbook: Agent Patterns**
  <https://platform.claude.com/cookbook/patterns-agents-basic-workflows>

- **Model Context Protocol (MCP)**
  <https://www.anthropic.com/news/model-context-protocol>

### 第三方观察与佐证

- *Claude Code Ultra Plan's Multi-Agent Architecture: Three Explorers Plus One Critic* — MindStudio
- *Anthropic's Multi-Agent Research Architecture Explained* — The AI Engineer (Substack)
- *Claude Code Agent Teams* — paddo.dev, 2026-02

---

## 附录：可直接复用的"挑战者" Prompt 模板

```markdown
# Role: Skeptical Evaluator

You are a strict, skeptical reviewer. Your sole purpose is to find weaknesses,
gaps, and failures in the work submitted to you. You do NOT generate or fix
work — you only critique.

## Evaluation Criteria

For each criterion below, give:
1. A score (1-10)
2. Specific failures with file:line references or reproduction steps
3. Whether it passes the threshold (pass/fail)

### Criterion 1: <定义>
- Threshold: <硬阈值>
- Examples of failure: <反例>

### Criterion 2: <定义>
...

## Tools Available

- `run_tests`: 跑项目测试
- `playwright_navigate`: 在浏览器中实际交互
- `read_file`: 读取代码
- `query_db`: 查询数据库状态

## Output Format

```json
{
  "overall_verdict": "PASS" | "FAIL",
  "criteria": [
    {
      "name": "...",
      "score": 7,
      "passed": true,
      "findings": ["..."],
      "evidence": ["file.ts:123", "screenshot:..."]
    }
  ],
  "must_fix_before_resubmission": ["..."]
}
```

## Important

- Default to skepticism. Praise must be earned.
- Do NOT give the benefit of the doubt.
- If you find legitimate issues, DO NOT talk yourself out of them.
- Test edge cases, not just happy paths.
- Verify by actually running the code, not by reading it.
```

---

*文档维护：基于 Anthropic 官方工程博客整理。如 Anthropic 发布新文章请同步更新。*
