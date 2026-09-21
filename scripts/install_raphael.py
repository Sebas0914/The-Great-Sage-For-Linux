#!/usr/bin/env python3
"""Install the Wisdom King Raphael RVC v2 model for Great Sage.

This is an explicit, opt-in installer. It downloads the third-party model
weights from Hugging Face into the local voice_models/ directory; it never
runs during normal Great Sage startup and the downloaded files are ignored by
Git.
"""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

import requests

REPO_ID = "zidanaetrna/wisdom-king-raphael"
BASE_URL = f"https://huggingface.co/{REPO_ID}/resolve/main"

FILES = {
    "Raphael_200e_3400s.pth": 53_900_000,
    "Raphael.index": 1_200_000,
}

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "voice_models" / "raphael"
CHUNK_SIZE = 1024 * 1024


def format_size(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MiB"


def download(filename: str) -> Path:
    destination = TARGET / filename
    TARGET.mkdir(parents=True, exist_ok=True)

    if destination.is_file() and destination.stat().st_size >= FILES[filename]:
        print(f"[ok] {filename} already exists ({format_size(destination.stat().st_size)})")
        return destination

    url = f"{BASE_URL}/{filename}"
    print(f"[download] {filename}")

    fd, temp_name = tempfile.mkstemp(prefix=f".{filename}.", dir=TARGET)
    os.close(fd)
    temp_path = Path(temp_name)

    try:
        with requests.get(
            url,
            stream=True,
            timeout=(15, 120),
            allow_redirects=True,
            headers={"User-Agent": "Great-Sage-Raphael-Installer/1.0"},
        ) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", "0"))

            written = 0
            with temp_path.open("wb") as output:
                for chunk in response.iter_content(chunk_size=CHUNK_SIZE):
                    if not chunk:
                        continue
                    output.write(chunk)
                    written += len(chunk)
                    if total:
                        percent = min(100.0, written * 100 / total)
                        print(
                            f"\r         {percent:6.1f}% "
                            f"({format_size(written)} / {format_size(total)})",
                            end="",
                            flush=True,
                        )

        print()
        if written < FILES[filename]:
            raise RuntimeError(
                f"{filename} is unexpectedly small ({written} bytes). "
                "The download may have been incomplete."
            )

        temp_path.replace(destination)
        return destination
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    print("Great Sage — Wisdom King Raphael RVC v2 installer")
    print(f"Source: https://huggingface.co/{REPO_ID}")
    print("License: CC BY-NC 4.0 (non-commercial use)")
    print()
    print("The model is downloaded only because you explicitly ran this installer.")
    print()

    try:
        paths = [download(filename) for filename in FILES]
    except requests.RequestException as exc:
        print(f"\n[error] Download failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"\n[error] {exc}", file=sys.stderr)
        return 1

    print("\n[ok] Raphael model installed:")
    for path in paths:
        print(f"     {path.relative_to(ROOT)}")
        print(f"     SHA-256: {sha256(path)}")

    print("\nGreat Sage can now use the Raphael RVC stage.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
