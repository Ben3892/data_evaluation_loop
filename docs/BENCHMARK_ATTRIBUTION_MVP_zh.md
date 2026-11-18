# Benchmark 推理动作与错误归因

基线为 2026-08-24 的 `main@e0bf620`。仓库原有 `run-task` 支持数学知识点合成、改写和代码数据生成，`filter` 支持确定性规则和 LLM 质量判定，`evaluate` 输出生成、有效和接受率，`optimize-prompt` 与 `optimize-mixture` 输出候选。设计文档 §8.3–8.4 把下游模型指标和训练归因列为未来工作。沿用 README 的题目侧能力切片，新增一个独立的模型轨迹入口。

## 文件与验收

下表命令在仓库根目录执行。每个 `unittest` 命令均使用自造题和固定标签，覆盖对应机制。

| 缺口 | 文件与最小改动 | Smoke test |
| --- | --- | --- |
| Atomic task | `task_definitions/benchmark_trace_annotation.v1.json`。用既有 registry 和 LLM client，把一条已判分的 attempt 映射为一组动作及归因。 | `python3 -m data_synthetic_pipeline list-tasks`，应含 `benchmark_trace_annotation`、`v1`。 |
| 可运行入口 | `data_synthetic_pipeline/cli.py` 增加 `benchmark-run`。读已判分 JSONL，可导入人工标注或用回放 judge。 | `python3 -m unittest tests.test_benchmark_mvp.BenchmarkMVPTests.test_run_and_stats`。生成 8 条结果并验证 judge 回放、各任务切片。 |
| 结果协议和重复/故障处理 | `schemas/benchmark_attempt.v1.json` 描述交换格式，`benchmark.py` 验证输入、步骤引用和失败 rubric，`utils.py` 增加原子写入。 | `python3 -m unittest tests.test_benchmark_mvp.BenchmarkMVPTests.test_failed_replay_preserves_previous_output`。错配 response 时输出保持为上一次完成的文件。 |
| First-error / primary-error | `benchmark.py` 按步骤派生 first-error，校验 judge 提议的 primary-error。 | `python3 -m unittest tests.test_benchmark_mvp.BenchmarkMVPTests.test_reject_repaired_or_unlinked_primary`。拒绝已修复的 primary 和指向通过项的 rubric。 |
| 切片与基础统计 | `benchmark.py:summarize_attempts`，由 `benchmark-stats` 读结果计算覆盖、动作与转移、first/primary 分布、attempt accuracy 和题级 pass@k。 | `python3 -m unittest tests.test_benchmark_mvp.BenchmarkMVPTests.test_run_and_stats`。SimpleQA 夹具 3 次中答对 1 次，pass@2 应为 2/3。 |
| 受控验证的配对接口 | `benchmark.py:compare_attempts` 和 `benchmark-compare`。匹配数据版本、题、协议、scorer、采样编号，输出改善/退化及缺失计数。 | `python3 -m unittest tests.test_benchmark_mvp.BenchmarkMVPTests.test_comparison_reports_unmatched_and_unscored`。夹具覆盖改善、单侧缺失和评分失败。 |

```bash
out=$(mktemp -d)
python3 -m data_synthetic_pipeline benchmark-run \
  --input examples/benchmark_attempts.jsonl \
  --judge-responses examples/benchmark_judge_responses.jsonl \
  --output "$out/results.jsonl"
python3 -m data_synthetic_pipeline benchmark-stats \
  --results "$out/results.jsonl" --slice operator --k 2 --output "$out/stats.json"
python3 -m unittest discover -v
```

每条有可见轨迹且无随行标注的 attempt 消耗一条 judge replay，回放须按输入顺序排列且匹配 `attempt_id`。只导入人工标签时去掉 `--judge-responses`。需要跑新标注时，已有 OpenAI-compatible 适配器可通过 `--judge-online` 使用，配置 `DSP_BENCHMARK_JUDGE_BASE_URL`、`DSP_BENCHMARK_JUDGE_MODEL` 和可选的 `DSP_BENCHMARK_JUDGE_API_KEY`。在线标注用真实任务、题目证据或参考作为依据，先用人工金标校准。

## 输入输出

一个 attempt 对应一个 checkpoint 对一道题的一次采样。上游评测应先完成作答与原 benchmark 判分，再把同一次作答的最终答案、可见轨迹与判分按键对齐。工具协议、解码、模板、token budget、上下文策略、seed 列表、选项顺序规则等写入 run manifest，`protocol_id` 引用这份可复现配置。题目的四维能力切片从样本侧继承，`trace` 侧的动作由这次作答提供。

| 字段 | 输入 | 结果 |
| --- | --- | --- |
| 身份与切片 | `run_id`、`model`、`benchmark`、`dataset_revision`、`item_id`、`protocol_id`、`sample_index`、`family`、可选 `slices` 字典。 | 保留身份、切片，计算稳定 `attempt_id` 并检查重复。 |
| 官方判分 | `score.outcome` 用 `correct / incorrect / abstain / unscored`，`score.scorer_id` 固定判分器版本及配置。IF 可传 `score.rubric_results`。 | 保留原判分与 rubric。每个 rubric 的 ID 在相同数据版本的不同模型之间保持一致。 |
| 可见轨迹与依据 | `trace` 是预切分的有序文本段。可选 `trace_kind`、`trace_ref`。LLM 输入可带 `task`、`reference`、`answer`、`tool_policy` 和 `tool_events`。 | 记录 `annotated / unannotated / unavailable`、轨迹类型、哈希和引用。若需定位原文，按 `trace_ref` 或同一 attempt 键回查原输入，`steps[*].index` 为从 0 开始的段号。 |
| 动作标签与归因 | 可随行提供 `annotation` 和 `annotator_id`，或由 judge 返回。每个段一个主动作，附质量、错误证据、行为标记、前置依赖与修复链接。 | `steps`、`first_error`、`primary_error`、`annotation_source`、`annotation_definition_id`。 |

建议让 adapter 在原轨迹中切出一句话级的可检验证据单元，如一项约束、一条候选排除依据、一个代数变换或一个可观测工具动作。把同一步的公式和释义留在同段，多个可独立验证的决定可拆分。完整轨迹、推理摘要和只有最终答案分别用 `reasoning_trace / reasoning_summary / final_answer`，只有答案时还可保留空轨迹。最终文本中的格式、选项映射或无依据断言可独立诊断。记录的错误位置以可见段为准。

### 动作、质量、错误与行为标记

- `action` 是做了什么，例如 `select_candidate` 或 `verify`。`quality` 用 `good / neutral / bad / uncertain`。有效动作推进任务或排除假设。中性动作不改变当前结论。错误动作有明确冲突的要求或证据。缺证据时用 `uncertain`。
- `error.code` 是错法，例如 `candidate_selection`。`evidence` 指向支持判断的上下文、公式、规范、工具记录或评分项。若后续步骤在错误前提下局部执行正确，填 `introduced_here=false`，链接 `depends_on`，仍可通过依赖看到传播。若一段新引入另一错误，则标为本段起因。
- `markers` 记行为。猜题源 `source_guess`、无依据猜测 `unsupported_guess`、打算用工具 `tool_intent`、模拟搜索 `simulated_search`、未核实来源 `unverified_source`、先选答案再找依据 `answer_first_rationalization`、空验证 `empty_verification`、无进展重复 `repetition_without_progress`。行为可伴随不同质量。只有闭卷设置或完备的工具记录排除了声称的查询结果，才标模拟搜索。来源未核实用相应标记，有可信反证再记错误，引用真实来源但读错内容用 `evidence_misread`。
- `first_error` 取最早新引入的可定位错误，保留后来更正的错误。有效的试探分支正常标注，正式使用了错误前提才按具体证据标错。
- `primary_error` 是对失败结果最有解释力的一个未修复起点。标注者写清改这一步会影响哪个答案或失败 rubric。多个原因无法区分、可见证据不足，值为 `null`。最终判对但有错误步骤仍保留 first-error，可追踪自修复或无效推导碰巧命中。primary 的初始状态是 `hypothesis`，修复验证所得证据另作实验记录。

## 按任务标注

以下使用自造例子。每个任务把题目需要的操作切片和模型实际采取的动作同时保留。例如 AIME 题目侧标 `boundary_case_reasoning`，轨迹侧能看到 `split_cases` 正确但 `compute` 出错，或根本遗漏一个分支。

| 题型 | 有效动作 | 错误或风险行为 | 标注边界与修复验证 |
| --- | --- | --- | --- |
| SimpleQA / fact recall | 解析实体、关系、年份和答案类型 `parse_target`；回忆事实 `recall_fact`；提出并按限定词逐一排除候选 `generate_candidate / select_candidate`；已有依据时交叉核对 `verify`。 | 拿同名人或邻接实体的事实 `entity_confusion`；忽略年份 `target_mismatch`；误排已出现且满足条件的候选 `candidate_selection`；猜题源后把猜测当证据、闭卷模拟搜索、编造或误用来源 `unsupported_claim / evidence_misread`。 | 对没有候选或只有最终错答的轨迹保留未知。明确说无法回忆并因此弃答，可记录 `recall_unresolved`，它只描述该次输出。通过同题 direct/reasoning 对照、无答案实体消歧提示或中性候选列表，区分可访问知识与候选裁决。 |
| AdvancedIF | 建约束清单，保留角色优先级、作用范围、触发条件和禁止项 `bind_constraint`；按每个 rubric 检查成品 `verify`。 | 把引用文本当系统指令、错用约束层级 `constraint_scope`；漏条件约束 `constraint_omission`；推理里识别了限制，成品多前言或超长度 `output_violation`。 | rubric ID 保留原始维度。若推理已正确绑定约束，定位到最后产出或编辑。只补缺失约束或改最终渲染，观察哪一项恢复。 |
| MultiChallenge | 找到原始轮次与适用信息 `locate_evidence`；更新当前版本及偏好 `update_state`；按修改范围编辑并复核未改字段。 | 继承旧版本 `stale_state`；覆盖用户未要求改的部分 `unauthorized_edit`；忘记早先约定 `constraint_omission`；与先前承诺矛盾可定位到所用状态或最终产出。 | 切片保留 benchmark 原有四轴（instruction retention、inference memory、self coherence、reliable version editing）。最小重放可只给准确的相关轮次或当前版本，分别检验找回信息和正确编辑。 |
| CL-bench / CL-bench Life | 定位上下文内规则、例外和信息来源 `locate_evidence / bind_constraint`；应用规则或流程 `apply_rule`；对时间线与版本重建状态 `update_state`。 | 用常识覆盖材料内规则 `context_rule_override`；套规则前漏例外 `rule_precondition`；跳过材料规定的操作 `procedure_skip`；采用过期记录 `stale_state`；编入材料没有的依据 `unsupported_claim`。 | 先切开定位、解释、应用和输出四类错误。只给相关上下文片段的诊断重放可检验定位。只提示某条规则的适用条件可检验应用。公开资料使用 **CL-bench Life**；如果内部的 **CLBench Live** 是独立评测，保留专有 benchmark ID、版本和 rubric。 |
| AIME / MATH | 形式化变量与题设 `model_problem`；选择方法且核对假设 `choose_method / apply_rule`；符号变换、分情况、回代及边界检查 `transform_symbol / split_cases / verify`。 | 建模错 `wrong_model`；除以可能为零的变量或错误逆推 `rule_precondition / invalid_transform`；算术错 `calculation`；漏分支 `case_omission`；把中间量当问求量 `answer_mapping`。 | 允许与参考解不同的证明路径。算错后回代修复仍计 first-error；若后来漏分支才动摇结果，primary 指漏分支。分别重放合法变换提示、有遗漏的域或成品答案提取。AIME 整数与 MATH 数学等价由各自 scorer 处理。 |
| GPQA / 科学推理 | 分清观测条件、变量和机制 `model_problem`；检查定律适用域 `apply_rule`；推导可比较结果 `derive_prediction`；用单位、数量级、反例和机制检查 `verify / evaluate_alternative`。 | 套错机制 `mechanism_mismatch`；条件不适用 `rule_precondition`；单位、量纲或量级错 `units_or_scale`；把相关当因果、忽略对照或混杂 `causal_overreach`；先选项后合理化；推导正确但填错选项 `answer_mapping`。 | 物理例子中定律选对、比例方向推反，定位 `invalid_inference`；只换选项顺序或隐藏选项重放可检查选项依赖。提供适用条件但不提供结论，可检查定律调用与后续推断。 |

来源：[SimpleQA](https://openai.com/index/introducing-simpleqa/) · [AdvancedIF](https://github.com/facebookresearch/AdvancedIF) · [MultiChallenge](https://huggingface.co/datasets/ScaleAI/MultiChallenge) · [CL-bench / Life](https://github.com/Tencent-Hunyuan/CL-bench) · [GPQA](https://arxiv.org/abs/2311.12022) · [ProcessBench](https://aclanthology.org/2025.acl-long.50/) · [可见 CoT 与解释忠实性](https://arxiv.org/abs/2305.04388)

## 从归因到干预

1. **校准。** 从每个任务抽取正确、错误、弃答和疑似自修复轨迹，按题分层。人工双标先核对分段和 error span，再核对 first-error、primary-error、rubric、修复关系。Judge 隐藏 checkpoint 名称与实验组，固定输入格式。抽查 `primary_error=null`、短轨迹和涉及来源的报告，记录人审与 judge 的分歧和可定位覆盖。
2. **定位退化。** 固定评分与采样协议，配对比较 base、K3 KD、K2.6 KD。同一题分别算正确稳定、偶尔做对、全错三类的迁移。优先看「base 对 → K3 错」与「base 错 → K3 对」，同题 K2.6 作为对照。报告每类错误占全部失败和占可定位失败的比例。还要看 marker 在正确与错误 attempt 的发生率，避免把普遍的风格差异解释成错误。轨迹长度只在分层和对照中使用。
3. **低成本验证。** 在开发集对候选步骤做最小修复，另做等 token 的中性提示对照。固定后续生成预算与采样，记录评分恢复、失败 rubric 恢复及其它错误变化。涉及答案的 oracle 修复单列，作为可修复上限。把无可见轨迹的 direct-answer 分数与 reasoning-enabled 的过程指标分开报告。
4. **训练验证。** 按第 3 步支持的假设选一个切片。比如删除“自报搜索结果且无工具依据”的 K3 轨迹、对补齐例外检查的解轨迹增权、补上有对照的科学解释或版本编辑样本。用同基础 checkpoint 和相同训练配方做匹配对照和定向干预，固定 token 预算、训练步数、混合域和 held-out 题集。候选训练集只用训练来源，目标 eval 题留作验证。复跑原协议和保护切片。确认目标错误率下降、同题成绩恢复及保护切片波动，再决定是否晋级。

```bash
python3 -m data_synthetic_pipeline benchmark-compare \
  --baseline base.results.jsonl --candidate intervention.results.jsonl \
  --output comparison.json
```

`benchmark-compare` 输出配对 attempt 上的准确率差和迁移数。开启下一轮决策前同时核对缺失项与未评分项。同题多采样的置信区间以后按题 bootstrap，避免把同题样本当独立题。基础统计的 pass@k 按题计算 `1 - C(n-c,k)/C(n,k)` 再宏平均，公开有效题数。它排除评估记录内有 `unscored` 或 `n<k` 的题。整条 attempt 缺行需要上游 manifest 检查。对于比较 K3“稳定性下降且 pass@32 上升”的场景，额外比较同一题集、同样本数下的 `c/n`、全错比例和稳定正确题比例。

当前验证的是结构化导入、judge 回放、统计和配对协议。真实 rollout 收集和官方 scorer 的数据适配由上游评测脚本完成，离线夹具只用于验证工程行为。训练集重采样与重训沿用已有的数据和训练工具，诊断结果提供干预对象与复测接口。
