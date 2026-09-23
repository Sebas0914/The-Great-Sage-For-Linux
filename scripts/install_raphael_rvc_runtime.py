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

    # A virtualenv does not expose another virtualenv's site-packages through
    # system-site-packages. Great Sage already owns the CUDA PyTorch stack in
    # .venv, so expose that exact site-packages directory to the RVC runtime
    # with a .pth file instead of downloading a second multi-GB torch build.
    main_site = ROOT / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    if not main_site.is_dir():
        raise SystemExit(f"Main Great Sage site-packages not found: {main_site}. Activate/create .venv first.")
    rvc_site = VENV / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    rvc_site.mkdir(parents=True, exist_ok=True)
    bridge = rvc_site / "great_sage_main_venv.pth"
    bridge.write_text(str(main_site) + "\n", encoding="utf-8")
    print(f"Reusing main PyTorch stack from {main_site}")

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
    # Lightweight runtime dependencies declared by infer_rvc_python but not
    # needed in the main Great Sage environment. Install them without asking
    # pip to replace the shared CUDA/PyTorch stack.
    run(str(PYTHON), "-m", "pip", "install", "ffmpeg-python>=0.2.0", "librosa", "soxr>=1.1.0", "torchcrepe==0.0.20", "transformers")

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
