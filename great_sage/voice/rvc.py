"""Local RVC v2 post-processing for the Raphael voice model.

RVC runs in a small companion process because infer_rvc_python currently pins
faiss-cpu to a release that has no CPython 3.14 wheel. The companion virtual
environment reuses the main environment's CUDA/PyTorch installation through
system-site-packages, while keeping RVC-only packages isolated.
"""
from __future__ import annotations

import os
import pickle
import struct
import subprocess
import sys
from typing import Tuple

import numpy as np


_DEFAULT_WORKER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "scripts", "rvc_worker.py")


def _frame(payload) -> bytes:
    data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    return struct.pack("!Q", len(data)) + data


def _read_frame(stream):
    header = stream.read(8)
    if len(header) != 8:
        raise RuntimeError("Raphael RVC worker exited before returning a response")
    size = struct.unpack("!Q", header)[0]
    data = stream.read(size)
    if len(data) != size:
        raise RuntimeError("Raphael RVC worker returned a truncated response")
    return pickle.loads(data)


class RVCVoiceConverter:
    """Persistent RVC worker with the model preloaded in a separate process."""

    def __init__(
        self,
        *,
        model_path: str,
        index_path: str,
        pitch_method="rmvpe+",
        index_rate=0.8,
        protect=0.33,
        pitch_semitones=0,
        device="cuda",
        tag="raphael",
        python_executable: str | None = None,
        worker_path: str | None = None,
    ):
        self.model_path = os.path.abspath(os.path.expanduser(model_path))
        self.index_path = os.path.abspath(os.path.expanduser(index_path))
        if not os.path.isfile(self.model_path):
            raise FileNotFoundError(f"Raphael RVC model not found: {self.model_path}")
        if not os.path.isfile(self.index_path):
            raise FileNotFoundError(f"Raphael RVC index not found: {self.index_path}")

        worker = os.path.abspath(os.path.expanduser(worker_path or _DEFAULT_WORKER))
        if not os.path.isfile(worker):
            raise FileNotFoundError(f"Raphael RVC worker not found: {worker}")

        self._proc = None
        self._stdin = None
        self._stdout = None

        executable = python_executable or self._find_python()
        command = [
            executable,
            worker,
            "--model", self.model_path,
            "--index", self.index_path,
            "--pitch-method", str(pitch_method),
            "--index-rate", str(index_rate),
            "--protect", str(protect),
            "--pitch-semitones", str(pitch_semitones),
            "--device", str(device),
            "--tag", str(tag),
        ]
        try:
            self._proc = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
                text=False,
            )
            self._stdin = self._proc.stdin
            self._stdout = self._proc.stdout
            response = _read_frame(self._stdout)
        except Exception:
            self.close()
            raise

        if response.get("ok") is not True:
            self.close()
            raise RuntimeError(response.get("error") or "Raphael RVC worker failed to initialize")

    @staticmethod
    def _find_python() -> str:
        configured = os.environ.get("GREAT_SAGE_RVC_PYTHON")
        if configured:
            return os.path.abspath(os.path.expanduser(configured))

        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        candidate = os.path.join(root, ".rvc-venv", "bin", "python")
        if os.path.isfile(candidate):
            return candidate

        # Development fallback: allows a manually installed RVC environment.
        return sys.executable

    def convert_array(self, samples, sample_rate: int) -> Tuple[np.ndarray, int]:
        if self._proc is None or self._proc.poll() is not None:
            raise RuntimeError("Raphael RVC worker is not running")
        audio = np.asarray(samples, dtype=np.float32)
        if audio.ndim > 1:
            audio = np.mean(audio, axis=1)
        audio = np.ascontiguousarray(audio)
        self._stdin.write(_frame({"op": "convert", "audio": audio, "sample_rate": int(sample_rate)}))
        self._stdin.flush()
        response = _read_frame(self._stdout)
        if response.get("ok") is not True:
            raise RuntimeError(response.get("error") or "Raphael RVC conversion failed")
        return np.asarray(response["audio"], dtype=np.float32).reshape(-1), int(response["sample_rate"])

    def close(self):
        if self._stdin is not None:
            try:
                self._stdin.write(_frame({"op": "close"}))
                self._stdin.flush()
            except Exception:
                pass
        if self._proc is not None:
            try:
                self._proc.wait(timeout=3)
            except Exception:
                self._proc.kill()
                self._proc.wait(timeout=3)
        self._stdin = None
        self._stdout = None
        self._proc = None

    def unload(self):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
