"""Core contracts for independent data tasks."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

_TEMPLATE_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.]*)\s*\}\}")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def stable_hash(*values: Any, prefix: str = "sha256") -> str:
    digest = hashlib.sha256()
    for value in values:
        digest.update(canonical_json(value).encode("utf-8"))
        digest.update(b"\x1e")
    return f"{prefix}:{digest.hexdigest()}"


def _resolve_template_value(context: Mapping[str, Any], path: str) -> Any:
    value: Any = context
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            raise KeyError(f"Missing template variable: {path}")
        value = value[part]
    return value


def render_template(template: str, context: Mapping[str, Any]) -> str:
    """Render strict double-brace variables without executing template code."""

    def replace(match: re.Match) -> str:
        value = _resolve_template_value(context, match.group(1))
        if isinstance(value, (dict, list, tuple, bool, int, float)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        if value is None:
            return "null"
        return str(value)

    return _TEMPLATE_PATTERN.sub(replace, template)


@dataclass(frozen=True)
class SamplingPolicy:
    weight: float = 1.0
    min_weight: float = 0.0
    max_weight: float = 1.0
    max_delta: float = 1.0

    def validate(self) -> None:
        if self.min_weight < 0 or self.max_weight > 1:
            raise ValueError("Sampling bounds must be inside [0, 1]")
        if self.min_weight > self.max_weight:
            raise ValueError("min_weight cannot exceed max_weight")
        if not self.min_weight <= self.weight <= self.max_weight:
            raise ValueError("weight must be inside [min_weight, max_weight]")
        if self.max_delta < 0:
            raise ValueError("max_delta must be non-negative")


@dataclass(frozen=True)
class TaskDefinition:
    name: str
    version: str
    kind: str
    description: str
    system_prompt: str
    user_prompt: str
    output_schema: Dict[str, Any]
    model: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    sampling: SamplingPolicy = field(default_factory=SamplingPolicy)
    editable_fields: Sequence[str] = field(
        default_factory=lambda: (
            "system_prompt",
            "user_prompt",
            "parameters",
            "sampling.weight",
        )
    )

    @property
    def definition_id(self) -> str:
        return stable_hash(self.to_dict(), prefix="task")

    def validate(self) -> None:
        if not self.name or not self.version or not self.kind:
            raise ValueError("Task definition requires name, version, and kind")
        if not self.system_prompt.strip() or not self.user_prompt.strip():
            raise ValueError("Task prompts cannot be empty")
        if not isinstance(self.output_schema, dict):
            raise ValueError("output_schema must be an object")
        self.sampling.validate()

    def render_user_prompt(self, context: Mapping[str, Any]) -> str:
        return render_template(self.user_prompt, context)

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["editable_fields"] = list(self.editable_fields)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskDefinition":
        sampling = SamplingPolicy(**dict(value.get("sampling", {})))
        definition = cls(
            name=str(value["name"]),
            version=str(value["version"]),
            kind=str(value["kind"]),
            description=str(value.get("description", "")),
            system_prompt=str(value["system_prompt"]),
            user_prompt=str(value["user_prompt"]),
            output_schema=dict(value.get("output_schema", {})),
            model=value.get("model"),
            parameters=dict(value.get("parameters", {})),
            sampling=sampling,
            editable_fields=tuple(value.get("editable_fields", ())),
        )
        definition.validate()
        return definition


@dataclass(frozen=True)
class TaskRequest:
    input_id: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ValidationResult:
    passed: bool
    issues: List[str] = field(default_factory=list)
    checks: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_issues(
        cls,
        issues: Iterable[str],
        *,
        checks: Optional[Dict[str, Any]] = None,
    ) -> "ValidationResult":
        issue_list = list(issues)
        return cls(not issue_list, issue_list, checks or {})

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TaskCandidate:
    candidate_id: str
    task_name: str
    task_version: str
    base_task_type: str
    generation_mode: str
    payload: Dict[str, Any]
    parent_ids: List[str] = field(default_factory=list)
    transformations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    private_payload: Dict[str, Any] = field(default_factory=dict, repr=False)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self, *, include_private: bool = False) -> Dict[str, Any]:
        value = asdict(self)
        if not include_private:
            value.pop("private_payload", None)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "TaskCandidate":
        return cls(
            candidate_id=str(value["candidate_id"]),
            task_name=str(value["task_name"]),
            task_version=str(value["task_version"]),
            base_task_type=str(value["base_task_type"]),
            generation_mode=str(value["generation_mode"]),
            payload=dict(value["payload"]),
            parent_ids=list(value.get("parent_ids", [])),
            transformations=list(value.get("transformations", [])),
            metadata=dict(value.get("metadata", {})),
            private_payload=dict(value.get("private_payload", {})),
            created_at=str(value.get("created_at", utc_now())),
        )


@dataclass
class TaskExecution:
    candidate: Optional[TaskCandidate]
    validation: ValidationResult
    raw_response_hash: Optional[str] = None
    request_id: Optional[str] = None
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.candidate is not None and self.validation.passed and not self.error

    def to_dict(self, *, include_private: bool = False) -> Dict[str, Any]:
        return {
            "candidate": (
                self.candidate.to_dict(include_private=include_private)
                if self.candidate
                else None
            ),
            "validation": self.validation.to_dict(),
            "raw_response_hash": self.raw_response_hash,
            "request_id": self.request_id,
            "error": self.error,
            "succeeded": self.succeeded,
        }


@dataclass
class QualityDecision:
    candidate_id: str
    decision: str
    hard_fail: bool
    rule_results: List[Dict[str, Any]]
    small_model: Dict[str, Any]
    judge: Dict[str, Any]
    reject_reasons: List[str]
    policy_version: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvaluationReport:
    report_id: str
    created_at: str
    totals: Dict[str, Any]
    per_task: Dict[str, Dict[str, Any]]
    rejection_reasons: Dict[str, int]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

