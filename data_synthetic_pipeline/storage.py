"""Run artifacts with public/private separation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Iterator, Optional, Union

from .models import QualityDecision, TaskCandidate, TaskExecution, stable_hash, utc_now
from .utils import atomic_write_json, iter_jsonl, write_jsonl


class RunStore:
    def __init__(self, output_root: Union[str, os.PathLike], run_id: str) -> None:
        self.root = Path(output_root) / run_id
        self.run_id = run_id
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def executions_path(self) -> Path:
        return self.root / "executions.jsonl"

    @property
    def quality_path(self) -> Path:
        return self.root / "quality.jsonl"

    def save_execution(self, execution: TaskExecution) -> None:
        public_value = execution.to_dict(include_private=False)
        candidate = execution.candidate
        if candidate and candidate.private_payload:
            private_path = self.root / "private" / f"{candidate.candidate_id}.json"
            atomic_write_json(private_path, candidate.private_payload)
            os.chmod(private_path, 0o600)
            public_value["candidate"]["payload"][
                "private_artifact_ref"
            ] = str(private_path)
        write_jsonl(self.executions_path, [public_value], append=True)

    def save_quality(self, decision: QualityDecision) -> None:
        write_jsonl(self.quality_path, [decision.to_dict()], append=True)

    def save_report(self, report: object, filename: str = "evaluation.json") -> Path:
        value = report.to_dict() if hasattr(report, "to_dict") else report
        path = self.root / filename
        atomic_write_json(path, value)
        return path

    def append_event(self, stage: str, payload: dict) -> None:
        event = {
            "event_id": stable_hash(
                self.run_id,
                stage,
                payload,
                utc_now(),
                prefix="event",
            ),
            "run_id": self.run_id,
            "stage": stage,
            "payload": payload,
            "created_at": utc_now(),
        }
        write_jsonl(self.root / "events.jsonl", [event], append=True)

