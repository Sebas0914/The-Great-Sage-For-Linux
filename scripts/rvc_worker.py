"""Persistent Raphael RVC worker.

Audio crosses the process boundary through temporary WAV files. The stdout
protocol therefore carries only small control messages, while RVC inference
and audio serialization stay inside this runtime process.
"""
from __future__ import annotations

import argparse
import os
import pickle
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
