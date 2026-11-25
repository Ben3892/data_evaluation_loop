# 数据合成与质量评估闭环（Data-only MVP）

当前实现只闭环数据任务，不修改训练代码，也不根据训练 loss 自动调整训练过程。

闭环对象是版本化的数据任务定义：数学知识点合成、风格/多样性/语言改写、类 KodCode 代码任务生成、确定性检查、小模型打标、大模型 Judge、数据内在评估，以及由大模型提出的 Prompt 或生成任务采样比例候选。

安装、论文实验对照组、可运行示例和预期产物见[论文实验指南](docs/PAPER_EXPERIMENTS_zh.md)。详细设计见 [CLOSED_LOOP_IMPLEMENTATION_DESIGN_zh.md](docs/CLOSED_LOOP_IMPLEMENTATION_DESIGN_zh.md)。

## 当前已实现

- `knowledge_extraction`：从来源文本抽取带来源、前置知识、求解操作和难度范围的知识点。
- `math_knowledge`：按知识点、求解操作、难度、语言和输出约束合成数学题。
- `rewrite`：独立改写已有候选；保留答案/解答、数值字面量和 lineage。
- `code_generation`：生成 question-solution-test；私测单独存储，公开样本只保留哈希。
- `filter`：先跑确定性硬检查，再依次调用小模型标签器与大模型 Judge。
- `evaluate`：按独立任务统计生成成功率、有效率、接受率和拒绝原因。
- `optimize-prompt`：大模型只能修改任务声明的 `editable_fields`，产生新版本候选，不自动覆盖基线。
- `optimize-mixture`：大模型提出三类生成任务的调用预算比例，再由确定性算法投影到上下界和 `max_delta` 约束内。
- OpenAI-compatible HTTP 模型客户端和完全离线的 Replay 客户端。

## 快速开始

Python 3.9+ 即可运行核心代码，无必装第三方依赖。

~~~bash
python3 -m data_synthetic_pipeline list-tasks
python3 -m pip install '.[eval]'
python3 -m unittest discover -s tests -v
~~~

下面用仓库自带响应夹具离线重放一个完整的数据闭环。使用新的 `run-id`，避免向已有 JSONL 追加重复记录。

~~~bash
python3 -m data_synthetic_pipeline run-task \
  --task math_knowledge \
  --input examples/math_inputs.jsonl \
  --responses examples/math_responses.jsonl \
  --run-id demo-math-v1

python3 -m data_synthetic_pipeline filter \
  --executions artifacts/runs/demo-math-v1/executions.jsonl \
  --labeler-responses examples/labeler_responses.jsonl \
  --judge-responses examples/judge_responses.jsonl \
  --output artifacts/runs/demo-math-v1/quality.jsonl

python3 -m data_synthetic_pipeline evaluate \
  --executions artifacts/runs/demo-math-v1/executions.jsonl \
  --quality artifacts/runs/demo-math-v1/quality.jsonl \
  --output artifacts/runs/demo-math-v1/evaluation.json

python3 -m data_synthetic_pipeline optimize-prompt \
  --task math_knowledge \
  --report artifacts/runs/demo-math-v1/evaluation.json \
  --responses examples/prompt_optimizer_response.jsonl \
  --output artifacts/runs/demo-math-v1/prompt-proposal.json

python3 -m data_synthetic_pipeline optimize-mixture \
  --report artifacts/runs/demo-math-v1/evaluation.json \
  --responses examples/mixture_optimizer_response.jsonl \
  --output artifacts/runs/demo-math-v1/mixture-proposal.json
~~~

任务可独立运行；例如只生成代码任务，不需要先运行数学任务或改写任务。`rewrite` 唯一额外输入是一个完整的父候选，因为它需要验证答案不变量和记录 lineage。

## 接入在线模型

不传 `--responses` 时，CLI 调用 OpenAI-compatible `chat/completions` 接口。生成任务使用：

~~~bash
export DSP_LLM_BASE_URL=http://localhost:8000/v1
export DSP_LLM_MODEL=your-generator-model
export DSP_LLM_API_KEY=optional-key
~~~

质量和优化阶段可以使用独立模型：

- 小模型标签器：`DSP_SMALL_LLM_BASE_URL`、`DSP_SMALL_LLM_MODEL`、`DSP_SMALL_LLM_API_KEY`。
- 大模型 Judge：`DSP_JUDGE_LLM_BASE_URL`、`DSP_JUDGE_LLM_MODEL`、`DSP_JUDGE_LLM_API_KEY`。
- Prompt/比例优化器：`DSP_OPTIMIZER_LLM_BASE_URL`、`DSP_OPTIMIZER_LLM_MODEL`、`DSP_OPTIMIZER_LLM_API_KEY`。

## 任务定义与变更规则

任务定义位于 `task_definitions/*.json`，包含 Prompt、输出 Schema、模型参数、采样约束和可编辑字段。每次执行都把定义哈希、模型、请求 ID 和父样本写入候选元数据。

大模型优化器只输出 `PromptProposal`/`MixtureProposal`：

1. 不修改 Python 代码。
2. 不覆盖当前任务定义。
3. 不允许修改 `editable_fields` 之外的字段。
4. 比例必须覆盖全部生成任务、和为 1，并满足每个任务的上下界与最大变化量。
5. 候选需要在冻结夹具或人工金标集上回放后，由人工决定是否晋级。

## 产物和隐私边界

每个 Run 默认写入 `artifacts/runs/<run-id>/`：

- `executions.jsonl`：公开候选、验证结果和 lineage。
- `private/<candidate-id>.json`：代码私测，文件权限设为 `0600`。
- `quality.jsonl`：硬规则、小模型和 Judge 的决策。
- `evaluation.json`：数据内在评估。
- `prompt-proposal.json`、`mixture-proposal.json`：待验证候选。
- `events.jsonl`：运行审计事件。

代码解答目前只做 Python AST/入口函数静态检查，不会在宿主机执行未信任代码。生产级代码正确性仍需接入禁网、只读文件系统、CPU/内存/时间受限的隔离执行器。数学 MVP 当前做结构和参考答案存在性检查；符号/数值独立求解器是下一阶段，不能用 Judge 分数替代。

## 包结构

~~~text
data_synthetic_pipeline/
├── task_definitions/                 # 可版本化、可由 LLM 提案修改的任务定义
├── examples/                         # 无模型凭据也可运行的响应夹具
├── tests/                            # unittest 离线测试
└── data_synthetic_pipeline/
    ├── llm.py                        # 在线/重放模型客户端
    ├── registry.py                   # 任务定义注册表
    ├── tasks/                        # 三类相互独立的生成任务
    ├── quality.py                    # 硬检查 + 小模型 + Judge
    ├── evaluation.py                 # 数据内在评估
    ├── optimization.py               # Prompt/生成比例候选
    ├── storage.py                    # 公开/私有产物与事件
    └── cli.py                        # 独立任务 CLI
~~~


## 新增：题级评测最小闭环

```sh
python -m pip install '.[eval]'
python -m data_synthetic_pipeline run-loop --input fixtures/eval-smoke.jsonl --baseline base --target candidate --output artifacts/eval-smoke
python -m unittest discover -s tests -v
```

新增题级结果 Schema、`first_error` / `primary_error` 标注约束、按题重复作答统计和前后模型正确性转移。8 条离线夹具覆盖四种转移，仅验证接口，不是实际模型效果。详细说明、命令、验收结果和未完成工作见 [实施报告](docs/EVALUATION_LOOP_IMPLEMENTATION_zh.md)。前端工作台源码与启动方式见 [workbench/README.md](workbench/README.md)。
