"""Semantics-preserving style, diversity, and language rewriting."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping

from ..llm import LLMResponse
from ..models import TaskCandidate, TaskRequest, ValidationResult, stable_hash
from .base import LLMDataTask

_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:\.\d+)?")


class RewriteTask(LLMDataTask):
    base_task_type = "general"
    generation_mode = "rewrite"

    def build_context(self, request: TaskRequest) -> Dict[str, Any]:
        parent = self._parent(request)
        return {
            **request.payload,
            "input_id": request.input_id,
            "parent": parent,
            "parent_payload": parent["payload"],
            "metadata": request.metadata,
        }

    def build_candidate(
        self,
        request: TaskRequest,
        response: LLMResponse,
    ) -> TaskCandidate:
        parent = self._parent(request)
        parent_payload = dict(parent["payload"])
        content = response.content
        transformations = list(
            content.get("transformations")
            or request.payload.get("transformations", [])
        )
        payload = {
            **parent_payload,
            "instruction": str(content.get("instruction", "")).strip(),
            "language": str(
                content.get(
                    "language",
                    request.payload.get(
                        "target_language",
                        parent_payload.get("language", "zh-CN"),
                    ),
                )
            ),
            "style": str(
                content.get(
                    "style",
                    request.payload.get(
                        "target_style",
                        parent_payload.get("style", "default"),
                    ),
                )
            ),
            "rewrite_summary": str(content.get("rewrite_summary", "")).strip(),
        }
        parent_id = str(parent["candidate_id"])
        lineage_group_id = parent.get("metadata", {}).get(
            "lineage_group_id",
            stable_hash(parent_id, prefix="lineage"),
        )
        return self.make_candidate(
            request=request,
            response=response,
            payload=payload,
            base_task_type=str(parent["base_task_type"]),
            generation_mode="rewrite",
            parent_ids=[parent_id],
            transformations=transformations,
            metadata={"lineage_group_id": lineage_group_id},
        )

    def validate_candidate(
        self,
        request: TaskRequest,
        candidate: TaskCandidate,
    ) -> ValidationResult:
        parent = self._parent(request)
        original = str(parent["payload"].get("instruction", "")).strip()
        rewritten = str(candidate.payload.get("instruction", "")).strip()
        issues: List[str] = []
        if not rewritten:
            issues.append("empty_field:instruction")
        if rewritten == original:
            issues.append("rewrite_is_identical")
        if candidate.payload.get("reference_answer") != parent["payload"].get(
            "reference_answer"
        ):
            issues.append("reference_answer_changed")
        if candidate.payload.get("response") != parent["payload"].get("response"):
            issues.append("response_changed")

        if request.payload.get("preserve_numbers", True):
            original_numbers = sorted(_NUMBER_PATTERN.findall(original))
            rewritten_numbers = sorted(_NUMBER_PATTERN.findall(rewritten))
            if original_numbers != rewritten_numbers:
                issues.append("numeric_literals_changed")
        else:
            original_numbers = []
            rewritten_numbers = []

        target_language = request.payload.get("target_language")
        if target_language and candidate.payload.get("language") != target_language:
            issues.append("target_language_not_met")
        target_style = request.payload.get("target_style")
        if target_style and candidate.payload.get("style") != target_style:
            issues.append("target_style_not_met")

        return ValidationResult.from_issues(
            issues,
            checks={
                "original_numbers": original_numbers,
                "rewritten_numbers": rewritten_numbers,
                "parent_candidate_id": parent["candidate_id"],
            },
        )

    @staticmethod
    def _parent(request: TaskRequest) -> Mapping[str, Any]:
        parent = request.payload.get("parent")
        if isinstance(parent, TaskCandidate):
            parent = parent.to_dict()
        if not isinstance(parent, Mapping):
            raise ValueError("Rewrite task requires payload.parent")
        required = {"candidate_id", "base_task_type", "payload"}
        missing = required - set(parent)
        if missing:
            raise ValueError(f"Invalid parent candidate, missing: {sorted(missing)}")
        return parent

