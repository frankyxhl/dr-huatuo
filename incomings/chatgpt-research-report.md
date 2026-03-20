# Python 好/差代码数据集与资源清单

## 研究边界与“好/差代码”信号类型

你想搜集的“好/差代码”，在公开数据里通常不是直接由人类给出“好/差”二分类，而是用一组可操作的**质量信号（signals）**来近似：例如“buggy/fixed 成对”“是否通过测试/评测（accepted/rejected）”“是否引入安全漏洞/是否被静态分析命中”“是否触发代码味道/反模式”“代码评审是否提出修改意见”等。不同信号对应不同使用场景：训练“修复”模型更适合 bug/fix 对；训练“质量分类/排序”更适合 accepted/rejected、review 评论强度、静态分析严重度等。citeturn33search0turn34search9turn19view1turn35view1turn6view0

为了让你后续“搜集起来”更好用，建议你把数据源按信号类型分层保存（例如：`patch_pairs/`、`judge_labels/`、`security/`、`smells/`、`reviews/`），并在元数据里至少保留：来源（repo/commit/issue）、许可证、构建/运行方式（容器或锁定依赖）、标签来源（人标/测试/静态分析/规则）。这类做法在可复现实验型基准（例如 BugsInPy、SWE-bench、BugSwarm）里非常常见。citeturn32view0turn36search10turn35view1turn35view2

## 真实缺陷与修复对数据集（buggy/fixed、patch、可复现测试）

这一类资源通常最接近“坏代码→好代码”的定义：同一问题的 buggy 版本与修复后的 fixed 版本成对出现，并尽量提供**能暴露 bug 的测试**或可复现环境。

### BugsInPy（你已列出，强烈建议保留为核心基准）

BugsInPy 由论文与工具链定义为一个面向 Python 的真实缺陷基准：包含 **493 个真实 bug、来自 17 个真实世界 Python 项目**，并配套命令行工具用于检出 buggy/fixed 版本和执行相关测试（以及覆盖率、变异测试等）。citeturn33search0turn32view0

```bash
git clone https://github.com/soarsmu/BugsInPy.git
```

### BugsInPy-MF（你已列出：多缺陷版本扩展）

BugsInPy-MF（bugsinpy-mf）给的是把原本“单缺陷版本”的 BugsInPy 扩展为“**多缺陷共存版本**”的一套脚本与数据发布，强调通过测试用例移植与故障定位映射来构建 multi-fault 数据集。它在 entity["organization","Zenodo","research repository"] 上也发布了可下载版本（示例：v1.0.0）。citeturn34search0turn34search8turn34search16

```bash
git clone https://github.com/DCallaz/bugsinpy-mf.git
```

### HaPy-Bug（你已列出：人标的 bug 修复提交与行级标注）

HaPy-Bug 的定位不是“可复现测试驱动的 bug benchmark”，而是“**人工标注的 bug 修复提交数据集**”：论文描述其包含 **793 个与 bug 修复相关的 Python 提交**，并且做到**逐行（line-level）由三位领域专家标注**，包括修改目的、行级变更信息与审阅者置信度等。对于你想做“更完善的质量信息搜集”，它的“人标语义维度”非常有价值。citeturn17search6

### PyBugHive（强补：可复现真实 bug + 测试 + patch）

PyBugHive 明确定位为“**手工验证、可复现的 Python 真实 bug 数据库**”，主页给出：初始版本包含 **149 个真实 bug、来自 11 个 Python 项目**；每条记录含 bug 报告摘要、对应 patch、能暴露该 bug 的测试用例以及环境/运行指令，并提供命令行接口。citeturn30search0turn30search2  
另外，它提供了“offline 版本”的分包发布（例如在 Zenodo 上的 offline dump）。citeturn30search3

### PyResBugs（强补：大规模 bug/fix 对 + 多级自然语言描述）

PyResBugs 的 entity["company","GitHub","code hosting platform"] 仓库说明其包含 **5007 个 residual Python bugs**，并与对应 fixed 版本配对，同时提供多层级自然语言描述；仓库标注为 MIT License。citeturn17search2turn17search5

### PyTraceBugs（强补：buggy/fixed 代码片段 + traceback/issue 信息）

PyTraceBugs 的 GitHub README 说明其面向缺陷预测/定位：从公开 GitHub 仓库抽取函数/方法级代码片段；稳定片段来自稳定代码，buggy 片段来自 bugfix commit/PR，并链接到 issue；数据分为 `buggy_dataset` 与 `stable_dataset`，并在表字段中提供 `before_merge`/`after_merge`、完整 traceback、异常类型、issue URL、bug 位置行号、以及基于 CWE 的 bug 类型等。它还给出一个可下载的压缩包链接，并声明 MIT license。citeturn31view0

> 这一类数据对“坏代码”的定义更贴近真实：不仅有修复对，还直接给出**运行时错误证据（traceback）**与 issue 语境，适合你想“尽可能多信息”地搜集。

### PyPiBugs（补充：PyPI bug 元数据，用于定位/修复研究复现）

entity["company","Microsoft","technology company"] 下载中心提供 PyPiBugs Dataset：一个压缩的 JSONL，包含用于某篇 NeurIPS 2021 研究评估的“Python Package Index bugs 元数据”，并注明版本与文件大小。它更偏“bug 元信息索引”，但对做“包生态 bug 统计/定位”很有用。citeturn30search23

### SWE-bench（强补：issue→PR 修复任务 + 单元测试验证）

SWE-bench 的官方描述是：从 **12 个流行 Python 仓库**中爬取并构建 **2,294 个任务实例**（issue 与对应 PR/commit 修复对），评测通过**在仓库环境里运行单元测试**验证修复结果。官方还提供多个子集（Lite/Verified/Multimodal/Multilingual 等）。citeturn36search10turn36search4turn36search1turn36search19  
如果你在做“真实工程修复”的训练/评测，SWE-bench 通常是 BugsInPy 之外最常被引用的 Python 向数据源之一。citeturn36search26

## 代码审查与“可接受/不可接受”信号数据集（review comment、no-comment）

这类资源的好处是：它们提供的“差”不一定是 bug，而是**可读性、可维护性、风格、工程规范**等维度上的不足，通常更贴近“代码质量”而非“功能正确性”。

### GitHub CodeReview 数据集（强补：带负样本的评审三元组）

`ronantakizawa/github-codereview`（entity["company","Hugging Face","ml platform"] 数据集卡片）给出了一个非常适合“好/差代码”任务的结构：  
它包含 37 种语言（含 Python），以 `source`（原始代码变更）、`comment`（review 评论）、`target`（修改后代码）形成正例三元组，并提供 “no comment / other comment / wrong code / unhelpful comment / buggy code” 等负例构造方式；同时说明其只使用 permissive licenses 的项目（如 MIT、Apache-2.0、BSD-3-Clause）。citeturn6view0

> 如果你的目标是训练“根据评审意见改代码”“识别不良改动/不合理评论”，这类结构化 review 数据通常比单纯 patch 对更直接。

## 安全漏洞与不安全代码资源（训练靶场与带单测提示集）

“差代码”里很重要的一支是“**安全不当实现**”。这一类资源通常可用于：漏洞修复、secure coding、静态分析引导的质量评分。

### PythonSecurityEval（提示→生成→静态分析→修补的基准）

论文《Can LLMs Patch Security Issues?》提出 PythonSecurityEval：从 entity["company","Stack Overflow","q&a platform"] 手工整理 **470 条自然语言 prompts**，每条 prompt 配一个 unit test，并使用 Bandit 对生成代码做安全问题检测；论文明确“代码与数据在 GitHub 提供”。citeturn18view0turn19view0  
该论文所指向的仓库里，`data/PythonSecurityEval/` 以编号目录组织样本，每个样本至少包含 `text.txt`（prompt）与 `unit_test.py`（测试）。citeturn20view0turn22view0turn24view0turn25view0turn26view0

PythonSecurityEval 及相关工作通常用到两个关键工具：Bandit（Python 安全静态分析）与 Pylint（代码质量/规范/潜在错误检查）。citeturn17search0turn17search7

### OWASP PyGoat（你已列出：故意带漏洞的 Python 应用）

entity["organization","OWASP","security nonprofit"] 的项目页说明：PyGoat 用 Python + Django 构建，用于学习测试与安全编码，包含 XSS、SQLi 等传统 Web 漏洞，并提供查看源码以定位漏洞点与修改加固。citeturn34search7  
同时存在多个相关实现仓库（例如 `adeyosemanputra/pygoat` 的 README 表明其是 intentionally vulnerable Django Web app，且是 MIT license）。citeturn34search3

> 这类“靶场型”仓库非常适合采集“有漏洞的坏代码片段”，并且你可以用修复提交把它们变成有监督的“漏洞修复对”。

（同类型补充）DjangoGoat 也是一个“故意脆弱的 Django 应用”，README 同样强调其包含 OWASP Top 10 类漏洞并用于教育。citeturn34search11

## 反模式、代码味道与静态分析标注资源

如果你要做“风格/可维护性”的“差代码”，这里的资源通常比 bug/fix 更直接，因为它们的“差”就是**反模式或 code smell**。

### Python Anti-Patterns（你已列出：结构化反模式，注意许可证限制）

`python-anti-patterns` 的仓库明确：内容以 **CC BY-NC-SA 4.0** 发布，允许非商业用途下自由使用与分发，并要求相同方式共享贡献。citeturn34search2  
这对“差代码模式归纳、反例库构建”很适合，但如果你后续要商用/闭源训练，需要特别注意 NC（非商业）与 SA（相同方式共享）的约束（建议你结合自身用途做合规评估）。citeturn34search2turn27search27

### PythonCodeSmellsDatasets（补充：PySmell 标注的 code smell CSV）

`PythonCodeSmellsDatasets` 仓库 README 声明其基于 PySmell 标注创建 Python code smell 数据集；仓库内 `Datasets/` 下至少提供 `LargeClass` 与 `LongMethod` 两类 smell，并以 CSV 文件形式发布。citeturn7view0turn11view0turn12view0turn13view0  
如果你需要“坏代码=某类 smell”的明确标签，这类 CSV 非常省事。

### 静态分析工具作为“可规模化标注器”

在“你要尽可能多搜集信息”的目标下，一个常见策略是：选取一批许可可用的 Python 代码语料，然后用静态分析工具批量打标签（例如 Bandit 的 CWE 映射、Pylint 的 Error/Warning/Refactor 等分组），把“命中规则”作为质量信号的一部分。Bandit 与 Pylint 本身分别定位为安全检查与代码质量/规范检查工具。citeturn17search0turn17search7

## 代码语料、索引与许可证注意事项（用于扩展采集）

当你把上述“强标签数据集”用作主干后，通常还会需要更大的 Python 语料来扩展覆盖面（然后再叠加静态分析、stars、review、运行测试等信号）。这一节给你几个“可直接拿来当底座”的来源与索引，并把许可证坑点说清楚。

### Project CodeNet（你已列出：Accepted/Rejected 信号的超大规模评测数据）

entity["company","IBM","technology company"] 的 Project CodeNet 在其 GitHub 主页与官方介绍中都强调其规模：约 **14 million** 代码样本，覆盖 **55+** 语言（含大量 Python），面向约 4000 个编程题（intended solutions）。citeturn34search5turn34search1turn34search17  
对应 NeurIPS 论文也给出规模描述：**14M 代码样本、约 500M 行、55 种语言**，并强调其带高质量标注。citeturn34search13turn34search9  
对你而言，CodeNet 的关键价值是它天然提供“**评测通过/不通过（accepted/rejected）**”这类非常强的质量信号（尤其适合做“好/差”分类或排序）。citeturn34search25turn34search9

### Bugs/修复任务的“可执行评测集”：FixEval（含 Python 预处理数据）

FixEval 仓库说明它构建了面向竞赛编程 bug fixing 的基准，强调“buggy submission 与对应 fixes”，并提供执行型评测（test suite）；README 明确给出**可下载的预处理 Python 数据**入口与数据组织结构（`data/python/...`），同时其流程依赖 Project CodeNet 元数据和测试用例下载。citeturn29view0

### CodeSearchNet（大规模 Python 函数与文档注释对）

CodeSearchNet 的论文与仓库将其定义为用于语义代码搜索的基准语料：包含约 6M 函数，覆盖多语言（含 Python），并提供“函数与文档注释”的配对与挑战集。citeturn28search30turn28search3  
其仓库资源目录还专门提供了“licenses.pkl”等文件以记录语料来源许可证信息。citeturn28search22  
它没有直接的“好/差标签”，但非常适合做“代码语料底座 + 叠加静态分析/评审/测试信号”。citeturn28search3turn28search22

### ETH Py150 / ETH Py150 Open（可再分发的 Python 代码语料）

entity["organization","ETH Zürich","swiss university"] 的 Py150 页面描述：提供一个约 150k 的 Python 数据集（以 parsed AST 等形式），来自 GitHub 仓库，并做去重、去 fork、过滤不可解析与疑似混淆文件等；同时强调仅使用 permissive / non-viral licenses（如 MIT/BSD/Apache）。citeturn28search1  
`eth_py150_open` 则是一个可再分发子集的实现仓库。citeturn28search0  
同样，它偏“干净语料”，需要你再叠加质量信号来切分“好/差”。citeturn28search1turn28search0

### 软件缺陷数据集索引（你已列出：defect-datasets）

defect-datasets 站点本身就是一个面向论文《From Bugs to Benchmarks: A Comprehensive Survey of Software Defect Datasets》的可检索表格索引，可按特征标签过滤数据集；它也直接收录了 PyBugHive 等 Python 相关缺陷数据集条目。citeturn30search9turn30search0

### Stack Overflow / Stack Exchange 内容的许可证与数据获取注意

你提到“Stack Overflow CC BY-SA 内容——质量参差不齐的代码”。这里最关键的是合规与可追溯：  
entity["company","Stack Exchange","q&a network"] 帮助中心明确说明：公开用户贡献内容按 Creative Commons Attribution-ShareAlike 授权（并按时间段区分 CC BY-SA 2.5/3.0/4.0）。citeturn27search6turn27search27  
历史上官方也提供全站数据 dump（每站点一个压缩包，含 Posts/Users/Votes/Comments 等表）。citeturn27search16  
如果你要把其中的代码块抽出来当“好/差代码”，建议你至少保留：原帖/答案 ID、作者、链接与分数（score/accepted）等，以满足 attribution 与可追踪要求（尤其是 CC BY-SA 的署名与相同方式共享要求）。citeturn27search6turn27search27  
另外，数据 dump 的分发方式在近年存在变动与争议讨论；你在做长期数据采集时，建议同时保留“抓取日期与获取路径”，避免后续复现困难。citeturn27search1turn27search7turn27search19

### 许可证与可商用性的一眼判别清单

你当前清单里最容易踩坑的两类许可证是：

- **CC BY-NC-SA 4.0**（例如 Python Anti-Patterns）：明确包含 Non-Commercial 限制。citeturn34search2  
- **CC BY-NC-ND 4.0**（例如 PyBugHive 论文页脚所示许可）：ND（禁止演绎）会对“改造/再发布衍生数据”非常不友好，尤其如果你要把样本加工成新格式或训练集再发布，需要特别谨慎。citeturn30search2  
相比之下，MIT/Apache/BSD 这类 permissive license 通常更适合做可再分发的数据工程底座（例如 PyResBugs、PyTraceBugs、FixEval 代码/仓库层面均声明 MIT）。citeturn17search2turn31view0turn29view0  

> 注：许可证合规牵涉具体使用方式与再分发方式；上面是“常见风险点提示”，不是法律意见（如要商用，建议以项目法务/律师意见为准）。citeturn34search2turn30search2turn27search27