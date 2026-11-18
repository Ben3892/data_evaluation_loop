"""Refresh browser downloads from tracked source; no network or credentials."""
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'workbench'
PATHS = [
    'data_synthetic_pipeline/eval_loop.py',
    'data_synthetic_pipeline/eval_assets/evaluation-result.schema.json',
    'data_synthetic_pipeline/eval_assets/atomic-exact.v1.json',
    'data_synthetic_pipeline/cli.py',
    'schemas/evaluation-result.schema.json',
    'fixtures/atomic-exact.v1.json',
    'fixtures/eval-smoke.jsonl',
    'tests/test_eval_loop.py',
    'pyproject.toml',
    'requirements-eval.txt',
]


def main():
    files = []
    for name in PATHS:
        content = (ROOT / name).read_text(encoding='utf-8')
        files.append({'path': name, 'content': content})
        target = DEST / 'kit' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    (DEST / 'kit-files.json').write_text(json.dumps(files, ensure_ascii=False), encoding='utf-8')
    with zipfile.ZipFile(DEST / 'evaluation-loop-mvp.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.writestr(file['path'], file['content'])
    print(f'Refreshed {len(files)} source files in workbench/kit and download ZIP.')


if __name__ == '__main__':
    main()
