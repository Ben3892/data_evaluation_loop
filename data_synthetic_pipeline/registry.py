"""Versioned task-definition registry."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from .models import TaskDefinition
from .utils import atomic_write_json


class TaskRegistry:
    def __init__(self, definitions: Optional[Iterable[TaskDefinition]] = None) -> None:
        self._definitions: Dict[str, Dict[str, TaskDefinition]] = {}
        for definition in definitions or ():
            self.register(definition)

    def register(self, definition: TaskDefinition) -> None:
        definition.validate()
        versions = self._definitions.setdefault(definition.name, {})
        if definition.version in versions:
            raise ValueError(
                f"Duplicate task definition: {definition.name}@{definition.version}"
            )
        versions[definition.version] = definition

    def get(self, name: str, version: Optional[str] = None) -> TaskDefinition:
        if name not in self._definitions:
            raise KeyError(f"Unknown task: {name}")
        versions = self._definitions[name]
        selected = version or sorted(versions)[-1]
        if selected not in versions:
            raise KeyError(f"Unknown task version: {name}@{selected}")
        return versions[selected]

    def list(self, *, kind: Optional[str] = None) -> List[TaskDefinition]:
        definitions = [
            definition
            for versions in self._definitions.values()
            for definition in versions.values()
        ]
        if kind is not None:
            definitions = [item for item in definitions if item.kind == kind]
        return sorted(definitions, key=lambda item: (item.name, item.version))

    @classmethod
    def from_directory(cls, directory: Union[str, Path]) -> "TaskRegistry":
        root = Path(directory)
        registry = cls()
        for path in sorted(root.glob("*.json")):
            with path.open("r", encoding="utf-8") as stream:
                registry.register(TaskDefinition.from_dict(json.load(stream)))
        if not registry._definitions:
            raise ValueError(f"No task definitions found in {root}")
        return registry

    def save_candidate(
        self,
        definition: TaskDefinition,
        output_path: Union[str, Path],
    ) -> None:
        definition.validate()
        atomic_write_json(output_path, definition.to_dict())

