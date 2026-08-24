"""Intrinsic evaluation for the data-only loop."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Mapping, Optional

from .models import (
    EvaluationReport,
    QualityDecision,
    TaskExecution,
    stable_hash,
    utc_now,
)


class DataQualityEvaluator:
    def evaluate(
        self,
        executions: Iterable[TaskExecution],
        decisions: Iterable[QualityDecision] = (),
        *,
        metadata: Optional[Dict[str, object]] = None,
    ) -> EvaluationReport:
        execution_list = list(executions)
        decision_by_candidate = {
            item.candidate_id: item for item in decisions
        }
        per_task_counts: Dict[str, Counter] = defaultdict(Counter)
        rejection_reasons: Counter = Counter()

        generated = valid = accepted = rejected = 0
        for execution in execution_list:
            task_name = (
                execution.candidate.task_name
                if execution.candidate
                else "unknown"
            )
            counts = per_task_counts[task_name]
            counts["requests"] += 1
            if execution.candidate:
                generated += 1
                counts["generated"] += 1
            if execution.succeeded:
                valid += 1
                counts["valid"] += 1
            else:
                for issue in execution.validation.issues:
                    rejection_reasons[f"generation:{issue}"] += 1

            if not execution.candidate:
                continue
            decision = decision_by_candidate.get(
                execution.candidate.candidate_id
            )
            if not decision:
                continue
            if decision.decision == "accept":
                accepted += 1
                counts["accepted"] += 1
            else:
                rejected += 1
                counts["rejected"] += 1
                for reason in decision.reject_reasons:
                    rejection_reasons[f"quality:{reason}"] += 1

        per_task: Dict[str, Dict[str, object]] = {}
        for task_name, counts in per_task_counts.items():
            task_generated = counts["generated"]
            task_accepted = counts["accepted"]
            per_task[task_name] = {
                **dict(counts),
                "valid_yield": (
                    counts["valid"] / task_generated if task_generated else 0.0
                ),
                "accept_yield": (
                    task_accepted / task_generated if task_generated else 0.0
                ),
            }

        totals = {
            "requests": len(execution_list),
            "generated": generated,
            "valid": valid,
            "accepted": accepted,
            "rejected": rejected,
            "valid_yield": valid / generated if generated else 0.0,
            "accept_yield": accepted / generated if generated else 0.0,
        }
        report_id = stable_hash(
            totals,
            per_task,
            dict(rejection_reasons),
            metadata or {},
            prefix="evaluation",
        )
        return EvaluationReport(
            report_id=report_id,
            created_at=utc_now(),
            totals=totals,
            per_task=per_task,
            rejection_reasons=dict(rejection_reasons),
            metadata=metadata or {},
        )

