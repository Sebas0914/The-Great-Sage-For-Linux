"""Static checks for the Linux Wayland/KDE integration."""

import ast
import json
from pathlib import Path

ROOT = Path(__file__).parent
PYTHON_FILES = [
    ROOT / "great_sage/core/platform/linux_wayland.py",
    ROOT / "great_sage/core/platform/factory.py",
    ROOT / "great_sage/server.py",
    ROOT / "run_hud.py",
]
KWIN_METADATA = ROOT / "great_sage/core/platform/kwin_script/metadata.json"
KWIN_SCRIPT = ROOT / "great_sage/core/platform/kwin_script/contents/code/main.js"


def main():
    for path in PYTHON_FILES:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    server = (ROOT / "great_sage/server.py").read_text(encoding="utf-8")
    assert "from great_sage.core.global_hotkey import GlobalHotkey" not in server
    hud = (ROOT / "run_hud.py").read_text(encoding="utf-8")
    assert 'if os.name == "nt":' in hud

    factory = (ROOT / "great_sage/core/platform/factory.py").read_text(encoding="utf-8")
    assert "_PLATFORM = None" in factory
    assert "_PLATFORM_KIND = None" in factory
    assert "if _PLATFORM is None or _PLATFORM_KIND != kind:" in factory

    metadata = json.loads(KWIN_METADATA.read_text(encoding="utf-8"))
    plugin = metadata.get("KPlugin", {})
    assert plugin.get("Id") == "great-sage-active-window"
    assert metadata.get("KPackageStructure") == "KWin/Script"
    assert metadata.get("X-Plasma-API") == "javascript"
    assert metadata.get("X-Plasma-MainScript") == "code/main.js"

    script = KWIN_SCRIPT.read_text(encoding="utf-8")
    assert "setInterval" in script
    assert "clearInterval" in script
    required = (
        "workspace.activeWindow",
        "workspace.windowActivated",
        "callDBus",
        "org.greatsage.KWinBridge",
        "SetActiveWindow",
    )
    missing = [item for item in required if item not in script]
    assert not missing, "KWin bridge script is missing: " + ", ".join(missing)

    print("OK - Linux platform Python and KWin bridge metadata/script validated")


if __name__ == "__main__":
    main()
