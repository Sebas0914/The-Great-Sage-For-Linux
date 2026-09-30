"""Small platform diagnostic used before starting the HUD.

Run:
    python -m great_sage.core.platform.diagnostics
"""
from .detector import summary
from .capabilities import detect_capabilities


def main() -> int:
    print("Great Sage platform diagnostics")
    print("-" * 32)
    info = summary()
    for key, value in info.items():
        print(f"{key}: {value}")
    print()
    print("capabilities:")
    for key, value in detect_capabilities().__dict__.items():
        print(f"  {key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
