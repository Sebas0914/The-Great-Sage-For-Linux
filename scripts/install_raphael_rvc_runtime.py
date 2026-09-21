"""Create the isolated Raphael RVC runtime.

The main Great Sage environment stays untouched. The RVC environment uses
system-site-packages so the existing CUDA PyTorch/torchaudio stack can be
reused instead of downloading a second copy of those large packages.
"""
from __future__ import annotations

import os
import platform
import subprocess
import sys
import venv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".rvc-venv"
PYTHON = VENV / "bin" / "python"


def run(*args: str) -> None:
    print("+", " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    if platform.system() != "Linux":
        raise SystemExit("The isolated Raphael runtime installer currently targets Linux.")

    if not PYTHON.exists():
        print(f"Creating {VENV} with system-site-packages...")
        venv.EnvBuilder(with_pip=True, system_site_packages=True).create(VENV)

    run(str(PYTHON), "-m", "pip", "install", "--upgrade", "pip")
    # infer_rvc_python 1.3.1 declares faiss-cpu==1.10.0. That FAISS release
    # has Linux wheels through CPython 3.13, but not CPython 3.14. The
    # runtime API does not require that exact FAISS build, so install the
    # newer ABI-compatible wheel separately and keep infer's metadata out
    # of the resolver.
    run(str(PYTHON), "-m", "pip", "install", "--no-deps", "infer_rvc_python==1.3.1")
    run(str(PYTHON), "-m", "pip", "install", "faiss-cpu>=1.13.1")
    run(str(PYTHON), "-m", "pip", "install", "praat-parselmouth>=0.4.3")
    # The normal pyworld 0.3.2 dependency is old enough to trigger source
    # builds on modern Python. The prebuilt distribution exposes the same
    # pyworld import and publishes current Linux CPython wheels.
    run(str(PYTHON), "-m", "pip", "install", "pyworld-prebuilt>=0.3.5.post1")

    check = (
        "import infer_rvc_python, faiss, pyworld; "
        "from infer_rvc_python import BaseLoader; "
        "print('Raphael RVC runtime OK'); "
        "print('infer_rvc_python:', infer_rvc_python.__file__); "
        "print('faiss:', faiss.__version__)"
    )
    run(str(PYTHON), "-c", check)
    print()
    print("Runtime ready:", PYTHON)
    print("Great Sage will use it automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
