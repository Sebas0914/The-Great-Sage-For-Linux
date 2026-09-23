"""Static contract check for the isolated Raphael RVC runtime."""
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parent
rvc = (ROOT / "great_sage/voice/rvc.py").read_text(encoding="utf-8")
worker = (ROOT / "scripts/rvc_worker.py").read_text(encoding="utf-8")
installer = (ROOT / "scripts/install_raphael_rvc_runtime.py").read_text(encoding="utf-8")
settings = (ROOT / "great_sage/config/settings.py").read_text(encoding="utf-8")

for source, name in ((rvc, "rvc.py"), (worker, "rvc_worker.py"), (installer, "installer"), (settings, "settings.py")):
    ast.parse(source, filename=name)

required = (
    "subprocess.Popen",
    "generate_from_cache",
    ".rvc-venv",
    "infer_rvc_python",
    "faiss-cpu>=1.13.1",
    "GREAT_SAGE_RVC_PYTHON",
)
missing = [item for item in required if item not in rvc + worker + installer + settings]
if missing:
    raise SystemExit(f"Missing Raphael isolated-runtime contract: {missing}")

print("OK - Raphael isolated RVC runtime contract")
