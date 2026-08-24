"""Question-solution-test code task generation."""

from __future__ import annotations

import ast
from typing import Any, Dict, List

from ..llm import LLMResponse
from ..models import TaskCandidate, TaskRequest, ValidationResult, stable_hash
from .base import LLMDataTask


class CodeGenerationTask(LLMDataTask):
    base_task_type = "code"
    generation_mode = "from_spec"

    def build_candidate(
        self,
        request: TaskRequest,
        response: LLMResponse,
    ) -> TaskCandidate:
        content = response.content
        public_tests = list(content.get("public_tests", []))
        private_tests = list(content.get("private_tests", []))
        private_hash = (
            stable_hash(private_tests, prefix="private-tests")
            if private_tests
            else None
        )
        payload = {
            "instruction": str(content.get("instruction", "")).strip(),
            "solution": str(content.get("solution", "")).strip(),
            "response": str(content.get("solution", "")).strip(),
            "language": str(
                content.get(
                    "language",
                    request.payload.get("language", "python"),
                )
            ).lower(),
            "entry_point": str(content.get("entry_point", "")).strip(),
            "public_tests": public_tests,
            "private_test_set_hash": private_hash,
            "algorithm_tags": list(content.get("algorithm_tags", [])),
            "difficulty": content.get(
                "difficulty",
                request.payload.get("difficulty", 1),
            ),
        }
        return self.make_candidate(
            request=request,
            response=response,
            payload=payload,
            private_payload={"private_tests": private_tests},
        )

    def validate_candidate(
        self,
        request: TaskRequest,
        candidate: TaskCandidate,
    ) -> ValidationResult:
        payload = candidate.payload
        issues: List[str] = []
        for field_name in ("instruction", "solution", "language", "entry_point"):
            if not payload.get(field_name):
                issues.append(f"empty_field:{field_name}")
        if not payload.get("public_tests"):
            issues.append("empty_field:public_tests")
        if not candidate.private_payload.get("private_tests"):
            issues.append("empty_field:private_tests")

        checks: Dict[str, Any] = {
            "static_parse": "not_run",
            "entry_point_found": False,
            "private_test_count": len(
                candidate.private_payload.get("private_tests", [])
            ),
        }
        if payload.get("language") == "python" and payload.get("solution"):
            try:
                module = ast.parse(payload["solution"])
                checks["static_parse"] = "passed"
                functions = {
                    node.name
                    for node in ast.walk(module)
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                }
                checks["entry_point_found"] = payload.get("entry_point") in functions
                if payload.get("entry_point") and not checks["entry_point_found"]:
                    issues.append("entry_point_not_found")
            except SyntaxError:
                checks["static_parse"] = "failed"
                issues.append("python_syntax_error")

        difficulty = payload.get("difficulty")
        if not isinstance(difficulty, int) or isinstance(difficulty, bool):
            issues.append("difficulty_must_be_integer")
        elif not 1 <= difficulty <= 5:
            issues.append("difficulty_out_of_range")
        return ValidationResult.from_issues(issues, checks=checks)

