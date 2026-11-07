"""Require a release tag to match all three application version declarations."""
import json
import os
from pathlib import Path
import tomllib

root = Path(__file__).resolve().parents[1] / "resume-studio"
versions = {
    json.loads((root / "package.json").read_text(encoding="utf-8"))["version"],
    json.loads((root / "src-tauri/tauri.conf.json").read_text(encoding="utf-8"))["version"],
    tomllib.loads((root / "src-tauri/Cargo.toml").read_text(encoding="utf-8"))["package"]["version"],
}
tag = os.environ.get("RELEASE_TAG", "")
if len(versions) != 1 or tag != "v" + next(iter(versions)):
    raise SystemExit("Release tag must be v<version>, matching package.json, Cargo.toml, and tauri.conf.json.")
print("Release versions match.")
