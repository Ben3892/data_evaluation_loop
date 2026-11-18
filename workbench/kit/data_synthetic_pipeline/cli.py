"""Command-line interface for the data-only closed loop."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List, Optional

from .evaluation import DataQualityEvaluator
from .knowledge_extraction import KnowledgeExtractor
from .llm import LLMClient, OpenAICompatibleClient, ReplayLLMClient
from .models import (
    EvaluationReport,
    QualityDecision,
    TaskCandidate,
    TaskExecution,
    TaskRequest,
    ValidationResult,
    stable_hash,
)
from .optimization import MixturePlanner, PromptOptimizer
from .pipeline import IndependentTaskRunner
from .quality import QualityFilterTask
from .registry import TaskRegistry
from .storage import RunStore
from .utils import atomic_write_json, iter_jsonl, write_jsonl

DEFAULT_DEFINITIONS = Path(__file__).resolve().parent.parent / "task_definitions"


def _client(
    responses_path: Optional[str],
    *,
    env_prefix: str = "DSP_LLM",
) -> LLMClient:
    if responses_path:
        return ReplayLLMClient(iter_jsonl(responses_path))
    return OpenAICompatibleClient.from_env(env_prefix)


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as stream:
        return json.load(stream)


def _load_report(path: str) -> EvaluationReport:
    value = _load_json(path)
    return EvaluationReport(
        report_id=value["report_id"],
        created_at=value["created_at"],
        totals=dict(value["totals"]),
        per_task=dict(value["per_task"]),
        rejection_reasons=dict(value["rejection_reasons"]),
        metadata=dict(value.get("metadata", {})),
    )


def _execution_from_dict(value: dict) -> TaskExecution:
    candidate_value = value.get("candidate")
    candidate = (
        TaskCandidate.from_dict(candidate_value) if candidate_value else None
    )
    validation_value = value.get("validation", {})
    validation = ValidationResult(
        passed=bool(validation_value.get("passed", False)),
        issues=list(validation_value.get("issues", [])),
        checks=dict(validation_value.get("checks", {})),
    )
    return TaskExecution(
        candidate=candidate,
        validation=validation,
        raw_response_hash=value.get("raw_response_hash"),
        request_id=value.get("request_id"),
        error=value.get("error"),
    )


def command_list_tasks(args: argparse.Namespace) -> int:
    registry = TaskRegistry.from_directory(args.definitions)
    rows = [
        {
            "name": item.name,
            "version": item.version,
            "kind": item.kind,
            "definition_id": item.definition_id,
            "sampling": item.to_dict()["sampling"],
        }
        for item in registry.list()
    ]
    json.dump(rows, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


def command_extract_knowledge(args: argparse.Namespace) -> int:
    registry = TaskRegistry.from_directory(args.definitions)
    extractor = KnowledgeExtractor(
        registry.get("knowledge_extraction"),
        _client(args.responses),
    )
    text = Path(args.input).read_text(encoding="utf-8")
    points = extractor.extract(
        text=text,
        source_id=args.source_id,
        language=args.language,
        domain_hint=args.domain,
    )
    atomic_write_json(
        args.output,
        {
            "source_id": args.source_id,
            "knowledge_points": [item.to_dict() for item in points],
        },
    )
    print(f"wrote {len(points)} knowledge points to {args.output}")
    return 0


def command_run_task(args: argparse.Namespace) -> int:
    registry = TaskRegistry.from_directory(args.definitions)
    store = RunStore(args.output_root, args.run_id)
    requests: List[TaskRequest] = []
    for row in iter_jsonl(args.input):
        payload = dict(row)
        input_id = str(payload.pop("input_id", stable_hash(payload, prefix="input")))
        metadata = dict(payload.pop("metadata", {}))
        requests.append(TaskRequest(input_id, payload, metadata))
    runner = IndependentTaskRunner(
        registry,
        _client(args.responses),
        store=store,
    )
    executions = runner.run(args.task, requests)
    summary = {
        "run_id": args.run_id,
        "task": args.task,
        "requests": len(executions),
        "succeeded": sum(item.succeeded for item in executions),
        "executions": str(store.executions_path),
    }
    json.dump(summary, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0 if summary["succeeded"] == summary["requests"] else 2


def command_filter(args: argparse.Namespace) -> int:
    registry = TaskRegistry.from_directory(args.definitions)
    quality_filter = QualityFilterTask(
        label_definition=registry.get("quality_labeler"),
        judge_definition=registry.get("quality_judge"),
        labeler=_client(args.labeler_responses, env_prefix="DSP_SMALL_LLM"),
        judge=_client(args.judge_responses, env_prefix="DSP_JUDGE_LLM"),
        accept_probability_threshold=args.accept_threshold,
    )
    decisions: List[dict] = []
    for row in iter_jsonl(args.executions):
        candidate_value = row.get("candidate")
        if not candidate_value:
            continue
        candidate = TaskCandidate.from_dict(candidate_value)
        decisions.append(quality_filter.run(candidate).to_dict())
    write_jsonl(args.output, decisions)
    print(f"wrote {len(decisions)} quality decisions to {args.output}")
    return 0


def command_evaluate(args: argparse.Namespace) -> int:
    executions = [
        _execution_from_dict(row) for row in iter_jsonl(args.executions)
    ]
    decisions = [
        QualityDecision(
            candidate_id=row["candidate_id"],
            decision=row["decision"],
            hard_fail=bool(row["hard_fail"]),
            rule_results=list(row.get("rule_results", [])),
            small_model=dict(row.get("small_model", {})),
            judge=dict(row.get("judge", {})),
            reject_reasons=list(row.get("reject_reasons", [])),
            policy_version=row["policy_version"],
            created_at=row.get("created_at", ""),
        )
        for row in iter_jsonl(args.quality)
    ]
    report = DataQualityEvaluator().evaluate(
        executions,
        decisions,
        metadata={"source": args.executions},
    )
    atomic_write_json(args.output, report.to_dict())
    print(f"wrote evaluation report {report.report_id} to {args.output}")
    return 0


def command_optimize_prompt(args: argparse.Namespace) -> int:
    registry = TaskRegistry.from_directory(args.definitions)
    optimizer = PromptOptimizer(
        registry.get("prompt_optimizer"),
        _client(args.responses, env_prefix="DSP_OPTIMIZER_LLM"),
    )
    error_examples = list(iter_jsonl(args.error_examples)) if args.error_examples else []
    proposal = optimizer.propose(
        target=registry.get(args.task),
        report=_load_report(args.report),
        error_examples=error_examples,
    )
    atomic_write_json(args.output, proposal.to_dict())
    print(f"wrote prompt proposal {proposal.proposal_id} to {args.output}")
    return 0


def command_optimize_mixture(args: argparse.Namespace) -> int:
    registry = TaskRegistry.from_directory(args.definitions)
    planner = MixturePlanner(
        registry.get("mixture_planner"),
        _client(args.responses, env_prefix="DSP_OPTIMIZER_LLM"),
    )
    proposal = planner.propose(
        tasks=registry.list(kind="generator"),
        report=_load_report(args.report),
    )
    atomic_write_json(args.output, proposal.to_dict())
    print(f"wrote mixture proposal {proposal.proposal_id} to {args.output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="dsp-data",
        description="Data-only synthetic generation and optimization loop",
    )
    parser.add_argument(
        "--definitions",
        default=str(DEFAULT_DEFINITIONS),
        help="Directory containing versioned task-definition JSON files",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list-tasks")
    list_parser.set_defaults(handler=command_list_tasks)

    extract_parser = subparsers.add_parser("extract-knowledge")
    extract_parser.add_argument("--input", required=True)
    extract_parser.add_argument("--source-id", required=True)
    extract_parser.add_argument("--language", default="zh-CN")
    extract_parser.add_argument("--domain", default="math")
    extract_parser.add_argument("--responses")
    extract_parser.add_argument("--output", required=True)
    extract_parser.set_defaults(handler=command_extract_knowledge)

    run_parser = subparsers.add_parser("run-task")
    run_parser.add_argument(
        "--task",
        required=True,
        choices=["math_knowledge", "rewrite", "code_generation"],
    )
    run_parser.add_argument("--input", required=True)
    run_parser.add_argument("--responses")
    run_parser.add_argument("--output-root", default="artifacts/runs")
    run_parser.add_argument("--run-id", required=True)
    run_parser.set_defaults(handler=command_run_task)

    filter_parser = subparsers.add_parser("filter")
    filter_parser.add_argument("--executions", required=True)
    filter_parser.add_argument("--labeler-responses")
    filter_parser.add_argument("--judge-responses")
    filter_parser.add_argument("--accept-threshold", type=float, default=0.7)
    filter_parser.add_argument("--output", required=True)
    filter_parser.set_defaults(handler=command_filter)

    evaluate_parser = subparsers.add_parser("evaluate")
    evaluate_parser.add_argument("--executions", required=True)
    evaluate_parser.add_argument("--quality", required=True)
    evaluate_parser.add_argument("--output", required=True)
    evaluate_parser.set_defaults(handler=command_evaluate)

    prompt_parser = subparsers.add_parser("optimize-prompt")
    prompt_parser.add_argument("--task", required=True)
    prompt_parser.add_argument("--report", required=True)
    prompt_parser.add_argument("--error-examples")
    prompt_parser.add_argument("--responses")
    prompt_parser.add_argument("--output", required=True)
    prompt_parser.set_defaults(handler=command_optimize_prompt)

    mixture_parser = subparsers.add_parser("optimize-mixture")
    mixture_parser.add_argument("--report", required=True)
    mixture_parser.add_argument("--responses")
    mixture_parser.add_argument("--output", required=True)
    mixture_parser.set_defaults(handler=command_optimize_mixture)
    from .eval_loop import register
    register(subparsers)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())

