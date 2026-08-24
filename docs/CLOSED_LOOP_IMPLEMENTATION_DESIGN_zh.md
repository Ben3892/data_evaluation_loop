# 数据合成、质量过滤、数据评估与数据任务优化闭环实施设计

> 状态：Data-only MVP Implementation
> 版本：0.2
> 日期：2026-08-24
> 目标仓库：data_synthetic_pipeline
> 当前边界：仅实现数据侧闭环；不修改或优化训练代码

## 0. 文档结论

当前只实现一条数据侧闭环：

~~~text
知识或任务规格
  → 独立的数学合成 / 数据改写 / 代码任务生成
  → 确定性质量检查
  → 小模型打标
  → 大模型 Judge
  → 数据内在评估
  → 大模型提出 Prompt 候选或生成任务采样比例候选
  → 固定夹具/金标验证后人工晋级新任务版本
~~~

数学合成、改写、代码生成和质量过滤均是可单独调用、可单独重放的任务，不强制串成一条工作流。训练框架、训练超参数、训练代码修复、训练期动态采样和下游模型训练均不属于当前闭环；数据版本以后可以由任意训练系统消费，但本仓库不控制该训练过程。

两条闭环都以 capability slice（能力切片）作为连接评估侧和数据侧的公共分析坐标。能力切片至少包含背景条件、任务类型、求解操作、输出约束四类标签，并绑定 Taxonomy Version 和稳定 slice_id，延续本仓库 [README](../README.md) 已有的方法论。评估标签到数据标签允许多对多映射，不能把它简化成无版本的数据库 Join Key。

大模型不能直接覆盖生产 Prompt，也不能修改 Python 实现。它只生成受 `editable_fields` 限制的版本化 `PromptProposal`，或受 `min_weight`、`max_weight`、`max_delta` 限制的生成任务 `MixtureProposal`。候选通过冻结夹具/金标门禁后，才可人工晋级为新的任务定义。

## 1. 当前代码基线

### 1.1 data_synthetic_pipeline

当前已具备数据侧 MVP：标准库实现的 LLM Adapter、版本化任务注册表、知识抽取、三类独立生成任务、两级质量过滤、数据内在评估、Prompt/生成比例候选、CLI、离线夹具和单元测试。README 已有的能力切片、数学操作组合诊断和 Weak(F) 方法仍作为后续扩展的数据侧理论基础。

### 1.2 与训练仓库的边界

`distillation_research` 不在当前实施范围。本阶段不读取其评估反馈来自动改训练配置，不修改其中的 `training.py`、`checkpointing.py`、Sampler 或数据 Provider，也不把训练故障当作本闭环要修复的问题。当前唯一允许的边界是：未来可把已接受的公开数据资产导出给训练系统；这种单向消费不构成本仓库的闭环步骤。

## 2. 目标、非目标与成功标准

### 2.1 目标

系统需要支持：

1. 数学知识点合成
   - 建立可版本化的知识点目录。
   - 按知识点、前置关系、求解操作组合、难度和输出形式生成题目与解答。
   - 对可验证题目执行符号、数值或约束验证。

2. 数据改写
   - 风格改写。
   - 表达和场景多样化。
   - 多语言翻译或本地化。
   - 保持原问题语义、答案和测试不变。

3. 类 KodCode 的代码任务生成
   - 生成 question-solution-test 三元组。
   - 支持多种任务来源、难度、算法或 API 领域。
   - 使用编译、单测、属性测试和 Test-based Rejection Sampling 验证。

4. 数学和代码质量过滤
   - 确定性规则和执行验证。
   - 小模型多维标签和置信度。
   - 大模型结构化 Judge。
   - 固定金标集上的阈值校准、误杀和漏放审计。

5. 数据内在评估
   - 正确性、覆盖度、多样性、难度、重复率、污染率和成本等内在指标。
   - 按数学、代码、语言、风格、难度和拒绝原因聚合。
   - 对过滤器统计通过率、误杀、漏放和校准指标。

6. 闭环优化
   - 大模型根据错误模式提出生成 Prompt、过滤 Prompt 或 MixturePlanningProposal 候选。
   - 受约束算法根据数据质量缺口提出各生成任务调用预算比例候选。
   - 通过固定验证门禁晋级、灰度和回滚。

### 2.2 非目标

P0 不包含：

- 在单次正式训练中无门禁地实时改变数据文件。
- 让生成模型兼任唯一 Judge 和唯一优化器。
- 用 Judge 高分替代数学验证或代码执行。
- 仅凭 validation loss 自动宣称采样策略具有因果收益。
- 在宿主机直接执行未信任代码。
- 一开始就引入复杂的分布式工作流平台。
- 修改、修复或自动调参任何训练代码。
- 根据训练 loss 或 Benchmark 分数在线改变训练采样比例。

### 2.3 成功标准

一个最小可用闭环应满足：

- 对已持久化的模型响应或请求缓存，相同配置可以重放且产物哈希一致。远程模型的 Live Rerun 可能非确定，必须保存原响应；Live Rerun 作为新 Attempt 和新 generation_id 记录，不能伪装成位级复现。
- 任意数据样本都能追溯到父样本、生成请求、Prompt、模型和过滤决策。
- 数学可验证子集必须通过确定性验证；代码子集必须在隔离环境通过声明的测试。
- 小模型和大模型 Judge 在冻结金标集上完成校准，并输出分类质量和校准误差。
- 每次 Prompt 或比例变更都有基线、候选、假设、指标、成本、回滚条件和晋级记录。
- 每个 Prompt 或生成比例候选都保留基线、假设、约束、数据指标和回滚信息；冻结测试集决定是否建议人工晋级。

## 3. 总体架构

~~~mermaid
flowchart LR
    A[知识源/种子数据/失败切片] --> B[Knowledge Catalog 与 Task Blueprint]
    B --> C1[数学合成]
    B --> C3[代码任务合成]
    C1 --> D[候选数据与完整 Lineage]
    C3 --> D
    D --> E1[Schema/安全/去重/泄漏规则]
    E1 --> E2[数学验证器/代码沙箱]
    E2 --> E3[小模型标签]
    E3 --> E4[大模型 Judge]
    E4 --> F[不可变 Dataset Version]
    F --> R[RewriteSpec: 风格/多样性/语言]
    R --> C2[改写候选]
    C2 --> D
    F --> G1[数据内在评估]
    G1 --> I[EvaluationReport]
    I --> J1[Prompt Optimizer]
    I --> J2[LLM Mixture Planner + 受约束 Optimizer]
    J1 --> K[OptimizationProposal]
    J2 --> K
    K --> L[固定集 A/B、保护门禁、成本门禁]
    L -->|通过| B
    L -->|拒绝| M[保留基线并记录反例]
~~~

设计上需要严格区分四种对象：

| 对象 | 含义 | 是否可直接覆盖 |
|---|---|---|
| PromptVersion | 某类生成、标签或 Judge 的完整模板与输出 Schema | 否，只新增版本 |
| CandidatePoolVersion | 固定输入与生成配置产生、尚未应用某个过滤策略的候选快照 | 否，不可变 |
| FilterPolicyVersion | 规则、验证器、小模型、Judge Prompt 和阈值的组合 | 否，只新增版本 |
| DatasetVersion | CandidatePoolVersion 经指定 FilterPolicyVersion 产生的已接受数据快照 | 否，不可变 |
| EvaluationReport | 某候选池或数据版本在固定数据评估协议下的结果 | 否，只追加 |
| OptimizationProposal | 对 Prompt、阈值或比例的候选修改 | 否，需门禁后生成新版本 |

## 4. 工程目录设计

建议采用以下目录。generated 和 artifacts 目录默认加入 .gitignore，只提交 Schema、配置模板、Prompt、代码和小型测试夹具。

~~~text
data_synthetic_pipeline/
├── pyproject.toml
├── README.md
├── configs/
│   ├── pipeline/
│   ├── models/
│   ├── filters/
│   ├── evaluation/
│   └── mixtures/
├── prompts/
│   ├── math_generator/
│   ├── rewriter/
│   ├── code_generator/
│   ├── small_labeler/
│   ├── llm_judge/
│   └── prompt_optimizer/
├── schemas/
│   ├── sample.schema.json
│   ├── dataset_manifest.schema.json
│   ├── evaluation_report.schema.json
│   └── optimization_proposal.schema.json
├── data_synthetic_pipeline/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── ids.py
│   ├── utils.py
│   ├── knowledge/
│   │   ├── catalog.py
│   │   ├── extraction.py
│   │   └── sampling.py
│   ├── llm/
│   │   ├── base.py
│   │   ├── compatible_client.py
│   │   ├── retry.py
│   │   └── cache.py
│   ├── synthesis/
│   │   ├── math.py
│   │   ├── rewrite.py
│   │   └── code.py
│   ├── filtering/
│   │   ├── pipeline.py
│   │   ├── rules.py
│   │   ├── dedup.py
│   │   ├── leakage.py
│   │   ├── math_verifier.py
│   │   ├── code_sandbox.py
│   │   ├── small_labeler.py
│   │   ├── llm_judge.py
│   │   └── calibration.py
│   ├── evaluation/
│   │   ├── intrinsic.py
│   │   ├── capability_slices.py
│   │   ├── downstream.py
│   │   └── statistics.py
│   ├── optimization/
│   │   ├── error_analysis.py
│   │   ├── prompt_optimizer.py
│   │   ├── mixture_optimizer.py
│   │   └── promotion.py
│   ├── orchestration/
│   │   ├── controller.py
│   │   └── stages.py
│   ├── storage/
│   │   ├── jsonl.py
│   │   ├── parquet.py
│   │   ├── manifest.py
│   │   └── event_log.py
│   └── adapters/
│       ├── training_export.py
│       └── distillation_research.py
├── tests/
│   ├── unit/
│   ├── contract/
│   ├── integration/
│   ├── golden/
│   └── fixtures/
└── docs/
~~~

首版编排可以使用本地 CLI 加 Stage 状态机。只有当任务量、失败恢复和多机资源调度确实成为瓶颈时，再接入 Ray、Airflow、Argo 或其他平台。

## 5. 核心数据协议

### 5.1 Materialized Sample View

底层事实拆成四类：不可变 CandidateRecord、GenerationAttempt、追加式 StageEvent，以及由事件折叠得到的 MaterializedSampleView。下面 JSON 是供分析、导出和调试使用的物化视图，不是允许原地修改的事实表。任务特有字段放入 payload；推荐主存储使用 Parquet，调试和跨系统交换使用 JSONL。

~~~json
{
  "schema_version": "1.0.0",
  "sample_id": "sha256:...",
  "candidate_id": "sha256:...",
  "generation_id": "sha256:...",
  "lineage_group_id": "sha256:...",
  "content_hash": "sha256:...",
  "semantic_cluster_id": "cluster:...",
  "parent_ids": ["sha256:..."],
  "run_id": "run_20260824_001",
  "split": "train",
  "lifecycle_status": "JUDGED",
  "base_task_type": "math",
  "generation_mode": "from_knowledge",
  "transformations": [],
  "domain": "math.algebra",
  "language": "zh-CN",
  "style": "competition_concise",
  "capability_slice": {
    "taxonomy_version": "capability_taxonomy:v3",
    "slice_id": "slice:sha256:...",
    "background_conditions": ["symbolic_notation"],
    "task_type": "formal_math",
    "solving_operations": [
      "equation_formulation",
      "constraint_tracking"
    ],
    "output_constraints": {
      "answer_form": "integer",
      "exactness": "exact",
      "explanation_required": true
    },
    "difficulty_target": 3
  },
  "payload": {
    "instruction": "...",
    "response": "...",
    "reference_answer": "...",
    "knowledge_points": ["math.algebra.linear_equation"],
    "starter_code": null,
    "public_tests": [],
    "private_test_set_ref": null,
    "private_test_set_hash": null
  },
  "generation": {
    "source_ids": ["kp:math.algebra.linear_equation:v3"],
    "generator_model": "provider/model@revision",
    "prompt_id": "math_generator:v4",
    "prompt_hash": "sha256:...",
    "decoding": {
      "temperature": 0.8,
      "top_p": 0.95,
      "seed": 42
    },
    "attempt": 1,
    "request_id": "...",
    "server_model_revision": "...",
    "raw_response_ref": "object://...",
    "raw_response_hash": "sha256:...",
    "input_tokens": 0,
    "output_tokens": 0,
    "estimated_cost": 0.0
  },
  "quality": {
    "rule_results": [],
    "verification": {},
    "small_model": {},
    "llm_judge": {},
    "quality_score": null,
    "quality_tier": null,
    "decision": "PENDING",
    "reject_reasons": []
  },
  "provenance": {
    "license": "internal-approved",
    "source_uri": null,
    "source_hash": "sha256:...",
    "created_at": "2026-08-24T00:00:00Z"
  }
}
~~~

底层对象职责：

| 对象 | 关键字段 | 写入规则 |
|---|---|---|
| CandidateRecord | candidate_id、Blueprint、规范化内容、parent_ids、lineage_group_id | 创建后不可改 |
| GenerationAttempt | generation_id、candidate_id、Prompt/模型/解码、原始响应引用和哈希 | 每次请求或 Live Rerun 新增 |
| StageEvent | event_id、candidate_id、stage、policy_version、decision、result_ref、timestamp | 只追加 |
| MaterializedSampleView | 上述对象折叠后的当前状态和质量摘要 | 可重建，不作为唯一事实源 |

### 5.2 ID、Lineage 与幂等

- candidate_id：标识固定 TaskBlueprint 和内容候选；在过滤策略之间保持稳定，允许在同一 CandidatePoolVersion 上做过滤 Prompt A/B。
- sample_id：由 Schema 版本、base_task_type、generation_mode、规范化内容和父链路哈希生成。重复执行同一输入不会产生新逻辑样本。
- generation_id：包含 Prompt、模型 Revision、采样参数、Seed 和 Attempt，用来区分同一 Blueprint 的不同候选。
- content_hash：仅用于精确去重，不包含模型和运行元数据。
- semantic_cluster_id：由 Embedding 或 MinHash/LSH 聚类产生，用于近重复控制。
- lineage_group_id：将父样本、全部改写、修复候选和语义等价派生数据绑定为一个分组。数据划分先按 lineage_group_id、来源组和 semantic_cluster_id 完成，同组样本不得跨 train/dev/test/holdout。
- 所有阶段只追加事件，不原地覆盖上游结果。最新状态由事件折叠得到。
- 默认 replay 读取已保存响应；显式 live-replay 才重新请求远程模型，并自动增加 Attempt。

### 5.3 DatasetManifest

每个可训练数据版本必须保存：

- dataset_version、父版本和创建时间。
- candidate_pool_version 和 filter_policy_version；过滤器 A/B 必须冻结 CandidatePoolVersion，不能同时混入重新生成的数据。
- 输入源、Schema 版本、Prompt ID、模型 Revision 和过滤配置哈希。
- 总样本数、有效 Token 数和 Shard 校验和。
- 按 base_task_type、generation_mode、transformation、domain、knowledge point、operation、language、style、difficulty、quality tier 的分布。
- 接受率、拒绝原因分布、重复率、污染率和估算成本。
- train/dev/test 划分规则和 Benchmark 排除清单。
- tokenizer、revision、chat template hash、vocab hash。
- sample_id 到 shard/offset 的 Sidecar 索引。
- 对应的 EvaluationReport 和晋级记录。

### 5.4 状态机

~~~text
RAW
 → SPEC_READY
 → GENERATED
 → RULE_PASSED
 → VERIFIED
 → LABELED
 → JUDGED
 → ACCEPTED | REJECTED | HUMAN_REVIEW
 → EXPORTED
 → TRAINED
 → EVALUATED
~~~

任何硬验证失败都不能被后续分数覆盖。重试会产生新的 generation_id，但保留原失败事件。Judge 的 suggested_fix 或人工修复必须形成带 parent_id 的新候选，并重新经过 F0 至 F6，不能原地把 REJECTED 改成 ACCEPTED。

## 6. 数据合成设计

### 6.1 数学知识点合成

#### 6.1.1 Knowledge Catalog

知识点不是自由文本列表，而是版本化图结构：

~~~yaml
id: math.algebra.linear_equation
name_zh: 一元一次方程
name_en: linear equation in one variable
domain_path:
  - math
  - algebra
prerequisites:
  - math.arithmetic.fraction
concepts:
  - equality
  - unknown
allowed_operations:
  - equation_formulation
  - symbolic_transformation
  - constraint_tracking
difficulty_range: [1, 4]
canonical_examples: []
source_refs: []
version: 3
~~~

knowledge/extraction.py 负责把课程大纲、经过许可的教材目录、内部知识库或人工表格转成候选节点。流程为：

1. 分段和来源记录。
2. 候选知识点、定义、前置关系和别名抽取。
3. 规则标准化与跨语言别名合并。
4. 小模型分类到固定 Taxonomy。
5. 大模型仅处理低置信或冲突关系。
6. 人工抽检后发布 KnowledgeCatalogVersion。

不要直接把 Benchmark 题目写入知识目录。Benchmark 只能提供能力标签和排除用指纹，避免训练污染。

#### 6.1.2 Blueprint 先行

生成题目之前先采样 TaskBlueprint：

- 1 至 3 个知识点及其前置约束。
- 单操作、操作对或操作三元组。
- 难度目标和预期解题步数区间。
- 语言、场景、风格和输出形式。
- 可验证方式：symbolic、numeric、constraint、proof_judge。
- 答案类型、值域、唯一性和边界条件。
- 禁止模式，例如与保留 Benchmark 高相似、答案泄漏、缺少必要条件。

Blueprint 的好处是可以区分“没有生成到目标能力”与“生成后被过滤掉”，并能独立计算计划分布和实际分布之间的偏差。

#### 6.1.3 生成与验证

推荐流程：

1. 参数或答案先采样：先确定满足约束的数值、表达式或结论。
2. 问题生成：基于参数、知识点和操作组合生成自然语言题目。
3. 独立求解：使用不同 Prompt，最好使用不同模型或禁用第一次解答上下文，重新求解。
4. 确定性验证：
   - 代数等价：规范化加 SymPy 等价或随机安全点代入。
   - 数值答案：高精度计算、单位和容差检查。
   - 方程或约束：重新代入所有条件，检查唯一性和边界。
   - 组合问题：小规模穷举或独立程序验证。
5. 一致性检查：题目条件、推理步骤、最终答案、输出格式一致。
6. 难度回标：小模型或代理求解器多次作答，估计 Pass 率，而不是完全相信生成时声明的难度。

证明题如果没有可靠形式化验证，应单独标记 verification_level=judge_only，不能与机器可验证题使用同一质量层级。

数学表达式同样是不可信输入。解析器必须使用函数和符号 Allowlist，禁止对候选文本直接 eval；每次化简、求解和随机代入设置 CPU、内存和墙钟限制。随机代入要避开奇点，并在显式定义域和假设下比较，超时或结论不确定时转 REVIEW，不能默认等价。

#### 6.1.4 覆盖策略

数学采样以以下优先级组合：

- 基础覆盖：每个知识点和单操作的最小预算。
- 诊断补弱：高 Weak(F) 的操作对和三元组。
- 边界覆盖：约束跟踪、边界情形、反例和异常条件。
- 探索预算：未匹配或低支持切片的均匀采样。

同一模板只替换数字不算有效多样性，应由 semantic_cluster_id 和 Blueprint 模板 ID 设置每簇上限。

### 6.2 风格、多样性和语言改写

改写必须是“带不变量的派生任务”，不能当作无约束生成。

改写后 base_task_type 保持父样本的 math/code/general，generation_mode 设为 rewrite，并在 transformations 中记录 style、diversity、language 等操作。父样本和所有派生样本共享 lineage_group_id；改写候选必须重新通过与父任务类型相同的验证和过滤链。

#### 6.2.1 三类独立操作

| 操作 | 示例维度 | 必须保持 |
|---|---|---|
| style | 教材式、竞赛简洁、苏格拉底式、面试式、结构化说明 | 任务目标、约束和答案 |
| diversity | 场景、叙述顺序、变量名、句法、输入形式 | 数学关系或程序语义 |
| language | zh-CN、en、目标语本地化 | 专有名词、公式、代码、测试和答案 |

单个改写任务只声明一个 primary transformation，其他变化作为 secondary transformations 记录，便于归因。

#### 6.2.2 改写流程

1. 读取已验证的父样本。
2. 生成 RewriteSpec，声明要改变和禁止改变的内容。
3. 生成改写候选。
4. 抽取候选中的约束、实体、数值和预期输出，与父样本做结构化对齐。
5. 数学题重新求解；代码题复用私有测试并重新执行。
6. 进行 Round-trip 检查：从改写文本恢复 TaskSpec，与父 TaskSpec 比较。
7. 近重复和语言质量检查。
8. 保存 parent_id 和 transformation 元数据。

翻译时不应翻译代码标识符、API 名称、数学符号、文件名或测试常量。若语言变化导致答案格式变化，必须由 OutputConstraint 显式声明。

### 6.3 类 KodCode 的代码任务生成

KodCode 的核心是多来源生成 question-solution-test 三元组、自验证、对困难任务增加尝试，以及验证后再做风格转换和基于测试的拒绝采样。本项目采用相同的工程思想，但使用自己的 Schema、许可证规则和执行沙箱。

#### 6.3.1 任务来源

- Zero-shot TaskBlueprint。
- 经过许可的人工任务规格，只提取抽象技能和约束，不复制受限文本。
- 经过许可的代码片段，反向合成行为规格。
- 技术文档或 API Schema，生成库使用任务。
- 模型评估失败的能力切片，只使用标签和错误模式，不把保留题目直接交给生成器。

#### 6.3.2 CodeBlueprint

至少包含：

- programming_language 和版本。
- task_family：algorithm、data_structure、debugging、API_usage、data_processing 等。
- 输入输出协议、函数签名或 stdin/stdout 形式。
- 算法和知识标签。
- 时间和空间约束。
- 正常、边界、异常和随机测试计划。
- 允许依赖和禁止系统能力。
- 难度目标、参考复杂度和预期陷阱。

#### 6.3.3 生成链路

~~~text
CodeBlueprint
 → 问题规格
 → 参考解候选 N 个
 → 单测候选 M 组
 → 规格静态检查
 → 编译/运行
 → 参考解交叉验证
 → 属性测试/差分测试/变异测试
 → Test-based Reject Sampling
 → 验证后的风格改写
~~~

测试集分为：

- public tests：帮助理解规格。
- private deterministic tests：用于过滤和评估。
- property-based tests：覆盖广泛输入。
- metamorphic tests：验证输入变换后的关系。
- differential tests：多个独立实现或可信 Oracle 对比。
- mutation tests：人为注入常见错误，检查测试是否能杀死错误实现。

只有“参考解通过”并不足以证明测试有效。至少需要检查错误实现或变异体的检出率、边界覆盖、超时和 Flaky 行为。

private tests 及其答案只保存在受控验证资产中，不写入普通 SFT 样本。生成器默认无权读取已发布私有测试；验证执行器可读取，Judge 只读取执行摘要，获授权的审计人员按需读取。若用于 RL，只向训练侧暴露受限执行接口和结果，不把私有测试正文交给待训练模型。

#### 6.3.4 执行安全

所有候选代码必须在隔离执行器运行：

- 默认禁网。
- 只读基础文件系统和一次性临时目录。
- CPU、内存、磁盘、进程数、输出大小和墙钟时间限制。
- 固定语言和依赖 Allowlist。
- 禁止访问宿主凭据、设备、Docker Socket 和工作区。
- 记录镜像 Digest、运行命令、退出码、资源使用和测试哈希。
- 超时、越界、非确定性或沙箱异常一律不自动接受。

## 7. 质量过滤设计

### 7.1 分层漏斗

过滤按成本从低到高执行：

| 阶段 | 核心检查 | 失败动作 |
|---|---|---|
| F0 Schema/来源 | 必填字段、类型、许可证、敏感信息、来源哈希 | REJECT |
| F1 静态规则 | 长度、语言、乱码、占位符、答案泄漏、格式 | REJECT 或 REVIEW |
| F2 去重/污染 | 精确、MinHash、Embedding、Benchmark 指纹 | REJECT 或隔离 |
| F3 任务验证 | 数学等价/约束；代码编译/测试/沙箱 | REJECT |
| F4 小模型标签 | 正确性风险、清晰度、难度、风格、异常类型 | LABEL |
| F5 大模型 Judge | 结构化 Rubric、证据、修复建议 | JUDGE |
| F6 决策器 | 硬门禁、校准阈值、质量分层、抽检 | ACCEPT/REJECT/REVIEW |

P0 为了建立校准数据，所有通过 F3 的候选都执行 F4 和 F5。积累足够金标后，P1 可以使用级联：

- 小模型高置信坏样本直接拒绝，但持续随机抽检。
- 小模型高置信好样本只在机器可验证通过时快速接受，并保留一定比例送大 Judge。
- 中间区间、冲突样本和高价值稀有切片送大 Judge。

级联启用条件是“小模型对关键错误的召回率”达到门槛，而不是总体准确率看起来较高。

### 7.2 确定性规则

通用规则：

- UTF-8、字段长度、空值和结构化输出解析。
- 语言识别与声明语言一致。
- 系统 Prompt、API 错误、模型拒答或占位符泄漏检测。
- 指令中无无意答案泄漏。
- 精确重复、近重复、同模板数字替换簇控制。
- 与 train/dev/test Benchmark 指纹的 N-gram、AST 和 Embedding 相似度。
- PII、凭据、许可证和来源策略检查。

数学规则：

- LaTeX 或数学表达式可解析。
- 最终答案存在且形式符合 OutputConstraint。
- 方程、数值、单位、范围、唯一性和边界验证。
- 题目条件无矛盾，解答使用的条件都在题目中。

代码规则：

- 语言、入口、函数签名和 I/O 协议一致。
- AST/编译检查。
- 禁止导入、文件、网络和系统调用规则。
- 测试通过、资源限制通过、重复执行稳定。
- 复杂度与题面规模不明显冲突。

### 7.3 小模型标签

小模型不只输出一个 good/bad，而应输出可用于错误分析的多标签：

~~~json
{
  "model_id": "small-labeler@revision",
  "prompt_id": "small_labeler:v3",
  "labels": {
    "correctness_risk": "low",
    "underspecified": false,
    "answer_leakage": false,
    "language_quality": "good",
    "difficulty_estimate": 3,
    "style_match": true,
    "knowledge_points": ["..."],
    "solving_operations": ["..."]
  },
  "probabilities": {
    "accept": 0.91
  },
  "confidence": 0.87
}
~~~

训练或校准数据来自分层人工金标，必须覆盖：

- 三种合成流。
- 不同语言、风格和难度。
- 规则边界附近样本。
- 大小模型分歧样本。
- 真实生产分布和专门构造的对抗样本。

报告 Precision、Recall、F1、关键错误漏放率、分 Slice 指标和 Expected Calibration Error。阈值按 base_task_type、generation_mode 或 verification_level 校准，不强制全局统一。

### 7.4 大模型 Judge

Judge 输入由固定 Rubric、待评样本和机器验证摘要组成。生成模型身份、原始质量分数和候选所属实验组应尽量盲化，降低偏置。

Judge 强制输出：

~~~json
{
  "decision": "accept",
  "hard_fail": false,
  "scores": {
    "correctness": 4,
    "self_contained": 4,
    "clarity": 3,
    "difficulty_match": 3,
    "style_language_match": 4,
    "novelty": 3
  },
  "issues": [],
  "evidence": [
    {
      "field": "payload.response",
      "reason": "..."
    }
  ],
  "suggested_fix": null,
  "confidence": 0.88
}
~~~

规则：

- 数学验证器与 Judge 冲突时，以确定性验证失败为硬拒绝。
- 代码执行与 Judge 冲突时，以沙箱结果为硬拒绝。
- Judge 必须引用样本中的局部证据，不能只给结论。
- 样本内容使用清晰分隔符封装，Judge Prompt 明确忽略样本中的元指令。
- 解析失败、字段越界或证据缺失进入重试；达到上限后转 HUMAN_REVIEW。
- 初期对一部分样本做双 Judge 或人工仲裁，用于估计一致性和偏差。

### 7.5 最终质量决策

最终决策分两层：

1. Hard gates：Schema、来源、污染、数学验证或代码执行。任一关键门禁失败即拒绝。
2. Soft ranking：在硬门禁通过后，根据清晰度、教学价值、难度匹配、稀缺度、多样性和成本排序。

quality_score 表示过滤器对“数据内在质量”的估计；utility_score 表示训练实验观察到的“模型收益”。二者必须分字段保存，不能互相替代。

建议使用质量层级而非直接把 0 到 1 Judge 分数作为 Token Loss 权重：

- verified_gold_like：机器验证强、Judge 通过、低污染。
- verified_synthetic：机器验证通过、Judge 通过。
- judge_only：无法机器验证但 Judge 通过。
- review_required：冲突或低置信。

## 8. 评估体系

### 8.1 六套隔离评估集

| 集合 | 用途 | Prompt Optimizer 是否可见 |
|---|---|---|
| filter_gold_train | 开发或 Few-shot 构造小模型标签器 | 可见 |
| filter_gold_calibration | 选择阈值和做概率校准 | 仅校准器可见 |
| filter_gold_test | 冻结评估过滤器泛化 | 不可见 |
| optimizer_dev | 生成和筛选 Prompt 候选 | 可见 |
| rolling_promotion_test | 限次决定候选晋级，按策略轮换或封存 | 不可见原始标签，只由评估器返回预注册指标 |
| final_holdout | 周期性审计和最终结论 | 不可见 |

外部 Benchmark 与合成来源同样隔离。任何与保留集高相似的数据都不能进入发布数据版本。

### 8.2 数据内在指标

质量和产量：

- 各 Stage 通过率、最终 Yield、每千条有效样本成本和延迟。
- 机器可验证率、数学验证通过率、代码编译和测试通过率。
- 小模型、大模型和人工之间的一致性。
- 关键错误的 Precision、Recall、FNR 和校准误差。

覆盖与多样性：

- knowledge point、operation、operation pair/triple 覆盖率。
- task/domain/language/style/difficulty/output constraint 分布。
- Blueprint 计划分布与最终接受分布的 KL/JS 距离。
- 精确重复率、近重复率、语义簇有效样本数和每簇最大占比。
- Benchmark 最近邻相似度和污染拒绝率。

难度：

- 代理模型多次采样 Pass 率。
- 解答步数、程序复杂度、测试覆盖和变异检出率。
- 目标难度与回标难度的混淆矩阵。

### 8.3 未来可选：下游模型指标（不在当前闭环）

本节仅定义未来由外部训练/评估系统回传结果时的兼容格式。当前实现、门禁和优化器不依赖这些指标，也不会据此修改训练代码。

至少包含：

- 数学：GSM8K、MATH/MATH-500、AIME 类困难集及内部知识点切片。
- 代码：HumanEval、MBPP、BigCodeBench 或内部可执行集。
- 通用保护：知识、阅读理解、常识、格式遵循和多语言集合。
- 生成长度、停止行为、答案抽取成功率和格式违规率。

Pass@K 与 Pass@1 要同时报告。对每题生成 n 个样本，其中 c 个正确时，可使用无偏估计：

~~~text
Pass@k = 1 - C(n-c, k) / C(n, k)
~~~

所有指标按 capability slice 展开，至少包含：

- background condition。
- task type。
- solving operation 单项、操作对和操作三元组。
- output constraint。
- language、style、difficulty 和数据来源。

### 8.4 未来可选：训练实验统计与归因

- 尽量做同一初始化或基座 Checkpoint、同 Token 预算、同训练配置、仅改变一个预注册干预的对照。比例实验把满足约束的完整 Vector 视为一个干预，不能单独修改某个 share 后再把其他 share 的被动变化忽略。
- 使用配对 Bootstrap 或题目级重采样给出 95% 置信区间。
- 关键配置运行多个 Seed；同一配置的 Seed 共享 experiment_id。
- 报告绝对差、相对差、样本量和置信区间，不只报告聚合均分。
- 目标切片改善与加入的数据切片对应可作为机制一致性证据，但不是单独的因果证明；通用保护集不能出现超过容忍度的回退。
- 区分“新轨迹出现但未成主模态”和“Pass@1 已改善”：前者常表现为 Pass@K 增益随 K 增大。

### 8.5 EvaluationReport

统一报告至少包含：

~~~yaml
report_id: eval_...
protocol_version: evaluation:v3
candidate:
  dataset_version: ds_v12
  model_checkpoint: ckpt_...
baseline:
  dataset_version: ds_v11
  model_checkpoint: ckpt_...
intrinsic_metrics: {}
filter_metrics: {}
downstream_metrics: {}
slice_metrics: {}
protection_metrics: {}
cost_metrics: {}
significance: {}
known_limitations: []
artifacts: []
~~~

## 9. Prompt 优化闭环

### 9.1 可优化对象

- math_generator Prompt。
- rewriter Prompt。
- code_generator、solution_generator、test_generator Prompt。
- small_labeler Prompt。
- llm_judge Prompt，尤其是用户要求的质量过滤 Prompt。

每类 Prompt 独立版本化：

~~~text
prompts/llm_judge/v004/
├── system.md
├── user.jinja2
├── output.schema.json
└── metadata.yaml
~~~

metadata 记录父版本、变更说明、模型适用范围、训练或优化时可见的数据集、创建者和内容哈希。

### 9.2 错误分析输入

Prompt Optimizer 只接收结构化错误包：

- 金标 False Positive 和 False Negative。
- 小模型与大模型分歧。
- Judge 与确定性验证器冲突。
- 人工抽检问题。
- 按 Slice 聚合的拒绝原因、漏放原因和校准误差。
- 下游失败切片及其数据覆盖缺口。
- 当前 Prompt、Rubric 和输出 Schema。

不把 promotion_test 或 final_holdout 的原始答案交给优化器。

ErrorPackage 必须携带 split、lineage_group_id 和来源哈希。Controller 拒绝任何来自 promotion_test、final_holdout，或由这些样本派生的反例进入 Prompt Optimizer。

### 9.3 候选生成

大模型输出 OptimizationProposal，而不是直接改文件：

~~~yaml
proposal_id: prompt_prop_017
target_prompt: llm_judge:v4
failure_clusters:
  - underspecified_math_constraints
hypothesis: Judge 对隐含唯一性条件检查不足
edits:
  - section: rubric.correctness
    operation: add
    content: 要求重新代入全部条件并检查唯一性
expected_effect:
  primary_metric: critical_error_recall
  direction: increase
risks:
  - 可能提高边界题误杀率
evaluation_plan:
  strata:
    - math_constraint_tracking
rollback_condition:
  - good_sample_false_reject_rate 增加超过门槛
~~~

实际应用 Proposal 前先由代码检查：

- 只能修改允许的 Prompt 区域。
- 一个候选优先只对应一个假设和一个原子 Diff；组合修改需要消融或预注册的 Factorial Design。
- 输出 Schema 仍可解析。
- Token 长度和成本在预算内。
- 没有引入保留集样例、秘密或环境变量。
- 生成新的候选版本，不覆盖基线。

### 9.4 候选评估与晋级

1. 在 optimizer_dev 上快速成对比较。
2. 保留多样化的若干候选，不只保留单一最高分。
3. 在 promotion_test 上盲测。
4. 检查关键错误召回、好样本误杀、分 Slice 稳定性、校准、成本和延迟。
5. 对临界候选做人工审计或双 Judge。
6. 通过后生成新 PromptVersion，并用固定 Seed 做小规模数据 Canary。
7. Canary 通过后才生成新的完整 DatasetVersion。

过滤 Prompt 的首要目标是关键错误漏放率，不能只优化总体 Accuracy。生成 Prompt 则同时优化有效 Yield、覆盖、多样性和单位成本。

对照时基线与候选使用同一输入、预算和配对 Seed，随机化展示顺序并隐藏 Prompt 版本。优化生成 Prompt 时冻结过滤器和 Judge；优化过滤 Prompt 时冻结生成数据。优化 llm_judge Prompt 时，晋级标签只能来自冻结金标、人工标签或确定性验证器，候选 Judge 不得自评。

promotion_test 不是可无限查询的调参接口。每轮预注册候选数、主指标、Slice、阈值和查询次数；候选一次性批量盲测，禁止读取某一候选反馈后在同轮继续生成。连续轮次和多候选、多指标比较使用预注册的多重比较或 alpha-spending 方案；promotion_test 定期轮换或封存，final_holdout 仅低频审计。

## 10. 采样比例优化闭环

### 10.1 分开两个比例空间

必须分别优化：

1. generation allocation：有限推理预算分配给哪些 Blueprint。
2. training mixture：已接受数据在训练 Token 中占多少比例。

某一类数据生成成功率低，可能需要更多生成预算，但不代表它应占更高训练比例。两个比例使用不同 Manifest 和 Proposal 字段。

两类实验的估计目标也不同：

- 优化 training mixture：冻结候选数据池、Prompt、过滤器、基础 Checkpoint、总训练 Token/Step 和训练配置，只改变完整的 Mixture Vector。
- 优化 generation allocation：冻结训练混合策略和质量门禁，在相同生成调用或 Token/成本预算下比较完整的 Allocation Vector。
- 两类比例不在同一普通实验轮同时改变。确需研究交互时，使用预注册 Factorial Design。

### 10.2 分层 Bucket

建议采用正交、分层的比例，而不是一次优化数千个平铺标签：

~~~text
Level 1: base_task_type = math / code / general
Level 2: generation_mode = from_knowledge / from_spec / rewrite
Level 3: domain / knowledge point / solving operation / language / style / difficulty
Level 4: transformation 与 quality tier
~~~

Rewrite 是依赖已验证父池的条件预算，不与 math/code 互斥。例如 math × rewrite 与 code × rewrite 是两个 Joint Bucket。配置需限制 max_rewrite_depth，默认只改写原始已接受父样本，防止递归改写导致分布失控。

每层设置：

- min_share：保底覆盖。
- max_share：防止单类吞噬预算。
- max_delta：单轮最大变化。
- remaining_capacity：剩余可生成或可消费样本。
- exploration_share：未知区域探索预算。
- duplication_cap：单样本或语义簇重复上限。

每个父 Bucket 下的子 share 是条件比例，必须满足 sum(child_share)=1。优化前检查 sum(min_share) ≤ 1 ≤ sum(max_share)，并联合验证 max_delta、remaining_capacity、整数样本数和 Token 预算。无可行解时明确失败，不能静默归一化。

### 10.3 大模型 Mixture Planner

为满足“根据评估结果使用大模型优化采样比例”，大模型在数值优化前生成受约束的 MixturePlanningProposal。它只读取聚合后的失败切片、覆盖缺口、过滤 Yield、重复率、成本和当前边界，不读取保留集原题，也不直接写生产比例。

~~~yaml
proposal_id: mixture_plan_023
base_allocation_version: allocation:v7
evidence:
  - slice_id: slice:constraint_tracking_x_equation
    observed_gap: high
    support: 420
    current_coverage: low
recommended_moves:
  - joint_bucket:
      base_task_type: math
      generation_mode: from_knowledge
      operations:
        - constraint_tracking
        - equation_formulation
    direction: increase
    delta_range: [0.02, 0.05]
    rationale: 目标切片缺口高且机器验证 Yield 可接受
  - joint_bucket:
      base_task_type: code
      generation_mode: rewrite
    direction: hold
risks:
  - math 语义簇集中度可能上升
required_protection_checks:
  - code_pass_at_1
~~~

Controller 验证证据引用、方向、允许 Bucket、Delta Range 和预算，再把 Proposal 转成规则优化器或代理模型的先验与候选约束。确定性 Bounded-Simplex 投影、容量检查、探索下限和实测 Gate 仍拥有最终决定权。大模型的理由是规划假设，不是收益证据。

### 10.4 P0 规则型优化器

数学切片沿用本仓库 README 的思想。对特征 F：

~~~text
Reliability(F) = log(1 + n(F)) × sqrt(n(F) / (n(F) + kappa))
Weak(F) = Reliability(F) ×
          [A_raw(F) + A_pair(F) + A_comp(F)]
~~~

P0 采用以下可实现定义，所有准确率均在同一预注册 Stratum 内估计，并用 Beta-Binomial 或 Bootstrap 收缩：

~~~text
A_raw(F) =
  max(0, SmoothedError(F) - SmoothedError(reference_stratum))

PairDegradation(u; o) =
  Accuracy(u) - Accuracy(u, o)
A_pair(F={u,o}) =
  max(0, PairDegradation(u; o))

TripleDegradation(u; oi,oj) =
  Accuracy(u) - Accuracy(u, oi, oj)
NonAdditivity(u; oi,oj) =
  TripleDegradation(u; oi,oj)
  - PairDegradation(u; oi)
  - PairDegradation(u; oj)
A_comp(F={u,oi,oj}) =
  max(0, NonAdditivity(u; oi,oj))
~~~

reference_stratum、Anchor 选择、正部截断、最小 Support、收缩先验和置信区间规则写入 weakness_protocol_version。A_raw、A_pair、A_comp 在同一 Feature Family 内缩放到可比较区间后再加权，不能把原始百分比、成本和不确定性直接相加。

不同任务流统一构造优先级信号：

~~~text
signal_i =
    target_capability_gap_i
  + coverage_gap_i
  + uncertainty_bonus_i
  - low_quality_penalty_i
  - duplication_penalty_i
  - normalized_cost_i
~~~

使用带边界的 exponentiated-gradient 更新：

~~~text
base_i = max(old_i, exploration_floor_i)
raw_i = base_i × exp(eta × clip(normalized_signal_i))
new = ProjectToBoundedSimplex(raw, min_share, max_share, max_delta)
~~~

signal 的每一项必须声明方向、权重、归一化统计量、Clip 范围和版本。exploration_floor 使 old_i=0 的 Bucket 仍可恢复。README 中的 Reliability 作为 P0 基线时，应在同一 Feature Family 内做缩放或上限截断并设置最小支持；同时对照有界置信度或经验贝叶斯收缩，避免大 Bucket 仅因 n 较大长期压制小 Bucket。

样本级选择使用加权无放回采样：

- 命中特征的样本权重取 Weak(F) 的最大值或可配置聚合。
- 使用 Efraimidis–Spirakis 指数竞赛 Key：对权重 w 大于 0 的样本生成 key = -log(u) / w，选择 Key 最小的预算数量。
- 设置语义簇和样本 duplication cap。
- 保留 rho 比例对未匹配池均匀探索。

无放回保证单次 Reservoir 内同一 sample_id 只出现一次；duplication_cap 另行限制跨 Slot、跨数据版本或训练 Epoch 的样本复用，并对 semantic_cluster_id 设置独立上限，三种作用域必须在配置中写明。

每次更新输出完整理由：哪些 Slice 变弱、候选比例、约束投影前后差异、预期收益和风险。

### 10.5 P1 实验代理模型

distillation_research/hyper_parameter_predict 可以复用为“实验配置 → 下游指标”的代理模型：

- 当前已支持 Random Forest、LightGBM、XGBoost 和 MLP。
- 使用嵌套交叉验证和 GroupKFold，适合同配置多 Seed。
- 可以通过自定义 features 接受各数据比例、Prompt 版本、阈值、训练 Token 和模型版本。

需要扩展：

- 比例非负且总和为 1 的约束。
- 候选不确定性和探索奖励。
- 多目标与保护集硬约束。
- 候选去重和 Batch 多样性。
- 高分越好或低分越好的显式方向。
- 面向顺序实验的 leave-one-round、leave-one-dataset-version-out 验证，避免随机跨轮 CV 掩盖漂移。
- 经过覆盖率校准的不确定性，例如 Bootstrap Ensemble、Quantile 或 Conformal 区间。

比例特征不应直接使用当前单变量 PDP，因为只改变一个比例会离开合法 Simplex。可选方案：

- 只建模 K-1 个比例，最后一个由和为 1 推导。
- 优先使用带版本的 isometric log-ratio 坐标；若使用 additive log-ratio，必须声明 Reference Bucket、零比例 Pseudocount 和变换版本。
- Dirichlet 可直接生成 Simplex 候选；Sobol 或 Latin-hypercube 点必须通过明确、可测试的映射进入带上下界 Simplex。
- 所有敏感性分析沿合法 Simplex 内的对比路径进行。

每轮实验预算分为 exploitation 和 exploration：

- 大部分验证代理模型预测较优且不确定性可接受的候选。
- 少部分覆盖远离历史数据或高不确定区域。
- 真实训练结果追加回实验表，再训练代理模型。

目标能力、各保护指标、成本和稳定性分别建模。先用保护指标置信上界筛除不可行候选，再按目标指标置信下界和探索奖励排序。Prompt、模型和 Checkpoint 类别在比例实验中应冻结，或仅使用历史已见水平；现有 One-hot 无法可靠外推到全新 Prompt 文本。代理模型只负责候选排序，不能充当晋级证据。

已完成 Run 的 Seed 方差是结果，不得作为尚未运行候选的已知输入特征。稳定性可以由独立模型预测，或只在获得多 Seed 实测后用于 Gate B/C 判定。

### 10.6 多目标效用与晋级

候选效用示例：

~~~text
Utility =
    weighted_target_slice_delta
  - lambda_regression × protection_regression
  - lambda_cost × normalized_training_cost
  - lambda_instability × seed_variance
~~~

同时设置硬门禁：

- 机器验证率和污染率达标。
- 目标主指标达到预设最小改善。
- 通用保护指标无超容忍回退。
- 生成与训练成本不超预算。
- 多 Seed 方差可接受。

代理模型推荐是下一批实验，不是最终最优或因果结论。

统计判定预注册为：

- 目标指标改善的置信下界超过最小实际效应。
- 保护集回退的置信上界低于 Non-inferiority Margin。
- 关键错误漏放率的单侧二项置信上界低于风险门槛。
- 样本量或训练 Seed 数满足预注册 Power 要求，并处理多候选、多指标比较。
- 使用同期随机化基线，不用历史最优值替代对照。

## 11. 未来参考：训练消费接口（不在当前实施范围）

本章保留为单向数据导出契约参考，不是当前闭环阶段，也不授权修改 `distillation_research`。当前代码不实现本章的训练 Provider、在线权重更新、Checkpoint 或模型评估功能。

### 11.1 导出两层数据

规范化层保存完整 JSONL/Parquet 和 Lineage；训练派生层保存 Tokenized Shard：

~~~text
DatasetVersion
├── canonical/
│   ├── samples-00000.parquet
│   └── manifest.json
├── training/
│   ├── continued_pretraining/
│   │   ├── math-from-knowledge.bin
│   │   ├── math-rewrite.bin
│   │   ├── code-from-spec.bin
│   │   └── code-rewrite.bin
│   ├── sft/
│   │   ├── samples.jsonl
│   │   └── assistant-loss-mask.bin
│   ├── distillation/
│   │   └── teacher-topk.bin
│   ├── sample-index.parquet
│   └── weighted_config.json
└── reports/
~~~

sample-index.parquet 维护 sample_id、shard、offset、token range，训练后出现失败切片时才能回溯到生成和过滤决策。

三种导出契约不能混用：

- continued pretraining：全 Token next-token 监督，可适配当前 NumpyBinDataset。
- assistant-only SFT：必须携带逐 Token Loss Mask，只监督目标回答；当前训练仓库的 SFTDataset 未实现，需要新增 Provider。
- teacher-top-k distillation：除 Token 外携带明确语义的 Teacher 分布和词表索引，只能使用 PT-TEACHER 路径。

### 11.2 weighted_config 解析器兼容格式

当前 arguments.py 可以解析以下结构，但不同 Dataset Mode 的实际消费行为仍不一致：

~~~json
{
  "training": [
    {
      "name": "math_from_knowledge",
      "file_path": "/immutable/env_run/ds_v12/math-from-knowledge.bin",
      "val_file_path": "/immutable/env_run/eval_v3/math-from-knowledge.bin",
      "file_size": 123456,
      "weight": 0.35,
      "consumed_data_count": 0,
      "ref_loss": 1.8,
      "quality_id": 1
    },
    {
      "name": "math_rewrite",
      "file_path": "/immutable/env_run/ds_v12/math-rewrite.bin",
      "val_file_path": "/immutable/env_run/eval_v3/math-rewrite.bin",
      "weight": 0.15,
      "consumed_data_count": 0,
      "ref_loss": 2.1,
      "quality_id": 1
    },
    {
      "name": "code_from_spec",
      "file_path": "/immutable/env_run/ds_v12/code-from-spec.bin",
      "val_file_path": "/immutable/env_run/eval_v3/code-from-spec.bin",
      "weight": 0.35,
      "consumed_data_count": 0,
      "ref_loss": 1.9,
      "quality_id": 1
    },
    {
      "name": "code_rewrite",
      "file_path": "/immutable/env_run/ds_v12/code-rewrite.bin",
      "val_file_path": "/immutable/env_run/eval_v3/code-rewrite.bin",
      "weight": 0.15,
      "consumed_data_count": 0,
      "ref_loss": 2.0,
      "quality_id": 1
    }
  ],
  "validation": [
    {
      "name": "math_from_knowledge",
      "val_file_path": "/immutable/env_run/eval_v3/math-from-knowledge.bin"
    },
    {
      "name": "math_rewrite",
      "val_file_path": "/immutable/env_run/eval_v3/math-rewrite.bin"
    },
    {
      "name": "code_from_spec",
      "val_file_path": "/immutable/env_run/eval_v3/code-from-spec.bin"
    },
    {
      "name": "code_rewrite",
      "val_file_path": "/immutable/env_run/eval_v3/code-rewrite.bin"
    }
  ]
}
~~~

训练执行层完成最小 P0 修复后，首个 Run 使用离线确认的固定权重，不在 Run 中热更新。原因是当前 set_weight 为 no-op，Checkpoint 和分布式同步也尚未满足可复现要求。

现有行为限制：

- PRETRAIN-WITH-WEIGHT 会读取独立 validation 列表；PT-TEACHER 当前仍用训练路径构建 validation/test。
- 即使提供独立 validation，每个 training 项仍必须带 val_file_path，因为解析器会无条件读取。
- file_size 当前只被 Teacher 数据路径使用，普通 Numpy Bin 会自行读取文件。
- Dataset 当前从路径字符串中的 env_run/ 推导 dataset_name；没有该片段会报错。上例暂时满足这一约束，正式接入应改为由 Manifest 显式提供稳定名称。
- PRETRAIN-WITH-WEIGHT 至少需要 dataset=PRETRAIN-WITH-WEIGHT、dataloader-type=weighted、weighted-config-file，以及一致的 seq-length、max-padding-length、Tokenizer 和起始 Checkpoint 参数。
- Teacher Shard 使用 dataset=PT-TEACHER，不能与普通 Bin 在同一 Provider 中混用。

### 11.3 训练格式注意事项

当前普通 NumpyBinDataset 把连续 int32 Token 流按 seq_length 为步长，但每次读取 seq_length + 1 个 Token 以构造 next-token label。因此文件 Token 数至少满足：

~~~text
num_file_tokens = num_samples × seq_length + 1
~~~

Shard 末尾必须保留 Look-ahead Token，不能在样本边界简单切断。现有路径还把 max_padding_length 当作 Reader Item Length，而训练张量按 seq_length 分配，接入前应强制二者相等。必须明确跨样本监督、EOD 和文档分隔策略，并用契约测试验证首尾、Stride、Label Shift 和 Loss Mask。

该格式表达的是全 Token continued pretraining，不能表达 assistant-only SFT 的逐 Token Loss Mask。数学问答或代码指令若用于 SFT，必须走独立 SFT 导出和 Provider。

当前 teacher 数据格式固定为：

- prompt：(seq_length + 1) 个 int64。
- teacher logprob：(seq_length, 256) 个 float32。
- teacher index：(seq_length, 256) 个 int32。

top-k、dtype、vocab size 和格式版本后续应写入 Manifest，避免硬编码。

Teacher Manifest 还必须明确保存值究竟是 raw logits、log-prob，还是已经过 Temperature 的概率。当前字段名是 teacher_topk_logprobs，但 Fused Loss 按 Logits 再做 Temperature 和 Softmax，若不修正契约会重复缩放。P0 仅支持 Teacher 与 Student 使用相同 Tokenizer/Vocab；top-k Index、vocab size、URL Marker Token 和 topk=256 等硬编码应在扩展前移入 Manifest 和校验器。

### 11.4 quality_id

当前 quality_id 是文件级整数，并在现有 loss 代码中带有特殊权重语义，不能直接塞入每条样本的 Judge 分数。

当前 quality_id 端到端不可用：普通 Dataset 未保存属性、普通 Batch 传播不完整、Teacher 与普通路径 Shape 不一致，质量 Loss 还有未定义符号。仅把配置值统一为 1 不能绕过这些问题。

P0 建议：

- 只把已接受数据导出训练层。
- 在修复属性、Batch 传播、Shape 和 Loss 契约前，不启用依赖 quality_id 的训练 Provider；修复后再使用经过审计的离散层级映射。
- 逐样本 small_model_score、judge_score 和 verification_level 只保存在 canonical 数据和 Sidecar。

P1 若需要逐样本质量权重，应显式定义 score → loss weight 的校准函数、上下界和消融实验，而不是线性照搬 Judge 分数。

### 11.5 训练前 Preflight

每个训练 Run 启动前检查：

- DatasetManifest、Shard 校验和和 Tokenizer 哈希一致。
- train/eval/holdout 无 sample_id 和近重复交叉。
- 实际各 Shard Token 比例与配置一致。
- train_iters × global_batch_size 不超过剩余可消费样本容量；若需要循环或有放回采样，必须显式配置并纳入重复率和恢复测试。
- Dataset Mode、seq-length、max-padding-length、Tokenizer 和导出格式匹配。
- EOS/文档分隔符的位置和 loss supervision 通过小型可视化审计。
- Sampler 在单卡和多卡下可重放，无重复遗漏异常。
- Checkpoint 能恢复数据偏移、权重、RNG 和 Controller。
- 训练入口的 Import smoke test 和 10 Step smoke run 通过。

### 11.6 P2 在线权重更新

只有训练执行层 P0/P1 问题修复后再启用：

1. Batch 显式携带整数 domain_id、slice_id 或 sample_index，并通过 Manifest Registry 解释；分布式 Batch 不传播可变字符串。
2. 对 LM、KD、JSD 等指标分别按 Key 累计 numerator、denominator、样本数和 Token 数，Controller 显式选择 primary_metric；在 DP、PP 维度做全局聚合。
3. Controller 使用 EMA 和 bounded exponentiated-gradient。
4. 全 Rank 广播同一权重版本。
5. 保存权重、每域 consumed、RNG、参考损失、Controller Step。
6. 异常指标、数据耗尽或保护指标触发 Freeze/Rollback。

在线更新只处理训练期快速信号。数学正确性、代码执行、Judge 和 Benchmark 仍由外部慢速闭环完成。

Sampler 恢复不能只依赖现有模型 load_checkpoint：需要先读取 Checkpoint 中的 Controller/Sampler Metadata，创建并校验 DataLoader 与 DatasetManifest，然后调用 sampler.load_state_dict，最后才开始迭代。

### 11.7 模型评估与机器可读出口

当前训练仓库主要提供 loss/PPL Evaluation，没有完整的数学或代码生成 Benchmark，也不保证能直接导出 Hugging Face Checkpoint。dsp evaluate-model 需要新增以下之一：

- 版本匹配的 Megatron 分布式推理 Adapter。
- 经校验的 Megatron → Hugging Face 转换和推理 Adapter。

Evaluator 启动前等待异步 Checkpoint 完成标记，并校验 Tokenizer、Model Config 和 Checkpoint Hash。训练和评估必须落盘机器可读记录：

- Metric 名称、方向、numerator、denominator、样本数和 Token 数。
- domain_id/slice_id 与 Registry Version。
- Checkpoint ID、DatasetVersion、weighted_config Hash 和训练配置 Hash。
- Iteration、World Topology、Sampler/Controller Version。
- Benchmark/Decode Protocol 和 EvaluationReport ID。

若训练 Batch 不携带 slice_id，训练期只报告文件级 Domain Loss；细粒度 Capability Slice 归因完全交给外部生成式 Evaluator，不能仅凭 sample-index Sidecar 反推。

## 12. 配置与 CLI

### 12.1 Pipeline 配置

~~~yaml
run:
  seed: 42
  output_root: artifacts/runs
  max_cost: 100.0
  fail_fast: false

models:
  generator: models/generator.yaml
  small_labeler: models/small_labeler.yaml
  judge: models/judge.yaml
  optimizer: models/optimizer.yaml

synthesis:
  new_generation:
    total_candidates: 8000
    base_task_share:
      math: 0.50
      code: 0.50
  rewrite:
    parent_budget: 2000
    max_rewrite_depth: 1
    base_task_share:
      math: 0.50
      code: 0.50
    transformations:
      style: 0.40
      diversity: 0.35
      language: 0.25

filtering:
  config: filters/default_v1.yaml
  run_small_labeler: true
  run_llm_judge: true
  human_review_budget: 100

evaluation:
  config: evaluation/default_v1.yaml

optimization:
  prompt:
    enabled: true
    max_candidates: 6
  mixture:
    enabled: true
    method: weakness_bounded_eg
    exploration_share: 0.10
~~~

配置文件只引用密钥环境变量名，不保存密钥值。模型 Revision 必须固定；无法固定的远程模型需要记录服务端返回版本并视为潜在漂移源。

### 12.2 CLI

建议入口为 dsp：

~~~text
dsp catalog build --config configs/pipeline/v1.yaml
dsp synthesize --run-id RUN_ID
dsp filter --run-id RUN_ID
dsp evaluate-data --run-id RUN_ID
dsp export-training --dataset-version DS_VERSION
dsp evaluate-model --checkpoint CKPT --protocol evaluation:v3
dsp optimize-prompt --report REPORT_ID
dsp optimize-mixture --report REPORT_ID
dsp promote --proposal PROPOSAL_ID
dsp run --config configs/pipeline/v1.yaml
dsp inspect-sample --sample-id SAMPLE_ID
dsp replay --generation-id GENERATION_ID
~~~

每条命令：

- 幂等。
- 支持 dry-run。
- 支持从已完成 Stage 续跑。
- 输出机器可读摘要。
- 不因部分请求失败丢失已成功结果。

### 12.3 LLM Adapter

定义统一接口，不让业务模块直接依赖某个 SDK：

~~~python
class LLMClient(Protocol):
    def generate(
        self,
        *,
        messages,
        output_schema,
        model,
        decoding,
        idempotency_key,
    ) -> GenerationResult:
        ...
~~~

Adapter 统一处理：

- 并发和 Rate Limit。
- 指数退避和可重试错误分类。
- 结构化输出校验和有限次数 Repair。
- 请求缓存和幂等键。
- Token、成本、延迟和错误记录。
- 模型、Prompt 和 Schema 哈希。
- 内容分隔和 Prompt Injection 防护。

## 13. 实验、门禁与回滚

### 13.1 实验单元

每个 experiment_id 对应一套固定候选配置，不同 Seed 共享 experiment_id。至少记录：

- dataset_version 和各 Bucket 比例。
- PromptVersion 集合。
- Filter 阈值和 Judge 模型。
- Student/Teacher Checkpoint。
- Tokenizer、训练 Token、学习率和训练代码 Commit。
- 分开记录 data-generation、materialization/sampler、train、evaluation/decode Seed。
- Evaluation protocol 和 Benchmark 版本。

不能把训练结束后才知道的字段作为代理模型输入，避免标签泄漏。

### 13.2 晋级门禁

建议分三级：

| 级别 | 数据规模/训练规模 | 目的 |
|---|---|---|
| Gate A | 冻结金标和小型 Canary | 排除格式、正确性、成本和明显回退 |
| Gate B | 代理模型排序后的实际短训练/实测 | 估计目标能力收益和训练稳定性 |
| Gate C | 正式多 Seed 对照 | 决定生产数据或正式训练配置晋级 |

代理模型可减少 Gate B 候选数量，但不能替代 Gate B 的真实观测。

门禁配置应明确：

- 关键错误漏放率上限。
- 好样本误杀率上限。
- 数学和代码硬验证必须通过。
- 污染和重复率上限。
- 目标 Slice 最小改善及置信区间要求。
- 保护集最大容忍回退。
- 成本和延迟上限。
- Seed 方差上限。

阈值由实际基线和业务风险校准，不能把文档示例写死为通用真值。

### 13.3 回滚

- Prompt、数据、过滤器和比例全部通过不可变版本引用。
- 新版本 Canary 只影响新生成任务，不覆盖旧数据。
- 任一门禁失败，Controller 保持当前 promoted 版本。
- 训练期若未来启用在线权重，异常时恢复上一权重快照并冻结更新。
- 回滚记录失败指标、影响范围和反例集，作为下一轮优化输入。

## 14. 测试策略

### 14.1 单元测试

- Schema 和配置边界。
- 稳定 ID、规范化和内容哈希。
- 数学解析、等价、容差、单位和唯一性。
- 比例 Simplex 投影、min/max/max_delta。
- Weighted Reservoir 的统计性质和可重放。
- Prompt 渲染、输出 Schema 和版本哈希。
- 去重、相似度阈值和 Split 隔离。

### 14.2 Contract 测试

- 每个 LLM Adapter 使用录制响应，不依赖真实外部服务。
- 每个 Prompt 的 Golden 输入都能解析为当前 Schema。
- Canonical Parquet/JSONL 往返无字段丢失。
- DatasetManifest 中 Shard 数量、Token 数和校验和一致。
- weighted_config 与训练解析器兼容。
- Tokenized Bin 的首尾、stride、label shift 和 EOS loss mask 正确。

### 14.3 集成测试

- 每种合成流从 Blueprint 到 ACCEPT/REJECT 跑通。
- 模拟超时、Rate Limit、坏 JSON、部分 Shard 失败和断点续跑。
- 数学错误答案不能被 Judge 高分覆盖。
- 代码 Judge 高分但测试失败时必须拒绝。
- 小模型与 Judge 冲突能进入设定路径。
- Prompt 候选不通过 promotion_test 时不能晋级。

### 14.4 沙箱测试

- 禁止网络、宿主文件、凭据和设备访问。
- Fork bomb、无限循环、大输出、内存耗尽和磁盘写满被限制。
- Flaky 测试能被重复执行发现。
- 沙箱失败不会降级到宿主直接执行。

### 14.5 端到端验收

使用小型固定夹具：

- 每条流若干正例、反例和边界例。
- 固定模型 Stub 或冻结响应。
- 完整运行两次，比较 Manifest 和有效样本哈希。
- 生成一个训练导出版本、一个 EvaluationReport 和至少一个被接受或拒绝的 OptimizationProposal。

## 15. 可观测性与成本

每个 Stage 记录：

- queued、started、succeeded、failed、retried 数量。
- 输入/输出 Token、单位成本和累计成本。
- P50/P95 延迟、Rate Limit 和解析失败率。
- 按 Prompt、模型、task、language、difficulty 的 Yield。
- 各拒绝原因数量和成本浪费。
- 去重前后有效样本、有效 Token 和语义簇数量。
- Judge 与验证器、小模型、人工的一致性。

设置：

- Run 总预算。
- 各 Stage 预算。
- 单样本最大重试。
- 连续错误 Circuit Breaker。
- 低 Yield 自动暂停条件。
- 模型版本漂移告警。

日志中不得保存密钥；含敏感来源的 Prompt/Response 需要脱敏和访问控制。

## 16. 里程碑与实施顺序

### M0：工程基础

交付：

- pyproject.toml、包结构和 CLI Skeleton。
- Sample、Manifest、Report、Proposal Schema。
- 流式 JSONL/Parquet、稳定 ID、事件日志。
- Prompt Registry 和 LLM Adapter Stub。

验收：离线夹具可以幂等跑完空管线，Manifest 可验证。

### M1：数学合成与验证

交付：

- Knowledge Catalog 和 Blueprint。
- 数学生成器。
- 符号、数值、约束验证器。
- 覆盖和难度回标指标。

验收：机器可验证数学夹具端到端通过，错误答案全部硬拒绝。

### M2：改写与代码生成

交付：

- 带不变量的 RewriteSpec。
- CodeBlueprint、问题/参考解/测试生成。
- 隔离代码执行和 Test-based Rejection Sampling。

验收：改写保持答案或测试；代码错误变异体能被测试检出。

### M3：两级质量过滤

交付：

- 通用规则、去重和污染检测。
- 小模型标签器。
- 大模型结构化 Judge。
- 金标校准、阈值和人工审计报告。

验收：关键错误召回、误杀和校准达到项目门槛。

### M4：数据内在评估与切片分析

交付：

- Intrinsic EvaluationReport。
- 按任务、知识点、语言、风格、难度和拒绝原因聚合。
- 候选池版本对比、成本和 Yield 指标。
- 过滤器金标集、校准集和隔离策略。

验收：基线和候选可做配对数据报告，任意指标可追溯到样本和任务定义；不要求训练或外部 Checkpoint。

### M5：Prompt 与比例优化

交付：

- 错误聚类和 Prompt OptimizationProposal。
- 大模型 MixturePlanningProposal。
- 冻结集 A/B、晋级和回滚。
- Weakness 加 bounded exponentiated-gradient 比例优化。
- 合法 Simplex 候选生成和单次变化量约束。

验收：优化器只能提出候选；绕过 Gate 的变更无法成为 promoted 版本。

### M6：数据任务晋级、回滚与运行加固

交付：

- Prompt/过滤策略/生成比例的候选注册表。
- 冻结集回放、Canary、人工晋级和一键回滚。
- 模型调用缓存、重试、预算、审计事件和私有测试访问控制。
- 数据版本 Manifest、内容哈希和可重放运行记录。

验收：同一输入、任务定义和响应夹具可重放得到一致内容哈希；未晋级候选不能覆盖基线任务定义。

## 17. 推荐的首批 Pull Request

1. PR-1：工程脚手架、Schema、配置加载、ID、Manifest、Event Log 和测试。
2. PR-2：统一 LLM Adapter、Prompt Registry、缓存、重试和结构化输出。
3. PR-3：Knowledge Catalog、数学 Blueprint、合成与确定性验证。
4. PR-4：RewriteSpec、三类改写和语义不变量检查。
5. PR-5：CodeBlueprint、三元组生成、沙箱和测试强度验证。
6. PR-6：规则过滤、去重/污染、小模型标签、大模型 Judge 和校准。
7. PR-7：Intrinsic EvaluationReport 与数据 Capability Slice 分析。
8. PR-8：冻结数据集 A/B、Prompt/过滤策略候选晋级和回滚。
9. PR-9：Prompt Optimizer、LLM Mixture Planner、受约束 Mixture Optimizer、Promotion 和 Rollback。
10. PR-10：数据 Manifest、运行恢复、机器可读指标和调用预算加固。

每个 PR 都应带小型离线夹具，不要求在线模型凭据即可运行测试。

## 18. 主要风险与控制

| 风险 | 控制 |
|---|---|
| Judge 偏好自身风格 | 生成器与 Judge 解耦、盲化、固定金标、人工抽检 |
| Prompt 优化过拟合 | dev/promotion/holdout 隔离，只返回聚合指标 |
| 数据污染 | 保留集指纹、N-gram/AST/Embedding 检测、来源隔离 |
| 合成分布塌缩 | Blueprint 配额、语义簇上限、探索预算 |
| 错误反馈被放大 | 硬验证优先、Max Delta、Canary、保护集和回滚 |
| Judge 分数被当成训练价值 | 分离 quality_score 和 utility_score，用训练对照验证 |
| 比例代理模型外推 | Simplex 合法候选、不确定性、探索预算、多 Seed |
| 代码执行逃逸 | 独立隔离执行器、禁网、资源和系统调用限制 |
| 多语言质量不均 | 分语言金标、阈值和本地化审计 |
| 模型服务漂移 | 固定 Revision、响应版本记录、漂移 Canary |
| 训练恢复不可复现 | Manifest、Sampler/Controller/RNG/Consumed 全量 Checkpoint |
| EOS 或输出格式问题被误判为能力问题 | 单独审计输出约束、生成长度、答案前缀和 loss mask |

## 19. 实施前需要确认的项目参数

以下参数不影响总体架构，但会影响具体配置：

1. 数学知识目录来源、覆盖学段和允许的题型。
2. 首批目标语言及每种语言的人工审计能力。
3. 支持的编程语言、依赖 Allowlist 和可用沙箱平台。
4. 生成模型、小模型标签器、大模型 Judge 和优化器的服务端点、预算与版本固定能力。
5. 各生成任务的调用/Token 预算、初始权重和最大单次变化量。
6. 首批冻结数据金标集、保护集和污染排除清单。
7. 可接受的许可证、隐私和数据保留规则。
8. 数据主指标、质量回退容忍度、人工复核预算和晋级节奏。

在这些参数未确定前，可以先完成 M0 和使用离线夹具的 M1 骨架。

## 20. 参考与现有资产

- 本仓库 [Data and Evaluation Closed-Loop README](../README.md)：能力切片、评估到数据映射、数学操作组合诊断与加权采样。
- [Data and Evaluation Closed-Loop for Model Capability Enhancement](https://arxiv.org/abs/2606.28471)：本仓库方法论文。
- [KodCode: A Diverse, Challenging, and Verifiable Synthetic Dataset for Coding](https://arxiv.org/abs/2503.02951)：question-solution-test、自验证、困难任务额外尝试和测试拒绝采样。
- [KodCode 官方实现](https://github.com/KodCode-AI/kodcode)：多来源任务生成、pytest、自验证和风格转换工程参考。
- ../../distillation_research/README.md：分领域训练目标与能力评估。
- ../../distillation_research/hyper_parameter_predict/README.md：实验配置到 validation loss 的代理建模和下一批候选推荐。
