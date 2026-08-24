"""Base implementation for an independently runnable LLM data task."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ..llm import LLMClient, LLMResponse
from ..models import (
    TaskCandidate,
    TaskDefinition,
    TaskExecution,
    TaskRequest,
    ValidationResult,
    stable_hash,
)

_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "null": type(None),
}


def validate_json_schema_subset(
    value: Mapping[str, Any],
    schema: Mapping[str, Any],
) -> List[str]:
    """Validate the JSON-Schema subset used by task definitions."""

    issues: List[str] = []
    for field_name in schema.get("required", []):
        if field_name not in value:
            issues.append(f"missing_required_field:{field_name}")
    for field_name, field_schema in schema.get("properties", {}).items():
        if field_name not in value:
            continue
        expected_name = field_schema.get("type")
        if expected_name in _JSON_TYPES:
            expected_type = _JSON_TYPES[expected_name]
            field_value = value[field_name]
            if expected_name in {"integer", "number"} and isinstance(field_value, bool):
                issues.append(f"invalid_type:{field_name}:{expected_name}")
            elif not isinstance(field_value, expected_type):
                issues.append(f"invalid_type:{field_name}:{expected_name}")
        if "enum" in field_schema and value[field_name] not in field_schema["enum"]:
            issues.append(f"invalid_enum:{field_name}")
        if isinstance(value[field_name], (int, float)) and not isinstance(
            value[field_name], bool
        ):
            if "minimum" in field_schema and value[field_name] < field_schema["minimum"]:
                issues.append(f"below_minimum:{field_name}")
            if "maximum" in field_schema and value[field_name] > field_schema["maximum"]:
                issues.append(f"above_maximum:{field_name}")
    return issues


class LLMDataTask(ABC):
    """Generate one candidate from one request using a versioned definition."""

    base_task_type: str
    generation_mode: str

    def __init__(self, definition: TaskDefinition, llm: LLMClient) -> None:
        if definition.kind != "generator":
            raise ValueError(
                f"{definition.name} is kind={definition.kind}, expected generator"
            )
        self.definition = definition
        self.llm = llm

    def build_context(self, request: TaskRequest) -> Dict[str, Any]:
        return {
            **request.payload,
            "input_id": request.input_id,
            "metadata": request.metadata,
        }

    def build_messages(self, request: TaskRequest) -> Sequence[Mapping[str, str]]:
        user_prompt = self.definition.render_user_prompt(self.build_context(request))
        return (
            {"role": "system", "content": self.definition.system_prompt},
            {"role": "user", "content": user_prompt},
        )

    def run(self, request: TaskRequest) -> TaskExecution:
        try:
            response = self.llm.generate_json(
                messages=self.build_messages(request),
                output_schema=self.definition.output_schema,
                model=self.definition.model,
                parameters=self.definition.parameters,
            )
            schema_issues = validate_json_schema_subset(
                response.content,
                self.definition.output_schema,
            )
            candidate = self.build_candidate(request, response)
            validation = self.validate_candidate(request, candidate)
            validation.issues[:0] = schema_issues
            validation.passed = not validation.issues
            return TaskExecution(
                candidate=candidate,
                validation=validation,
                raw_response_hash=response.raw_response_hash,
                request_id=response.request_id,
            )
        except Exception as exc:
            return TaskExecution(
                candidate=None,
                validation=ValidationResult(
                    passed=False,
                    issues=[f"task_error:{type(exc).__name__}"],
                ),
                error=str(exc),
            )

    def make_candidate(
        self,
        *,
        request: TaskRequest,
        response: LLMResponse,
        payload: Dict[str, Any],
        base_task_type: Optional[str] = None,
        generation_mode: Optional[str] = None,
        parent_ids: Optional[List[str]] = None,
        transformations: Optional[List[str]] = None,
        private_payload: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TaskCandidate:
        candidate_id = stable_hash(
            self.definition.definition_id,
            request.input_id,
            payload,
            parent_ids or [],
            prefix="candidate",
        )
        generation_metadata = {
            "definition_id": self.definition.definition_id,
            "model": response.model,
            "request_id": response.request_id,
            "usage": response.usage,
            "input_id": request.input_id,
            **request.metadata,
            **(metadata or {}),
        }
        return TaskCandidate(
            candidate_id=candidate_id,
            task_name=self.definition.name,
            task_version=self.definition.version,
            base_task_type=base_task_type or self.base_task_type,
            generation_mode=generation_mode or self.generation_mode,
            payload=payload,
            parent_ids=parent_ids or [],
            transformations=transformations or [],
            metadata=generation_metadata,
            private_payload=private_payload or {},
        )

    @abstractmethod
    def build_candidate(
        self,
        request: TaskRequest,
        response: LLMResponse,
    ) -> TaskCandidate:
        ...

    @abstractmethod
    def validate_candidate(
        self,
        request: TaskRequest,
        candidate: TaskCandidate,
    ) -> ValidationResult:
        ...
