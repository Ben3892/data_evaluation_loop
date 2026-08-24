"""Knowledge-point extraction independent from math question synthesis."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .llm import LLMClient
from .models import TaskDefinition, stable_hash
from .tasks.base import validate_json_schema_subset


@dataclass(frozen=True)
class KnowledgePoint:
    knowledge_id: str
    name: str
    domain: str
    description: str
    prerequisites: Sequence[str] = field(default_factory=tuple)
    solving_operations: Sequence[str] = field(default_factory=tuple)
    difficulty_min: int = 1
    difficulty_max: int = 5
    source_id: str = ""

    def validate(self) -> None:
        if not self.knowledge_id or not self.name or not self.domain:
            raise ValueError("knowledge_id, name, and domain are required")
        if not 1 <= self.difficulty_min <= self.difficulty_max <= 5:
            raise ValueError("difficulty range must satisfy 1 <= min <= max <= 5")

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["prerequisites"] = list(self.prerequisites)
        value["solving_operations"] = list(self.solving_operations)
        return value


class KnowledgeExtractor:
    """Extract a versioned knowledge catalog fragment from source text."""

    def __init__(self, definition: TaskDefinition, llm: LLMClient) -> None:
        if definition.kind != "extractor":
            raise ValueError("KnowledgeExtractor requires an extractor definition")
        self.definition = definition
        self.llm = llm

    def extract(
        self,
        *,
        text: str,
        source_id: str,
        language: str = "zh-CN",
        domain_hint: str = "math",
    ) -> List[KnowledgePoint]:
        context = {
            "source_text": text,
            "source_id": source_id,
            "language": language,
            "domain_hint": domain_hint,
        }
        messages = (
            {"role": "system", "content": self.definition.system_prompt},
            {
                "role": "user",
                "content": self.definition.render_user_prompt(context),
            },
        )
        response = self.llm.generate_json(
            messages=messages,
            output_schema=self.definition.output_schema,
            model=self.definition.model,
            parameters=self.definition.parameters,
        )
        schema_issues = validate_json_schema_subset(
            response.content,
            self.definition.output_schema,
        )
        if schema_issues:
            raise ValueError(f"Invalid extraction response: {schema_issues}")
        points = response.content.get("knowledge_points", [])
        if not isinstance(points, list):
            raise ValueError("knowledge_points must be a list")
        extracted: List[KnowledgePoint] = []
        for raw in points:
            if not isinstance(raw, Mapping):
                raise ValueError("Each knowledge point must be an object")
            name = str(raw.get("name", "")).strip()
            domain = str(raw.get("domain", domain_hint)).strip()
            raw_id = str(raw.get("knowledge_id", "")).strip()
            knowledge_id = raw_id or stable_hash(
                domain,
                name,
                prefix="knowledge",
            )
            point = KnowledgePoint(
                knowledge_id=knowledge_id,
                name=name,
                domain=domain,
                description=str(raw.get("description", "")).strip(),
                prerequisites=tuple(raw.get("prerequisites", [])),
                solving_operations=tuple(raw.get("solving_operations", [])),
                difficulty_min=int(raw.get("difficulty_min", 1)),
                difficulty_max=int(raw.get("difficulty_max", 5)),
                source_id=source_id,
            )
            point.validate()
            extracted.append(point)
        return extracted
