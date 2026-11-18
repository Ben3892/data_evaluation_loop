# 最小评测闭环实现台

构建免依赖的浏览器本地工作台，源自 Sites 版本。

```sh
python scripts/build_workbench_bundle.py
python -m http.server 8080 --directory workbench
```

打开 http://localhost:8080 。不要用 file://，页面通过 fetch 读取快照与资源。

核对基线为 e0bf620（2026-08-24）的历史快照，不随 GitHub 提交自动更新。当前仓库已经接入 run-loop；工作台中的“原始实现状态”仍用于比较这个历史基线。导入材料不会自动提升为已验证。下载包由当前仓库代码生成，应用前先检查现有文件；原 CLI 已接入，无需再应用旧版 cli.patch。

支持文本文件导入/粘贴、文件对比、契约核对、JSON Schema 子集校验、浏览器 smoke、四格转移/按题统计、首错与主因回放、日志关联和 Markdown 报告。完整 JSON Schema 校验在 Python jsonschema 中执行。浏览器不执行导入的 Python/Shell，不调用模型。

数据仅保存于本浏览器 localStorage；可通过“导出工作区”备份 JSON，并重新导入。未接入数据库、任务调度器或沙盒服务。

regression.log 为 Sites 构建时 20 项测试的历史证据，不代表之后修改的测试结论。下载包的最新验证请参考 docs/EVALUATION_LOOP_IMPLEMENTATION_zh.md。
