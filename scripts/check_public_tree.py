"""Guard public sample data and reject tracked local artifacts. Not a general PII detector."""
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
errors = []
paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode("utf-8").split("\0")
for name in filter(None, paths):
    path = PurePosixPath(name)
    if set(path.parts) & {"node_modules", "target", "dist", "build", "__pycache__", ".test-data", "test-results", "playwright-report", ".venv", "private", ".cache"}:
        errors.append(f"Local/generated directory is tracked: {name}")
    if path.suffix.lower() in {".docx", ".pdf", ".log", ".exe", ".bak", ".pyc", ".tmp", ".tsbuildinfo"} or path.name.startswith("workspace") and path.suffix == ".json":
        errors.append(f"Local/generated file is tracked: {name}")
    if path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example":
        errors.append(f"Environment file is tracked: {name}")

for language, expected in (("en", "John Doe"), ("zh", "陈大文")):
    source = ROOT / f"resume_{language}.yaml"
    fixture = ROOT / f"resume-studio/fixtures/resume_{language}.yaml"
    if source.read_bytes() != fixture.read_bytes():
        errors.append(f"Root and application sample differ: {source.name}")
    sample = yaml.safe_load(source.read_text(encoding="utf-8"))
    if sample["profile"]["name"] != expected:
        errors.append(f"Public sample must use {expected}: {source.name}")
    contacts = "\n".join(sample["profile"]["contacts"])
    if any(domain.lower() != "example.com" for domain in re.findall(r"@([\w.-]+)", contacts)):
        errors.append(f"Sample email must use example.com: {source.name}")
    if any(domain.lower() != "example.com" for domain in re.findall(r"https?://([^/\s]+)", contacts)):
        errors.append(f"Sample URL must use example.com: {source.name}")
    if re.search(r"\d{7,}", contacts):
        errors.append(f"Sample contains a phone-like number: {source.name}")
    for section in sample["sections"]:
        field = {"experience": "company", "education": "school"}.get(section["type"])
        if field and any(not any(marker in item[field].lower() for marker in ("fictional", "虚构")) for item in section["items"]):
            errors.append(f"Sample organizations must be marked fictional: {source.name}")

if errors:
    print("\n".join(errors), file=sys.stderr)
    raise SystemExit(1)
print("Public sample and tracked-file checks passed.")
