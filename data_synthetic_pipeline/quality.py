"""Independent deterministic + small-labeler + large-judge quality task."""

from __future__ import annotations

import ast
from typing import Any, Dict, List, Mapping, Optional, Sequence

from .llm import LLMClient
from .models import (
    QualityDecision,
    TaskCandidate,
    TaskDefinition,
    ValidationResult,
    stable_hash,
)
from .tasks.base import validate_json_schema_subset


class DeterministicQualityVerifier:
    """Low-cost checks shared by every quality policy."""

    _PLACEHOLDER_VALUES = {
        "",
        "todo",
        "tbd",
        "placeholder",
        "待补充",
        "略",
    }

    def verify(self, candidate: TaskCandidate) -> ValidationResult:
        payload = candidate.payload
        issues: List[str] = []
        instruction = str(payload.get("instruction", "")).strip()
        response = str(
            payload.get("response", payload.get("solution", ""))
        ).strip()
        if instruction.lower() in self._PLACEHOLDER_VALUES:
            issues.append("invalid_instruction")
        if response.lower() in self._PLACEHOLDER_VALUES:
            issues.append("invalid_response")

        checks: Dict[str, Any] = {
            "instruction_length": len(instruction),
            "response_length": len(response),
            "base_task_type": candidate.base_task_type,
        }
        if candidate.base_task_type == "math":
            if not str(payload.get("reference_answer", "")).strip():
                issues.append("missing_reference_answer")
            if not payload.get("knowledge_points"):
                issues.append("missing_knowledge_points")
        elif candidate.base_task_type == "code":
            solution = str(payload.get("solution", response))
            if not payload.get("public_tests"):
                issues.append("missing_public_tests")
            if not (
                payload.get("private_test_set_hash")
                or candidate.private_payload.get("private_tests")
            ):
                issues.append("missing_private_tests")
            if payload.get("language") == "python" and solution:
                try:
                    module = ast.parse(solution)
                    checks["python_static_parse"] = "passed"
                    entry_point = payload.get("entry_point")
                    functions = {
                        node.name
                        for node in ast.walk(module)
                        if isinstance(
                            node,
                            (ast.FunctionDef, ast.AsyncFunctionDef),
                        )
                    }
                    if entry_point and entry_point not in functions:
                        issues.append("entry_point_not_found")
                except SyntaxError:
                    checks["python_static_parse"] = "failed"
                    issues.append("python_syntax_error")
        return ValidationResult.from_issues(issues, checks=checks)


class QualityFilterTask:
    """Run one candidate through independent filter stages.

    Deterministic hard failures stop before model calls.  Every candidate that
    clears hard checks receives both a small-model label and a large-model
    judgment in the MVP so the two stages can later be calibrated.
    """

    def __init__(
        self,
        *,
        label_definition: TaskDefinition,
        judge_definition: TaskDefinition,
        labeler: LLMClient,
        judge: LLMClient,
        accept_probability_threshold: float = 0.7,
        verifier: Optional[DeterministicQualityVerifier] = None,
    ) -> None:
        if label_definition.kind != "labeler":
            raise ValueError("label_definition must have kind=labeler")
        if judge_definition.kind != "judge":
            raise ValueError("judge_definition must have kind=judge")
        if not 0 <= accept_probability_threshold <= 1:
            raise ValueError("accept_probability_threshold must be in [0, 1]")
        self.label_definition = label_definition
        self.judge_definition = judge_definition
        self.labeler = labeler
        self.judge = judge
        self.accept_probability_threshold = accept_probability_threshold
        self.verifier = verifier or DeterministicQualityVerifier()
        self.policy_version = stable_hash(
            label_definition.definition_id,
            judge_definition.definition_id,
            accept_probability_threshold,
            prefix="filter-policy",
        )

    def run(self, candidate: TaskCandidate) -> QualityDecision:
        verification = self.verifier.verify(candidate)
        rule_results = [
            {
                "name": "deterministic_quality",
                "passed": verification.passed,
                "issues": verification.issues,
                "checks": verification.checks,
            }
        ]
        if not verification.passed:
            return QualityDecision(
                candidate_id=candidate.candidate_id,
                decision="reject",
                hard_fail=True,
                rule_results=rule_results,
                small_model={},
                judge={},
                reject_reasons=list(verification.issues),
                policy_version=self.policy_version,
            )

        public_candidate = candidate.to_dict(include_private=False)
        context = {
            "candidate": public_candidate,
            "verification": verification.to_dict(),
        }
        label_response = self.labeler.generate_json(
            messages=(
                {
                    "role": "system",
                    "content": self.label_definition.system_prompt,
                },
                {
                    "role": "user",
                    "content": self.label_definition.render_user_prompt(context),
                },
            ),
            output_schema=self.label_definition.output_schema,
            model=self.label_definition.model,
            parameters=self.label_definition.parameters,
        )
        label_issues = validate_json_schema_subset(
            label_response.content,
            self.label_definition.output_schema,
        )
        if label_issues:
            raise ValueError(f"Invalid small-model labels: {label_issues}")

        judge_context = {
            **context,
            "small_model_labels": label_response.content,
        }
        judge_response = self.judge.generate_json(
            messages=(
                {
                    "role": "system",
                    "content": self.judge_definition.system_prompt,
                },
                {
                    "role": "user",
                    "content": self.judge_definition.render_user_prompt(
                        judge_context
                    ),
                },
            ),
            output_schema=self.judge_definition.output_schema,
            model=self.judge_definition.model,
            parameters=self.judge_definition.parameters,
        )
        judge_issues = validate_json_schema_subset(
            judge_response.content,
            self.judge_definition.output_schema,
        )
        if judge_issues:
            raise ValueError(f"Invalid judge result: {judge_issues}")

        probability = float(label_response.content.get("accept_probability", 0))
        judge_decision = str(
            judge_response.content.get("decision", "review")
        ).lower()
        hard_fail = bool(judge_response.content.get("hard_fail", False))
        reject_reasons: List[str] = []
        if probability < self.accept_probability_threshold:
            reject_reasons.append("small_model_below_threshold")
        if hard_fail:
            reject_reasons.append("judge_hard_fail")
        if judge_decision != "accept":
            reject_reasons.append(f"judge_decision:{judge_decision}")
        decision = "accept" if not reject_reasons else "reject"
        return QualityDecision(
            candidate_id=candidate.candidate_id,
            decision=decision,
            hard_fail=hard_fail,
            rule_results=rule_results,
            small_model={
                **label_response.content,
                "_model": label_response.model,
                "_request_id": label_response.request_id,
            },
            judge={
                **judge_response.content,
                "_model": judge_response.model,
                "_request_id": judge_response.request_id,
            },
            reject_reasons=reject_reasons,
            policy_version=self.policy_version,
        )

