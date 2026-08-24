"""Small orchestrator that preserves task independence."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Type

from .llm import LLMClient
from .models import TaskExecution, TaskRequest
from .registry import TaskRegistry
from .storage import RunStore
from .tasks import CodeGenerationTask, MathKnowledgeTask, RewriteTask
from .tasks.base import LLMDataTask

_TASK_TYPES: Dict[str, Type[LLMDataTask]] = {
    "math_knowledge": MathKnowledgeTask,
    "rewrite": RewriteTask,
    "code_generation": CodeGenerationTask,
}


class IndependentTaskRunner:
    """Run one named task without requiring any other task stage."""

    def __init__(
        self,
        registry: TaskRegistry,
        llm: LLMClient,
        *,
        store: Optional[RunStore] = None,
    ) -> None:
        self.registry = registry
        self.llm = llm
        self.store = store

    def build_task(self, task_name: str) -> LLMDataTask:
        if task_name not in _TASK_TYPES:
            raise KeyError(f"No task implementation registered for {task_name}")
        definition = self.registry.get(task_name)
        return _TASK_TYPES[task_name](definition, self.llm)

    def run(
        self,
        task_name: str,
        requests: Iterable[TaskRequest],
    ) -> List[TaskExecution]:
        task = self.build_task(task_name)
        executions: List[TaskExecution] = []
        for request in requests:
            execution = task.run(request)
            executions.append(execution)
            if self.store:
                self.store.save_execution(execution)
                self.store.append_event(
                    "task_execution",
                    {
                        "task_name": task_name,
                        "input_id": request.input_id,
                        "candidate_id": (
                            execution.candidate.candidate_id
                            if execution.candidate
                            else None
                        ),
                        "succeeded": execution.succeeded,
                        "issues": execution.validation.issues,
                    },
                )
        return executions

