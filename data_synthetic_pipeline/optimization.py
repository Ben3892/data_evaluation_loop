"""LLM-proposed, deterministically validated data-task modifications."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .llm import LLMClient
from .models import (
    EvaluationReport,
    SamplingPolicy,
    TaskDefinition,
    stable_hash,
    utc_now,
)
from .tasks.base import validate_json_schema_subset


@dataclass
class PromptProposal:
    proposal_id: str
    target_definition_id: str
    candidate_definition: TaskDefinition
    hypothesis: str
    expected_effects: List[str]
    risks: List[str]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["candidate_definition"] = self.candidate_definition.to_dict()
        return value


@dataclass
class MixtureProposal:
    proposal_id: str
    raw_weights: Dict[str, float]
    projected_weights: Dict[str, float]
    rationale: Dict[str, str]
    constraints: Dict[str, Dict[str, float]]
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PromptOptimizer:
    """Ask an LLM for a candidate task definition; never auto-promote it."""

    def __init__(
        self,
        optimizer_definition: TaskDefinition,
        llm: LLMClient,
    ) -> None:
        if optimizer_definition.kind != "optimizer":
            raise ValueError("optimizer_definition must have kind=optimizer")
        self.definition = optimizer_definition
        self.llm = llm

    def propose(
        self,
        *,
        target: TaskDefinition,
        report: EvaluationReport,
        error_examples: Sequence[Mapping[str, Any]] = (),
    ) -> PromptProposal:
        context = {
            "target_definition": target.to_dict(),
            "evaluation_report": report.to_dict(),
            "error_examples": list(error_examples),
            "editable_fields": list(target.editable_fields),
        }
        response = self.llm.generate_json(
            messages=(
                {"role": "system", "content": self.definition.system_prompt},
                {
                    "role": "user",
                    "content": self.definition.render_user_prompt(context),
                },
            ),
            output_schema=self.definition.output_schema,
            model=self.definition.model,
            parameters=self.definition.parameters,
        )
        issues = validate_json_schema_subset(
            response.content,
            self.definition.output_schema,
        )
        if issues:
            raise ValueError(f"Invalid prompt proposal: {issues}")

        proposed_updates: Dict[str, Any] = {}
        if "system_prompt" in response.content:
            self._ensure_editable(target, "system_prompt")
            proposed_updates["system_prompt"] = str(
                response.content["system_prompt"]
            )
        if "user_prompt" in response.content:
            self._ensure_editable(target, "user_prompt")
            proposed_updates["user_prompt"] = str(response.content["user_prompt"])
        if "parameters" in response.content:
            self._ensure_editable(target, "parameters")
            proposed_updates["parameters"] = dict(response.content["parameters"])
        if not proposed_updates:
            raise ValueError("Prompt proposal did not modify an editable field")

        content_hash = stable_hash(
            target.definition_id,
            proposed_updates,
            prefix="prompt-proposal",
        )
        candidate = replace(
            target,
            version=f"{target.version}.candidate.{content_hash[-8:]}",
            **proposed_updates,
        )
        candidate.validate()
        return PromptProposal(
            proposal_id=content_hash,
            target_definition_id=target.definition_id,
            candidate_definition=candidate,
            hypothesis=str(response.content.get("hypothesis", "")),
            expected_effects=list(response.content.get("expected_effects", [])),
            risks=list(response.content.get("risks", [])),
            created_at=utc_now(),
        )

    @staticmethod
    def _ensure_editable(target: TaskDefinition, field_name: str) -> None:
        if field_name not in target.editable_fields:
            raise ValueError(f"Field is not editable: {field_name}")


def project_bounded_simplex(
    raw_weights: Mapping[str, float],
    bounds: Mapping[str, Tuple[float, float]],
    *,
    tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> Dict[str, float]:
    """Project positive task weights onto a box-constrained simplex."""

    names = sorted(bounds)
    if set(raw_weights) != set(names):
        raise ValueError("raw_weights and bounds must have identical task names")
    lower_sum = sum(bounds[name][0] for name in names)
    upper_sum = sum(bounds[name][1] for name in names)
    if lower_sum > 1 + tolerance or upper_sum < 1 - tolerance:
        raise ValueError("Infeasible bounds: require sum(lower) <= 1 <= sum(upper)")
    for name, (lower, upper) in bounds.items():
        if lower < 0 or upper > 1 or lower > upper:
            raise ValueError(f"Invalid bounds for {name}: {(lower, upper)}")

    values = {
        name: min(max(float(raw_weights[name]), bounds[name][0]), bounds[name][1])
        for name in names
    }
    if sum(max(value, 0.0) for value in values.values()) <= tolerance:
        values = {name: bounds[name][0] for name in names}

    for _ in range(max_iterations):
        difference = 1.0 - sum(values.values())
        if abs(difference) <= tolerance:
            break
        if difference > 0:
            capacities = {
                name: bounds[name][1] - values[name] for name in names
            }
        else:
            capacities = {
                name: values[name] - bounds[name][0] for name in names
            }
        capacity_sum = sum(value for value in capacities.values() if value > 0)
        if capacity_sum <= tolerance:
            raise ValueError("Cannot satisfy simplex with provided bounds")
        for name in names:
            capacity = max(capacities[name], 0.0)
            if not capacity:
                continue
            delta = difference * capacity / capacity_sum
            values[name] = min(
                max(values[name] + delta, bounds[name][0]),
                bounds[name][1],
            )
    if abs(sum(values.values()) - 1.0) > 1e-8:
        raise ValueError("Simplex projection did not converge")
    return values


class MixturePlanner:
    """Ask an LLM for weights, then enforce deterministic task constraints."""

    def __init__(
        self,
        planner_definition: TaskDefinition,
        llm: LLMClient,
    ) -> None:
        if planner_definition.kind != "planner":
            raise ValueError("planner_definition must have kind=planner")
        self.definition = planner_definition
        self.llm = llm

    def propose(
        self,
        *,
        tasks: Sequence[TaskDefinition],
        report: EvaluationReport,
    ) -> MixtureProposal:
        generators = [item for item in tasks if item.kind == "generator"]
        if not generators:
            raise ValueError("At least one generator task is required")
        current = {item.name: item.sampling.weight for item in generators}
        constraints: Dict[str, Dict[str, float]] = {}
        bounds: Dict[str, Tuple[float, float]] = {}
        for item in generators:
            policy = item.sampling
            lower = max(policy.min_weight, policy.weight - policy.max_delta)
            upper = min(policy.max_weight, policy.weight + policy.max_delta)
            bounds[item.name] = (lower, upper)
            constraints[item.name] = {
                "current": policy.weight,
                "min": lower,
                "max": upper,
            }
        context = {
            "current_weights": current,
            "constraints": constraints,
            "evaluation_report": report.to_dict(),
        }
        response = self.llm.generate_json(
            messages=(
                {"role": "system", "content": self.definition.system_prompt},
                {
                    "role": "user",
                    "content": self.definition.render_user_prompt(context),
                },
            ),
            output_schema=self.definition.output_schema,
            model=self.definition.model,
            parameters=self.definition.parameters,
        )
        issues = validate_json_schema_subset(
            response.content,
            self.definition.output_schema,
        )
        if issues:
            raise ValueError(f"Invalid mixture proposal: {issues}")
        raw = {
            name: float(value)
            for name, value in dict(response.content.get("weights", {})).items()
        }
        if set(raw) != set(current):
            raise ValueError("Planner must propose exactly one weight per task")
        projected = project_bounded_simplex(raw, bounds)
        rationale = {
            str(name): str(reason)
            for name, reason in dict(
                response.content.get("rationale", {})
            ).items()
        }
        proposal_id = stable_hash(
            report.report_id,
            current,
            raw,
            projected,
            prefix="mixture-proposal",
        )
        return MixtureProposal(
            proposal_id=proposal_id,
            raw_weights=raw,
            projected_weights=projected,
            rationale=rationale,
            constraints=constraints,
            created_at=utc_now(),
        )

