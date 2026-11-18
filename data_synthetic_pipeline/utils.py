import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Union

PathLike = Union[str, os.PathLike]

# 读取jsonl里所有行到内存，返回一个列表
def read_jsonl(file_path):
    return list(iter_jsonl(file_path))


def iter_jsonl(file_path: PathLike) -> Iterator[Dict[str, Any]]:
    """Stream JSON objects from a JSONL file.

    Empty lines are ignored.  Errors include the source line number so a large
    run can be repaired without loading the complete file into memory.
    """

    with open(file_path, "r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSONL at {file_path}:{line_number}: {exc.msg}"
                ) from exc
            if not isinstance(value, dict):
                raise ValueError(
                    f"JSONL row must be an object at {file_path}:{line_number}"
                )
            yield value


def write_jsonl(
    file_path: PathLike,
    rows: Iterable[Dict[str, Any]],
    *,
    append: bool = False,
) -> None:
    """Write JSON objects as UTF-8 JSONL."""

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            stream.write("\n")


def atomic_write_jsonl(file_path: PathLike, rows: Iterable[Dict[str, Any]]) -> None:
    """Publish a complete JSONL artifact after consuming all rows."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{path.name}.", dir=path.parent) as temporary:
        pending = Path(temporary) / path.name
        write_jsonl(pending, rows)
        os.replace(pending, path)


def atomic_write_json(file_path: PathLike, value: Any) -> None:
    """Atomically replace a JSON artifact in the target directory."""

    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass
        raise

# 读取parquet文件
def read_parquet(file_path):
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError(
            "read_parquet requires the optional data dependencies; "
            "install with: pip install -e '.[data]'"
        ) from exc
    df = pd.read_parquet(file_path)
    return df
