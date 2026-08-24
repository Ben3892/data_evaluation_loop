"""Math synthesis from explicit knowledge points."""

from __future__ import annotations

from typing import List

from ..llm import LLMResponse
from ..models import TaskCandidate, TaskRequest, ValidationResult
from .base import LLMDataTask


class MathKnowledgeTask(LLMDataTask):
    base_task_type = "math"
    generation_mode = "from_knowledge"

    def build_candidate(
        self,
        request: TaskRequest,
        response: LLMResponse,
    ) -> TaskCandidate:
        content = response.content
        requested_points = request.payload.get("knowledge_points", [])
        payload = {
            "instruction": str(content.get("instruction", "")).strip(),
            "response": str(content.get("response", "")).strip(),
            "reference_answer": str(content.get("reference_answer", "")).strip(),
            "knowledge_points": list(
                content.get("knowledge_points") or requested_points
            ),
            "solving_operations": list(content.get("solving_operations", [])),
            "difficulty": content.get(
                "difficulty",
                request.payload.get("difficulty", 1),
            ),
            "language": str(
                content.get("language", request.payload.get("language", "zh-CN"))
            ),
            "verification_level": str(
                content.get("verification_level", "judge_only")
            ),
        }
        return self.make_candidate(
            request=request,
            response=response,
            payload=payload,
        )

    def validate_candidate(
        self,
        request: TaskRequest,
        candidate: TaskCandidate,
    ) -> ValidationResult:
        payload = candidate.payload
        issues: List[str] = []
        for field_name in ("instruction", "response", "reference_answer"):
            if not payload.get(field_name):
                issues.append(f"empty_field:{field_name}")
        if not payload.get("knowledge_points"):
            issues.append("empty_field:knowledge_points")
        difficulty = payload.get("difficulty")
        if not isinstance(difficulty, int) or isinstance(difficulty, bool):
            issues.append("difficulty_must_be_integer")
        elif not 1 <= difficulty <= 5:
            issues.append("difficulty_out_of_range")

        requested = set(request.payload.get("knowledge_points", []))
        returned = set(payload.get("knowledge_points", []))
        missing = sorted(requested - returned)
        if missing:
            issues.append(f"missing_requested_knowledge_points:{','.join(missing)}")

        checks = {
            "requested_knowledge_points": sorted(requested),
            "returned_knowledge_points": sorted(returned),
            "has_reference_answer": bool(payload.get("reference_answer")),
        }
        return ValidationResult.from_issues(issues, checks=checks)

