# data_evaluation_loop 最小评测闭环实施报告

## 目标与基线

在 `e0bf62038cb49dbfe50e157caf46f02d3a9d695e` 的数据侧闭环上新增独立的题级离线评测链路：读取 fixture → 原子评分 → 结果 Schema 与跨字段校验 → 逐行落盘 → 按题/按转移统计。原有生成、过滤、内在质量评估接口继续保留。

## 文件与接口

| 文件 | 改动 | 验收 |
| --- | --- | --- |
| `data_synthetic_pipeline/eval_loop.py` | 新增 `evaluate`、`validate_result`、`summarize` 和 `run-loop` | 原子评分、首错/主因约束、配对、结构化失败 |
| `data_synthetic_pipeline/cli.py` | 注册 `run-loop` 子命令 | `python -m data_synthetic_pipeline run-loop` 可执行 |
| `schemas/evaluation-result.schema.json` | 对外结果契约，Draft-07 | 字段类型、枚举、required、额外字段限制 |
| `data_synthetic_pipeline/eval_assets/` | 安装包自带 Schema 与原子任务配置 | 在源码目录外使用 wheel 仍可找到资源 |
| `fixtures/atomic-exact.v1.json` | `atomic_exact.v1` 任务，strip + exact_match | 不使用在线模型或语义 judge |
| `fixtures/eval-smoke.jsonl` | 8 条人工合成接口记录 | 4 题 × 两个 run，四类转移各 1 |
| `tests/test_eval_loop.py` | 新增 16 项契约与 CLI 回归 | 通过、拒绝非法输入、错误码、依赖隔离 |
| `pyproject.toml` | 可选 `eval` 依赖、包资源 | 原命令无强制新依赖，`.[eval]` 可安装 |
| `workbench/` | 浏览器工作台源码与历史快照 | 导入/粘贴、核对、对比、校验、smoke、报告与回放 |
| `scripts/build_workbench_bundle.py` | 从当前源码刷新下载资源 | 不依赖在线服务，不含 Sites 部署标识 |

## 运行

Python 3.9+。在仓库根目录执行：

```sh
python -m pip install '.[eval]'
python -m data_synthetic_pipeline run-loop \
  --input fixtures/eval-smoke.jsonl \
  --baseline base --target candidate \
  --output artifacts/eval-smoke
python -m unittest discover -s tests -v
```

已安装命令入口时，也可用 `dsp-data run-loop ...`。独立模块入口为 `python -m data_synthetic_pipeline.eval_loop run-loop ...`。不提供 baseline/target 时只做题级汇总；选择转移分析时两者必须同时提供、不同且有有效配对。

成功退出码为 0，输出目录包含 `results.jsonl` 与 `summary.json`。异常退出码为 2，stdout 返回 `status=failed`、`failure_type`、`message`。读入和校验失败不会创建本次输出目录。

工作台：

```sh
python scripts/build_workbench_bundle.py
python -m http.server 8080 --directory workbench
```

打开 http://localhost:8080 。工作台预载的是旧提交 `e0bf620` 的历史快照，用于对照原始缺口；页面不自动读取当前 GitHub 最新提交。历史“缺失”状态不能解释为当前仓库仍缺少这些文件。浏览器内校验只支持列明的 Draft-07 子集；Python 使用 jsonschema 完整校验。

## 关键约束

- 结果键：`run_id/task_id/sample_id/attempt_id/protocol` 唯一；保留 direct/reasoning 协议，不跨协议配对。
- 按题分组：`run_id/task_id/sample_id/protocol`；输出重复作答次数 n、正确次数和 accuracy。
- 转移匹配：`task_id/sample_id/attempt_id/protocol`；必须 reference 一致。输出四格计数、paired、unmatched；零配对拒绝作为成功转移分析。
- `steps.step_id` 唯一有序。incorrect 步骤必须有错误类型和证据。
- `first_error` 是最早**已标注**错误；unknown 不被解释为正确。null 只表示没有已确认错误，不能证明过程正确。
- `primary_error` 是外部明确选出的主要错误，可以与首错不同；必须指向一个已确认错误。unreviewed 不得写入错误断言。
- 评分只比较 strip 后答案是否相同。fixture 的知识/指令/数学/科学动作标签均是人工接口样例，不是实际 benchmark 诊断结果。

## 实测证据（2026-11-18）

- 原有 10 项测试 + 新增 16 项回归：**26 项全部通过**。完整日志见 [evaluation-loop-unittest.log](validation/evaluation-loop-unittest.log)。
- 通过实际统一 CLI 执行：8 条结果、4 个匹配对、0 unmatched，四类转移各 1。
- 非法 JSON：实际 CLI 返回退出码 2 与结构化错误，未写入成功产物。
- 使用 `python -S` 移除第三方包路径后，旧 `list-tasks` 仍正常运行；`run-loop` 明确提示安装 `.[eval]`。
- 通过 `pip wheel --no-deps --no-build-isolation` 构建；在临时目录解包 wheel、离开源码目录运行 `run-loop`，8 条结果 / 4 对通过，确认包内任务与 Schema 可访问。
- 浏览器核心 JS 通过 Node 执行相同 fixture，得到 8 条结果 / 4 对；`app.js`、`core.mjs` 语法检查通过。工作台初始 Sites 版本已做浏览器导入、筛选、有效/非法 Schema、smoke 与历史回放验证；本次源码资源接入未重新部署 Sites。

以上仅覆盖离线契约和接口可靠性，不是模型能力、归因正确性或真实 benchmark 完整性的证明。workbench/regression.log 是此前 Sites 版本的 20 项历史测试日志，与本次 26 项验收分开记录。

## 未完成与后续边界

尚未实现 SimpleQA 语义判分、AdvancedIF/MultiChallenge/CLBench 约束检查器、math-verify 接入、科学推理 judge、在线模型 rollout 或自动步骤标注。候选干预能否改善模型需要冻结真实样本和受控实验。没有数据库、调度器、自建 Docker/Kubernetes 或未信任代码执行功能。
