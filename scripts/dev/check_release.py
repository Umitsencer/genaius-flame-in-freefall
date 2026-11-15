"""Non-mutating checks for the public source layout and authored documentation."""
from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SKIP = {'.git', '.venv', '__pycache__', 'node_modules'}
errors: list[str] = []
checked = 0
for path in ROOT.rglob('*'):
    relative = path.relative_to(ROOT)
    if not path.is_file() or SKIP.intersection(relative.parts) or relative.parts[:2] == ('data', 'raw'):
        continue
    if path.suffix not in {'.py', '.js', '.css', '.html', '.md', '.json', '.yml', '.toml', '.csv', '.txt'}:
        continue
    text = path.read_text(encoding='utf-8')
    checked += 1
    if '\ufffd' in text:
        errors.append(f'Encoding replacement character: {relative}')
    if path.suffix == '.json':
        json.loads(text)
    if path.suffix == '.html':
        HTMLParser().feed(text)
        ids = re.findall(r'\bid="([^"]+)"', text)
        if len(ids) != len(set(ids)):
            errors.append(f'Duplicate HTML IDs: {relative}')
        for asset in re.findall(r'(?:src|href)="((?:js|css|assets)/[^"]+)"', text):
            if not (path.parent / asset).is_file():
                errors.append(f'Missing asset in {relative}: {asset}')
    if path.suffix == '.md':
        for target in re.findall(r'\[[^\]]+\]\(([^)]+)\)', text):
            target = target.split('#', 1)[0].strip('<>')
            if not target or re.match(r'^[a-z]+:', target, re.I):
                continue
            if not (path.parent / target).exists():
                errors.append(f'Missing document link in {relative}: {target}')
if errors:
    raise SystemExit('\n'.join(errors))
print(f'RELEASE_CHECK_OK: {checked} text files; UTF-8, JSON, HTML IDs/assets and Markdown paths checked.')
