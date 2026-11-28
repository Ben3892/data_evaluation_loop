# 从启动仓库到回放论文实验

从仓库根目录运行命令。第一次使用需要 Python 3.9+ 和 `jsonschema`。以下入口都可以在 CPU 上用固定响应回放。原论文的两个干预在外部继续预训练流水线上完成，本仓库提供数据任务和评测工具；原始训练集、训练入口、模型权重及两组完整 rollout 需另备。[论文 PDF](../Data_and_Evaluation_Closed_Loop.pdf) · [arXiv](https://arxiv.org/abs/2606.28471)

## 先确认启动哪条链路

| 想完成的工作 | 启动入口 | 能核对的产物 |
|---|---|---|
| 合成数学样本、过滤、比较 Prompt 或生成任务比例 | `run-task → filter → evaluate → optimize-prompt / optimize-mixture` | `executions.jsonl`、`quality.jsonl`、`evaluation.json` 和候选提案。[完整离线命令](../README_zh.md#快速开始) |
| 对固定题集比较两个模型 | `run-loop` | `results.jsonl` 每次作答一行，`summary.json` 给出题级正确率、对应 attempt 的迁移和可选 pass@k |
| 从浏览器查看题级证据 | 在仓库根目录运行 `python -m http.server 8080 --directory workbench`，打开 `http://localhost:8080` | 浏览器导入与回放。[工作台用法](../workbench/README.md) |

```bash
python -m pip install '.[eval]'
python -m data_synthetic_pipeline list-tasks
python -m data_synthetic_pipeline run-loop --help
python -m unittest discover -s tests -v
```

`list-tasks` 应列出 8 个版本化任务。全量测试中有一项需要公开 AIME 响应文件，由 `AIME_REPLAY_SOURCE` 指定；获取方式见下文实验二。数据命令 `evaluate` 统计生成样本的接受率，模型答题正确率由 `run-loop` 计算。

## 实验一：BBH 退化与 EOS 监督

**问题。** BBH 下降时，模型有多少次已经给出正确前缀，却因继续生成内容而被原 scorer 判错？

**论文对照。** 保留 warm-start 作为续训前参照。base 沿用将 EOS 目标排除在 loss 外的配置，exp 恢复这些目标的 loss。两条续训分支从同一起点出发，保持训练数据、预算、模型和优化器配置一致。验证训练侧改动时，在 label shift 之后检查“目标 token 是 EOS”的位置及其 loss mask；只统计输入序列里出现过多少个 EOS 无法验证梯度监督。[论文案例一](../README.md#5-case-study-1--output-constraint-diagnosis-reveals-an-eos-supervision-bug)

**评测顺序。** 对三个 checkpoint 使用同一题表、prompt、解码设置、过滤器与 BBH scorer。保存每题的 gold、原始响应、过滤后的响应、判分和输出约束标签。论文在 5,545 条 closed-set / 单选预测上审计前缀。先计算“过滤后以 gold 开头的题数 / 审计题数”，再计算“原 scorer 判对的前缀命中数 / 前缀命中数”。报告分母，同时比较后缀长度和异常起始串。前缀诊断始终保留原判分。

| 论文报告的指标 | warm-start | base | exp |
|---|---:|---:|---:|
| BBH 得分 | 47.27 | 25.14 | 66.44 |
| gold 前缀命中率 | 50.39% | 69.25% | 69.31% |
| 前缀命中后被 scorer 接受的比例 | 99.82% | 37.34% | 99.69% |

**本地验证。** 下面两条人工记录模拟同一道闭集题。它们经过仓库的 stripped exact-match 入口生成一对“错→对”，可用来检查进入正式审计前，过滤后的尾随文本是否仍可追溯。

```bash
work=$(mktemp -d)
cat > "$work/bbh-prefix.jsonl" <<'JSONL'
{"run_id":"masked","model":"demo-base","sample_id":"demo/bbh/01","attempt_id":0,"protocol":"direct","reference":"(A)","answer":"(A)<begin_url>continued"}
{"run_id":"restored","model":"demo-exp","sample_id":"demo/bbh/01","attempt_id":0,"protocol":"direct","reference":"(A)","answer":"(A)"}
JSONL
python -m data_synthetic_pipeline run-loop --input "$work/bbh-prefix.jsonl" \
  --baseline masked --target restored --output "$work/report"
python - "$work/report/results.jsonl" <<'PY'
import json, sys
from collections import Counter
from pathlib import Path

counts = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    group = counts.setdefault(row["run_id"], Counter())
    group["total"] += 1
    if row["answer"].startswith(row["reference"]):
        group["prefix"] += 1
        group["accepted"] += int(row["correct"])
for run, c in counts.items():
    print(run, "prefix/total", (c["prefix"], c["total"]),
          "accepted/prefix", (c["accepted"], c["prefix"]))
PY
```

预期两组的 `prefix/total` 均为 `(1, 1)`，`accepted/prefix` 从 `(0, 1)` 变为 `(1, 1)`。接真实日志时，把原 BBH 过滤结果映射到 `answer`、原判分映射到 `correct`，按固定题集运行上面的统计片段；重新用简化的 exact-match 判一次可能改变分子。要验证论文中的训练归因，还需真实 BBH 日志及恢复 EOS 监督的对照 checkpoint。

## 实验二：按数学操作弱项重采样

**问题。** 在相同的数学指令 token 预算下，优先采样薄弱操作组合，能否提高困难题的多次作答覆盖率？

| 阶段 | 论文做法 | 复跑时应保存 |
|---|---|---|
| 定位弱项 | 在 GSM8K、MathQA、MATH 的 9,304 道诊断题上标操作。先看单项错误率，再对比锚点操作独立出现和与另一操作共现时的正确率，最后考察三项组合相对成对效应的额外退化 | 按题保存操作集合和正确性，各切片保留支持数。单项、成对和三项统计分开 |
| 选择数据 | 用诊断误差、组合退化和支持数得到特征弱项分。将合成题的操作集合与特征匹配，最高阶命中优先，在该阶取最高弱项分。对匹配槽位使用 Efraimidis–Spirakis 加权无放回采样，单样本最多两份 | 特征、命中阶数、权重、seed、样本 ID、重复次数和实际 token 数。论文设置优先填满匹配预算，容量不足时由未匹配池补齐 |
| 固定变量续训 | base 与 exp 共用 warm-start、100B 续训 token、50/30/20 的通用/数学/代码配比。在同一 15B-token 合成数学池中选出 10B tokens，base 采用非定向采样，exp 采用诊断定向采样 | 两份数据清单、训练配置和 checkpoint；检查两边使用相同的 token 预算 |
| 比较结果 | 对相同题集分别比较 zero-shot pass@1/16/32/128；在 MATH500 回看目标操作切片，在通用集检查回退 | 每题每次采样的最终答案、题级 n 与正确次数、每个 k 的共同合格题集，以及生成与判分配置 |

`optimize-mixture` 调整生成任务之间的调用预算。论文所用的样本级加权采样器、操作标注全集及续训作业需要在外部数据和训练流水线中接入。[论文案例二](../README.md#6-case-study-2--diagnosis-aligned-targeted-sampling-for-mathematical-weakness)

**本地验证。** 先用自带的 AIME fixture 跑通按题重复作答和配对，再用公开完整响应检查答案提取。以下命令应产生 7 条结果、3 个配对、1 个未配对；同题 reasoning 的 base 和 candidate 分别答对 2/3 和 1/3，pass@2 分别为 1 和 2/3。每组均不足 32 次，pass@32 为 null。

```bash
python -m data_synthetic_pipeline run-loop \
  --task data_synthetic_pipeline/eval_assets/aime-integer.v1.json \
  --input fixtures/aime-smoke.jsonl --baseline base --target candidate \
  --pass-at-k 1 2 32 --output artifacts/aime-smoke
```

公开回放包含 AIME 2024 两道真题、两个模型、每模型每题三次采样，可验收 12 条原始响应和 6 个配对。[下载、校验和回放命令](AIME_INTEGRATION_zh.md#回放-2024-aime-的真实模型响应)

复核论文指标时，用外部生成的 AIME 2025/2026 多次作答替换 smoke 输入，请求 `--pass-at-k 1 16 32 128`，核对两边每题至少有 128 次同协议的有效提交；完全缺失的题须与冻结题表比对。论文中两个年份的 **base → exp** pass@128 都是 **6.67 → 26.67**（百分制），仓库 `summary.json` 的 `value` 使用 0–1 比例。额外记录目标切片的变化，才能检验收益是否出现在采样所针对的能力上。
