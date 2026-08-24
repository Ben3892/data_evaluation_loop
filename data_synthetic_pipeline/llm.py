"""Provider-neutral JSON LLM clients."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence

from .models import canonical_json, stable_hash


@dataclass
class LLMResponse:
    content: Dict[str, Any]
    model: str
    request_id: Optional[str] = None
    usage: Dict[str, Any] = field(default_factory=dict)
    raw_response_hash: Optional[str] = None

    def __post_init__(self) -> None:
        if self.raw_response_hash is None:
            self.raw_response_hash = stable_hash(self.content, prefix="response")


class LLMClient(Protocol):
    def generate_json(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        output_schema: Mapping[str, Any],
        model: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> LLMResponse:
        ...


class ReplayLLMClient:
    """Deterministic client backed by recorded JSON responses."""

    def __init__(
        self,
        responses: Iterable[Mapping[str, Any]],
        *,
        model: str = "replay-model",
    ) -> None:
        self._responses = iter(responses)
        self.model = model
        self.calls: List[Dict[str, Any]] = []

    def generate_json(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        output_schema: Mapping[str, Any],
        model: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> LLMResponse:
        self.calls.append(
            {
                "messages": [dict(item) for item in messages],
                "output_schema": dict(output_schema),
                "model": model,
                "parameters": dict(parameters or {}),
            }
        )
        try:
            content = dict(next(self._responses))
        except StopIteration as exc:
            raise RuntimeError("ReplayLLMClient has no response left") from exc
        return LLMResponse(
            content=content,
            model=model or self.model,
            request_id=f"replay-{len(self.calls)}",
        )


class OpenAICompatibleClient:
    """Minimal JSON client for OpenAI-compatible chat-completions endpoints.

    The implementation uses only the Python standard library so local vLLM or
    remote compatible endpoints can be used without forcing an SDK dependency.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not model:
            raise ValueError("model is required")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

    @classmethod
    def from_env(cls, prefix: str = "DSP_LLM") -> "OpenAICompatibleClient":
        base_url = os.environ.get(f"{prefix}_BASE_URL", "")
        model = os.environ.get(f"{prefix}_MODEL", "")
        api_key = os.environ.get(f"{prefix}_API_KEY")
        return cls(base_url=base_url, model=model, api_key=api_key)

    @property
    def endpoint(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def generate_json(
        self,
        *,
        messages: Sequence[Mapping[str, str]],
        output_schema: Mapping[str, Any],
        model: Optional[str] = None,
        parameters: Optional[Mapping[str, Any]] = None,
    ) -> LLMResponse:
        schema_message = {
            "role": "system",
            "content": (
                "Return only one JSON object matching this schema. "
                f"Do not add markdown: {canonical_json(output_schema)}"
            ),
        }
        payload: Dict[str, Any] = {
            "model": model or self.model,
            "messages": [dict(item) for item in messages] + [schema_message],
            "response_format": {"type": "json_object"},
        }
        payload.update(dict(parameters or {}))
        request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            request = urllib.request.Request(
                self.endpoint,
                data=request_body,
                headers=headers,
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                decoded = json.loads(raw.decode("utf-8"))
                choice = decoded["choices"][0]["message"]["content"]
                if isinstance(choice, str):
                    content = json.loads(choice)
                elif isinstance(choice, dict):
                    content = choice
                else:
                    raise ValueError("LLM response content is not a JSON object")
                if not isinstance(content, dict):
                    raise ValueError("LLM response JSON must be an object")
                return LLMResponse(
                    content=content,
                    model=str(decoded.get("model", model or self.model)),
                    request_id=decoded.get("id"),
                    usage=dict(decoded.get("usage", {})),
                    raw_response_hash=stable_hash(decoded, prefix="response"),
                )
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                KeyError,
                IndexError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as exc:
                last_error = exc
                if attempt + 1 < self.max_retries:
                    time.sleep(min(2**attempt, 8))
        raise RuntimeError(
            f"LLM request failed after {self.max_retries} attempts: {last_error}"
        ) from last_error

