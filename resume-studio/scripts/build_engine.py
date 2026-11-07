"""Build the headless engine for Tauri (run from any working directory)."""
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
host = next(line.split(": ", 1)[1] for line in subprocess.check_output(["rustc", "-vV"], text=True).splitlines() if line.startswith("host:"))
subprocess.run([
    sys.executable, "-m", "PyInstaller", "--noconfirm", "--onefile", "--console",
    "--name", "resume-engine-" + host,
    "--distpath", str(root / "src-tauri/binaries"),
    "--workpath", str(root / "build/engine"),
    "--specpath", str(root / "build"),
    str(root / "python/engine.py"),
], check=True, cwd=root)
