# AIME 整数答案评测接入

基线为 `Ben3892/data_evaluation_loop` 的 `main@a3ecb5c`。原入口 `run-loop` 已支持离线评分、`EvaluationResult` v1、显式步骤标注、重复作答正确率，以及按 attempt 配对的四格迁移。该入口的任务配置原先只接受 `exact_match/strip`。AIME 的答案空间是 0–999 的整数，适合在相同入口里用标准库做确定性判分，并同时验证重复采样统计。公开题目规则见 [MAA](https://old.maa.org/sites/default/files/pdf/pubs/mar04.pdf)。

## 判分与输入契约

| 字段或接口 | 行为 |
| --- | --- |
| `--task data_synthetic_pipeline/eval_assets/aime-integer.v1.json` | 选择 `aime_integer/aime_final_answer.v1`。评分函数接收 `answer, reference` 并返回正确性与标准答案，`evaluate` 继续组装并校验 v1 结果。 |
| `sample_id` | 使用稳定的题目 ID，如 `aime/1983/p01`。有 I/II 场次时将场次纳入 ID。每次作答从同一份冻结答案表关联 `reference`。 |
| `run_id, model, protocol, attempt_id` | 一个 run 对应固定模型和推理配置。协议使用现有 `direct` 或 `reasoning`，attempt 为非负整数。同一协议下的比较使用共享的重复作答编号，编号对应预先约定的采样槽位。 |
| `answer` | 传入上游已定位的最终答案字段。接受 1–3 位 ASCII 数字及独立的 `\boxed{60}`、`$60$`、`$\boxed{060}$` 形式，去除外部空白后统一为三位数。空串、歧义、多候选、表达式和非标准格式记为错误。输入类型错误返回结构化失败。 |
| `reference` | 来自题库答案表的字符串。去除外部空白后须为 1–3 位 ASCII 数字，输出统一为三位数，如 `60` 和 `060` 均写成 `060`。非法参考值使运行失败。结果中保留原始 `answer` 以便回放。 |
| `annotation_status, steps` | 标注按 `run_id/task_id/sample_id/attempt_id/protocol` 关联到同一次作答。默认 `unreviewed`。步骤按 `step_id` 升序且唯一，每步提供 `action, validity, error_type, evidence`。标记 `incorrect` 时须注明类型与证据，无法判断时标记 `unknown`。 |
| `first_error` | 结果侧从最早的已确认错误派生。此前可以有 `unknown` 步骤，此时只定位到「最早已确认」。 |
| `primary_error` | 外部标注可提供 `{step_id, type, evidence}`，三项须与某个 `incorrect` 步骤精确一致。证据不足时用 `null`；已确认的主因可以出现在首错之后。 |

评分只使用答案字段，错误归因只使用显式标注。答对的尝试也可能有已确认的过程错误，答错且未审核的尝试两个错误字段均为 `null`。保存真实运行时，将完整响应、提取器版本、题库版本、模型 checkpoint、prompt、解码配置和 seed 保存在上游运行清单，并用结果键关联。实际回放需要上游先划定最终答案字段，再运行本仓库的适配器。

## 重复作答与 pass@k

- `summary.json.per_question` 保持按 `run_id/task_id/sample_id/protocol` 分组。`n` 为已提交尝试数，`correct` 为正确数 `c`，`accuracy` 为 `c/n`。成功返回但答案为空或格式不合法计入 `n`。上游传输或请求失败单独记录，汇总的 `n` 仅反映已评分尝试。
- 传入 `--pass-at-k 1 2 32` 时，每题附加 `pass_at_k` 对象。`n ≥ k` 时计算 $1 - \binom{n-c}{k}/\binom{n}{k}$，`n < k` 时填 `null`，`c = 0` 且 `n ≥ k` 时为 0。`pass@1` 等于当前采样协议下的 `c/n`。估计量参见 [Chen et al., 2021，式 (1)](https://arxiv.org/pdf/2107.03374)。
- 顶层 `pass_at_k` 按 `run_id/task_id/protocol/k` 给出题级等权均值 `value`、`eligible_questions` 和 `total_questions`。后者是有作答记录的题数，零作答覆盖需用冻结题表审计。对比模型时固定解码策略并使用双方共同满足 `n ≥ k` 的题集。将结果解释为采样 pass@k 要求同题重复来自同一采样分布、独立生成。
- 正确性迁移继续按 `task_id/sample_id/attempt_id/protocol` 匹配。跨协议的尝试保留在各自统计中，同一配对的标准答案须一致。

## Fixture 与验收

`fixtures/aime-smoke.jsonl` 使用 1983 AIME 第 1 题的金标 `060`。取 `x,y,z>1` 和 `w>0`，给定 `log_x(w)=24`、`log_y(w)=40`、`log_{xyz}(w)=12`，求 `log_z(w)`。换底后 `log_w(z)=1/12−1/24−1/40=1/60`。题目和金标来自赛事，7 次作答与步骤标注是手工构造的验收数据。[题目与公开解答](https://artofproblemsolving.com/wiki/index.php/1983_AIME_Problems/Problem_1)

```sh
python -m pip install '.[eval]'
python -m data_synthetic_pipeline run-loop \
  --task data_synthetic_pipeline/eval_assets/aime-integer.v1.json \
  --input fixtures/aime-smoke.jsonl \
  --baseline base --target candidate --pass-at-k 1 2 32 \
  --output artifacts/aime-smoke
python -m unittest discover -v
```

| Run | Protocol | n | 正确数 | pass@1 | pass@2 | pass@32 |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| base | direct | 1 | 1 | 1 | null | null |
| base | reasoning | 3 | 2 | 2/3 | 1 | null |
| candidate | reasoning | 3 | 1 | 1/3 | 2/3 | null |

预期输出 7 条结果、3 个配对、1 个未配对。迁移为 2 个正确→错误、1 个错误→正确。候选 run 的 attempt 0 在步骤 1 记录首错、步骤 2 记录主因。测试覆盖规范化、无效参考、归因与正确性独立、题级宏平均、覆盖不足、协议隔离和旧输出兼容性。

`EvaluationResult` v1 可继续用于工作台校验。AIME 判分与 pass@k 通过 Python CLI 执行，浏览器 smoke 使用原 exact-match 入口。完整榜单复现需要冻结完整题表、提示词、最终答案提取协议与采样记录。
