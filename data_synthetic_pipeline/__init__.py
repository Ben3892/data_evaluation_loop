"""Data-only synthetic-data closed loop.

The package deliberately keeps generation, rewriting, code-task creation, and
quality filtering as independent tasks.  They can be composed by the pipeline,
but none of them depends on a training framework.
"""

from .models import (
    EvaluationReport,
    TaskCandidate,
    TaskDefinition,
    TaskExecution,
    TaskRequest,
    ValidationResult,
)

__all__ = [
    "EvaluationReport",
    "TaskCandidate",
    "TaskDefinition",
    "TaskExecution",
    "TaskRequest",
    "ValidationResult",
]

__version__ = "0.1.0"

