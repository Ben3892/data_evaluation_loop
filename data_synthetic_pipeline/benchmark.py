"""Replay scored benchmark attempts and summarize observed reasoning actions."""

from __future__ import annotations

from collections import Counter, defaultdict
from math import comb
from typing import Any, Dict, Iterable, Optional

from .llm import LLMClient
from .models import TaskDefinition, stable_hash

FAMILIES = {"fact_recall", "instruction_following", "math", "science"}
ACTIONS = {
    "parse_target", "recall_fact", "locate_evidence", "generate_candidate",
    "select_candidate", "bind_constraint", "update_state", "choose_method",
    "model_problem", "apply_rule", "transform_symbol", "compute",
    "split_cases", "derive_prediction", "evaluate_alternative", "verify",
    "revise", "use_tool", "emit_answer", "other",
}
ERROR_CODES = {
    "target_mismatch", "entity_confusion", "recall_unresolved", "fact_incorrect",
    "unsupported_claim", "candidate_selection", "evidence_misread",
    "constraint_omission", "constraint_scope", "stale_state", "unauthorized_edit",
    "context_rule_override", "procedure_skip", "wrong_model",
    "rule_precondition", "invalid_inference", "invalid_transform", "calculation",
    "case_omission", "units_or_scale", "mechanism_mismatch", "causal_overreach",
    "answer_mapping", "output_violation", "unavailable_tool",
}
MARKERS = {
    "source_guess", "unsupported_guess", "tool_intent", "simulated_search",
    "unverified_source", "answer_first_rationalization", "empty_verification",
    "repetition_without_progress",
}
OUTCOMES = {"correct", "incorrect", "abstain", "unscored"}
IDENTITY_FIELDS = ("run_id", "model", "benchmark", "dataset_revision", "item_id", "protocol_id")
RESULT_SCHEMA = "benchmark_attempt.v1"


def required_text(value: dict, field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return result


def attempt_id(row: dict) -> str:
    identity = [required_text(row, field) for field in IDENTITY_FIELDS]
    index = row.get("sample_index")
    if type(index) is not int or index < 0:
        raise ValueError("sample_index must be a non-negative integer")
    return stable_hash(identity, index, prefix="attempt")


def validate_annotations(annotation: dict, count: int, score: dict) -> dict:
    if not isinstance(annotation, dict):
        raise ValueError("annotation must be an object")
    steps = annotation.get("steps")
    if not isinstance(steps, list) or len(steps) != count:
        raise ValueError("annotations must cover every supplied step exactly once")

    first_error = None
    normalized_steps = []
    for index, step in enumerate(steps):
        if (
            not isinstance(step, dict)
            or type(step.get("index")) is not int
            or step["index"] != index
        ):
            raise ValueError(f"expected annotation for step {index}")
        action = required_text(step, "action")
        if action not in ACTIONS:
            raise ValueError(f"unknown action at step {index}")
        quality = required_text(step, "quality")
        if quality not in {"good", "neutral", "bad", "uncertain"}:
            raise ValueError(f"unknown quality at step {index}")
        markers = step.get("markers", [])
        if not isinstance(markers, list) or any(
            not isinstance(marker, str) or marker not in MARKERS for marker in markers
        ):
            raise ValueError(f"unknown markers at step {index}")
        for field in ("depends_on", "repairs"):
            links = step.get(field, [])
            if not isinstance(links, list) or any(
                type(link) is not int or not 0 <= link < index for link in links
            ):
                raise ValueError(f"invalid {field} at step {index}")
        if any(steps[link]["quality"] != "bad" for link in step.get("repairs", [])):
            raise ValueError("repairs must point to an earlier bad step")
        error = step.get("error")
        if quality == "bad":
            if not isinstance(error, dict) or required_text(error, "code") not in ERROR_CODES:
                raise ValueError(f"unknown error at step {index}")
            evidence = required_text(error, "evidence")
            if type(error.get("introduced_here")) is not bool:
                raise ValueError(f"error.introduced_here must be boolean at step {index}")
            if not error["introduced_here"] and not any(
                steps[link]["quality"] == "bad" for link in step.get("depends_on", [])
            ):
                raise ValueError("propagated errors must depend on an earlier bad step")
            error = {
                "code": error["code"],
                "evidence": evidence,
                "introduced_here": error["introduced_here"],
            }
            if first_error is None and error["introduced_here"]:
                first_error = {"index": index, **error}
        elif error is not None:
            raise ValueError(f"only bad steps may carry an error, at step {index}")
        normalized_steps.append({
            "index": index,
            "action": action,
            "quality": quality,
            "markers": markers,
            "depends_on": step.get("depends_on", []),
            "repairs": step.get("repairs", []),
            "error": error,
        })

    primary = annotation.get("primary_error")
    if primary is not None:
        if not isinstance(primary, dict) or score["outcome"] not in {"incorrect", "abstain"}:
            raise ValueError("a primary error requires an incorrect or abstained attempt")
        index = primary.get("index")
        if type(index) is not int or not 0 <= index < count:
            raise ValueError("primary_error.index must reference a step")
        error = steps[index].get("error")
        if not error or not error["introduced_here"]:
            raise ValueError("primary_error must introduce an error")
        if any(index in step.get("repairs", []) for step in steps[index + 1:]):
            raise ValueError("primary_error must still affect the final result")
        reason = required_text(primary, "reason")
        rubric_ids = primary.get("rubric_ids", [])
        failed_ids = {key for key, status in score["rubric_results"].items() if status == "fail"}
        if not isinstance(rubric_ids, list) or any(
            not isinstance(key, str) or key not in failed_ids for key in rubric_ids
        ) or (failed_ids and not rubric_ids):
            raise ValueError("primary_error.rubric_ids must link to a failed criterion when available")
        primary = {
            "index": index,
            "code": error["code"],
            "reason": reason,
            "rubric_ids": rubric_ids,
            "status": "hypothesis",
        }

    return {"steps": normalized_steps, "first_error": first_error, "primary_error": primary}


def evaluate_attempt(
    row: Dict[str, Any],
    *,
    definition: TaskDefinition,
    client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    row_id = attempt_id(row)
    family = required_text(row, "family")
    if family not in FAMILIES:
        raise ValueError(f"unknown benchmark family: {family}")
    score = row.get("score")
    if not isinstance(score, dict) or required_text(score, "outcome") not in OUTCOMES:
        raise ValueError("invalid score.outcome")
    required_text(score, "scorer_id")
    rubric = score.get("rubric_results", {})
    if not isinstance(rubric, dict) or any(
        not isinstance(value, str) or value not in {"pass", "fail", "unscored"}
        for value in rubric.values()
    ):
        raise ValueError("rubric_results must map criterion IDs to pass, fail or unscored")
    score = {**score, "rubric_results": rubric}
    trace = row.get("trace", [])
    if not isinstance(trace, list) or any(
        not isinstance(segment, str) or not segment.strip() for segment in trace
    ):
        raise ValueError("trace must be an array of non-empty segments")
    trace_kind = row.get("trace_kind", "reasoning_trace" if trace else None)
    if trace and trace_kind not in ("reasoning_trace", "reasoning_summary", "final_answer"):
        raise ValueError("invalid trace_kind")
    if not trace and trace_kind is not None:
        raise ValueError("trace_kind requires a non-empty trace")
    trace_ref = required_text(row, "trace_ref") if row.get("trace_ref") is not None else None
    slices = row.get("slices", {})
    if not isinstance(slices, dict) or any(
        not isinstance(value, str) or not value.strip() for value in slices.values()
    ):
        raise ValueError("slices must map dimension names to non-empty strings")

    annotation = row.get("annotation")
    source = None
    if annotation is not None:
        if not trace:
            raise ValueError("an annotation requires an observed trace")
        source = {"method": "import", "annotator_id": required_text(row, "annotator_id")}
    elif trace and client is not None:
        payload = {key: row.get(key) for key in (
            "task", "reference", "answer", "tool_events", "tool_policy", "protocol_id"
        )}
        payload.update(
            attempt_id=row_id, family=family, trace_kind=trace_kind,
            trace=list(enumerate(trace)), score=score
        )
        response = client.generate_json(
            messages=[
                {"role": "system", "content": definition.system_prompt},
                {"role": "user", "content": definition.render_user_prompt({
                    "attempt": payload, "actions": sorted(ACTIONS), "errors": sorted(ERROR_CODES),
                    "markers": sorted(MARKERS),
                })},
            ],
            output_schema=definition.output_schema,
            model=definition.model,
            parameters=definition.parameters,
        )
        annotation = response.content
        if annotation.get("attempt_id") != row_id:
            raise ValueError("judge response attempt_id does not match the input")
        source = {
            "method": "judge",
            "annotator_id": response.model,
            "request_id": response.request_id,
            "response_hash": response.raw_response_hash,
        }

    localization = {"steps": [], "first_error": None, "primary_error": None}
    trace_status = "unannotated" if trace else "unavailable"
    if annotation is not None:
        localization = validate_annotations(annotation, len(trace), score)
        trace_status = "annotated"

    return {
        "schema_version": RESULT_SCHEMA,
        "attempt_id": row_id,
        **{field: row[field] for field in IDENTITY_FIELDS},
        "sample_index": row["sample_index"],
        "family": family,
        "slices": slices,
        "score": score,
        "trace_status": trace_status,
        "trace_kind": trace_kind,
        "trace_hash": stable_hash(trace, prefix="trace") if trace else None,
        "trace_ref": trace_ref,
        "annotation_source": source,
        "annotation_definition_id": definition.definition_id,
        **localization,
    }


def summarize_attempts(
    rows: Iterable[dict], *, k: int = 1, slice_key: Optional[str] = None
) -> dict:
    """Report attempt counts and question-macro pass@k within comparable runs."""
    if type(k) is not int or k < 1:
        raise ValueError("k must be a positive integer")
    group_fields = ("run_id", "model", "benchmark", "dataset_revision", "family",
                    "protocol_id", "scorer_id", "annotation_definition_id")
    groups = defaultdict(list)
    seen = set()
    for row in rows:
        if row.get("schema_version") != RESULT_SCHEMA:
            raise ValueError("unknown benchmark result schema")
        row_id = attempt_id(row)
        if row_id != row.get("attempt_id") or row_id in seen:
            raise ValueError("invalid or duplicate attempt_id")
        seen.add(row_id)
        group_row = {**row, "scorer_id": row["score"]["scorer_id"]}
        key = tuple(group_row[field] for field in group_fields)
        slice_value = row["slices"].get(slice_key) if slice_key else None
        groups[key, slice_value].append(row)

    summaries = []
    for (key, slice_value), attempts in groups.items():
        outcomes = Counter(row["score"]["outcome"] for row in attempts)
        coverage = Counter(row["trace_status"] for row in attempts)
        trace_kinds = Counter(row["trace_kind"] for row in attempts if row["trace_kind"])
        sources = Counter(
            (row["annotation_source"]["method"], row["annotation_source"]["annotator_id"])
            for row in attempts if row["annotation_source"]
        )
        questions = defaultdict(Counter)
        first = Counter()
        primary = Counter()
        actions = Counter()
        markers = Counter()
        transitions = Counter()
        unresolved = 0
        for row in attempts:
            outcome = row["score"]["outcome"]
            questions[row["item_id"]][outcome] += 1
            if row["first_error"]:
                first[row["first_error"]["code"]] += 1
            if row["primary_error"]:
                primary[row["primary_error"]["code"]] += 1
            elif outcome in {"incorrect", "abstain"}:
                unresolved += 1
            action_names = [step["action"] for step in row["steps"]]
            actions.update(f'{step["action"]}:{step["quality"]}' for step in row["steps"])
            markers.update({marker for step in row["steps"] for marker in step.get("markers", [])})
            transitions.update(f"{left}->{right}" for left, right in zip(action_names, action_names[1:]))

        pass_values = []
        for counts in questions.values():
            # Partial scorer failures are excluded at item level.
            n = sum(counts.values())
            if counts["unscored"] or n < k:
                continue
            c = counts["correct"]
            pass_values.append(1 - comb(n - c, k) / comb(n, k))

        scored = len(attempts) - outcomes["unscored"]
        summaries.append({
            **dict(zip(group_fields, key)),
            "slice_key": slice_key,
            "slice_value": slice_value,
            "items": len(questions),
            "attempts": len(attempts),
            "scored_attempts": scored,
            "outcomes": dict(outcomes),
            "attempt_accuracy": outcomes["correct"] / scored if scored else None,
            "trace_coverage": dict(coverage),
            "trace_kinds": dict(trace_kinds),
            "annotation_sources": [
                {"method": method, "annotator_id": annotator_id, "attempts": count}
                for (method, annotator_id), count in sorted(sources.items())
            ],
            "first_error_counts": dict(first),
            "primary_error_counts": dict(primary),
            "unlocalized_failures": unresolved,
            "action_quality_counts": dict(actions),
            "marker_attempt_counts": dict(markers),
            "transition_counts": dict(transitions),
            "pass_at_k": sum(pass_values) / len(pass_values) if pass_values else None,
            "pass_at_k_eligible_items": len(pass_values),
        })
    return {"k": k, "groups": summaries}


def _comparison_rows(rows: Iterable[dict]) -> tuple:
    run_ids = set()
    attempts = {}
    for row in rows:
        if row.get("schema_version") != RESULT_SCHEMA or row.get("attempt_id") != attempt_id(row):
            raise ValueError("invalid benchmark result in comparison")
        run_ids.add((row["run_id"], row["model"]))
        key = (
            row["benchmark"], row["dataset_revision"], row["family"], row["protocol_id"],
            row["score"]["scorer_id"], row["item_id"], row["sample_index"],
        )
        if key in attempts:
            raise ValueError("duplicate comparison attempt")
        attempts[key] = row["score"]["outcome"]
    if len(run_ids) != 1:
        raise ValueError("each comparison input must contain exactly one model and run")
    return next(iter(run_ids)), attempts


def compare_attempts(baseline: Iterable[dict], candidate: Iterable[dict]) -> dict:
    """Compare binary correctness on matched, scored attempts."""
    baseline_run, before = _comparison_rows(baseline)
    candidate_run, after = _comparison_rows(candidate)
    shared_keys = before.keys() & after.keys()
    groups = defaultdict(Counter)
    for key in before.keys() | after.keys():
        counts = groups[key[:5]]
        if key not in shared_keys:
            counts["baseline_only" if key in before else "candidate_only"] += 1
        elif "unscored" in (before[key], after[key]):
            counts["unscored_pairs"] += 1
        else:
            counts["matched_scored"] += 1
            counts["baseline_correct"] += before[key] == "correct"
            counts["candidate_correct"] += after[key] == "correct"
            counts["improved"] += before[key] != "correct" and after[key] == "correct"
            counts["regressed"] += before[key] == "correct" and after[key] != "correct"

    fields = ("benchmark", "dataset_revision", "family", "protocol_id", "scorer_id")
    return {
        "baseline": dict(zip(("run_id", "model"), baseline_run)),
        "candidate": dict(zip(("run_id", "model"), candidate_run)),
        "groups": [
            {
                **dict(zip(fields, key)),
                **{field: counts[field] for field in (
                    "matched_scored", "baseline_only", "candidate_only", "unscored_pairs",
                    "baseline_correct", "candidate_correct", "improved", "regressed",
                )},
                "delta_attempt_accuracy": (
                    (counts["improved"] - counts["regressed"]) / counts["matched_scored"]
                    if counts["matched_scored"] else None
                ),
            }
            for key, counts in sorted(groups.items())
        ],
    }
