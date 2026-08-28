"""Regenerate and type-check the public contract on Windows, macOS, or Linux."""

import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    subprocess.run([sys.executable, str(root / "scripts" / "export_openapi.py")], check=True)
    subprocess.run([npm, "run", "contracts:generate"], cwd=root / "frontend", check=True)
    subprocess.run([npm, "run", "typecheck"], cwd=root / "frontend", check=True)


if __name__ == "__main__":
    main()
