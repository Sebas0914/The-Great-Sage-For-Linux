"""Static contract checks for the Raphael RVC integration."""
import ast
from pathlib import Path

ROOT = Path(__file__).parent

def main():
    for path in (
        ROOT / "great_sage/voice/rvc.py",
        ROOT / "great_sage/voice/f5_tts_engine.py",
        ROOT / "great_sage/config/settings.py",
    ):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    rvc = (ROOT / "great_sage/voice/rvc.py").read_text(encoding="utf-8")
    assert "BaseLoader" in rvc
    assert "generate_from_cache" in rvc
    assert "rmvpe+" in rvc or "rmvpe" in rvc

    settings = (ROOT / "great_sage/config/settings.py").read_text(encoding="utf-8")
    for name in (
        "RVC_ENABLED", "RVC_MODEL_PATH", "RVC_INDEX_PATH",
        "RVC_PITCH_METHOD", "RVC_INDEX_RATE", "RVC_PROTECT",
    ):
        assert name in settings

    f5 = (ROOT / "great_sage/voice/f5_tts_engine.py").read_text(encoding="utf-8")
    assert "RVCVoiceConverter" in f5
    assert "self._rvc.convert_array" in f5

    print("OK - Raphael RVC voice integration contract")

if __name__ == "__main__":
    main()
