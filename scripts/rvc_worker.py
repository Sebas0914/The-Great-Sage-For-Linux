"""Persistent Raphael RVC worker.

Audio crosses the process boundary through temporary WAV files. The stdout
protocol therefore carries only small control messages, while RVC inference
and audio serialization stay inside this runtime process.
"""
from __future__ import annotations

import argparse
import os
import pickle

import numpy as np
import struct
import sys
import tempfile
import traceback

import soundfile as sf


def send(stream, payload):
    data = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    stream.write(struct.pack("!Q", len(data)))
    stream.write(data)
    stream.flush()


def _clarity_eq(samples, sample_rate: int):
    """Gentle post-RVC voicing EQ: less box/horn, slightly more articulation."""
    from pedalboard import HighShelfFilter, LowShelfFilter, PeakFilter, Pedalboard

    board = Pedalboard([
        LowShelfFilter(cutoff_frequency_hz=180.0, gain_db=-1.2, q=0.7),
        PeakFilter(cutoff_frequency_hz=700.0, gain_db=-1.4, q=0.8),
        PeakFilter(cutoff_frequency_hz=1900.0, gain_db=-1.5, q=0.9),
        PeakFilter(cutoff_frequency_hz=4300.0, gain_db=1.6, q=0.85),
        HighShelfFilter(cutoff_frequency_hz=8500.0, gain_db=0.8, q=0.7),
    ])
    data = np.asarray(samples, dtype=np.float32)
    mono = data.ndim == 1
    if mono:
        data = data.reshape(1, -1)
    out = board(data, float(sample_rate), reset=True)
    return out[0] if mono else out


def recv(stream):
    header = stream.read(8)
    if len(header) != 8:
        return None
    size = struct.unpack("!Q", header)[0]
    data = stream.read(size)
    if len(data) != size:
        raise RuntimeError("truncated RVC request")
    return pickle.loads(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--pitch-method", default="rmvpe+")
    parser.add_argument("--index-rate", type=float, default=0.8)
    parser.add_argument("--protect", type=float, default=0.33)
    parser.add_argument("--pitch-semitones", type=int, default=0)
    parser.add_argument("--output-gain-db", type=float, default=0.0)
    parser.add_argument("--dry-mix", type=float, default=0.0)
    parser.add_argument("--clarity-eq", default="true")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--tag", default="raphael")
    args = parser.parse_args()

    try:
        from infer_rvc_python import BaseLoader

        only_cpu = str(args.device).lower() in {"cpu", "none"}
        converter = BaseLoader(only_cpu=only_cpu)
        converter.apply_conf(
            tag=args.tag,
            file_model=args.model,
            pitch_algo=args.pitch_method,
            pitch_lvl=args.pitch_semitones,
            file_index=args.index,
            index_influence=args.index_rate,
            respiration_median_filtering=3,
            envelope_ratio=0.25,
            consonant_breath_protection=args.protect,
        )
        send(sys.stdout.buffer, {"ok": True, "event": "ready"})
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        send(sys.stdout.buffer, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        return 1

    while True:
        try:
            request = recv(sys.stdin.buffer)
            if request is None:
                break
            if request.get("op") == "close":
                break
            if request.get("op") != "convert":
                raise ValueError(f"unknown RVC worker operation: {request.get('op')!r}")

            input_path = request.get("input_path")
            if not input_path or not os.path.isfile(input_path):
                raise FileNotFoundError(f"RVC input WAV not found: {input_path!r}")

            output_path = None
            try:
                result, output_rate = converter.generate_from_cache(
                    audio_data=input_path,
                    tag=args.tag,
                )

                # RVC can occasionally return peaks close to or above full
                # scale. Feeding those straight to the browser/sounddevice
                # makes the result sound clipped even when the DSP chain is
                # completely dry. Apply a small presentation gain, then keep
                # the peak below 0 dBFS without normalising quiet speech
                # upward into noise.
                result = np.asarray(result, dtype=np.float32)
                if result.ndim > 1:
                    result = np.mean(result, axis=1)

                if args.output_gain_db:
                    result *= 10.0 ** (args.output_gain_db / 20.0)

                if str(args.clarity_eq).lower() in {"1", "true", "yes", "on"}:
                    result = _clarity_eq(result, int(output_rate))

                dry_mix = max(0.0, min(1.0, float(args.dry_mix)))
                if dry_mix > 0.0:
                    dry, dry_rate = sf.read(
                        input_path, dtype="float32", always_2d=False
                    )
                    dry = np.asarray(dry, dtype=np.float32)
                    if dry.ndim > 1:
                        dry = np.mean(dry, axis=1)
                    if dry_rate != output_rate or len(dry) != len(result):
                        if len(dry) > 1 and len(result) > 1:
                            x_old = np.linspace(0.0, 1.0, num=len(dry), endpoint=False)
                            x_new = np.linspace(0.0, 1.0, num=len(result), endpoint=False)
                            dry = np.interp(x_new, x_old, dry).astype(np.float32)
                        else:
                            dry = np.resize(dry, result.shape).astype(np.float32)
                    result = (1.0 - dry_mix) * result + dry_mix * dry

                peak = float(np.max(np.abs(result))) if result.size else 0.0
                if peak > 0.89:
                    result *= 0.89 / peak
                result = np.clip(result, -0.89, 0.89)

                with tempfile.NamedTemporaryFile(
                    suffix=".wav",
                    prefix="great-sage-rvc-out-",
                    delete=False,
                ) as output_file:
                    output_path = output_file.name

                sf.write(output_path, result, int(output_rate), subtype="FLOAT")
                send(
                    sys.stdout.buffer,
                    {
                        "ok": True,
                        "output_path": output_path,
                        "sample_rate": int(output_rate),
                    },
                )
                output_path = None
            finally:
                if output_path:
                    try:
                        os.unlink(output_path)
                    except OSError:
                        pass
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            send(sys.stdout.buffer, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})

    try:
        converter.unload_models()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
