import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = ROOT / "skills" / "drawio" / "references"
FIXTURES = ROOT / "tests" / "fixtures"


def run_script(name, *args):
    return subprocess.run(
        [sys.executable, str(REFERENCES / f"{name}.py"), *map(str, args)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
