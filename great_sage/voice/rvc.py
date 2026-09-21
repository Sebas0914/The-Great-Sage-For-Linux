"""Local RVC v2 post-processing for the Raphael voice model."""
from __future__ import annotations
import os
from typing import Tuple
import numpy as np

class RVCVoiceConverter:
    """Preloaded RVC converter for low-latency audio-array conversion."""
    def __init__(self, *, model_path: str, index_path: str, pitch_method="rmvpe+",
                 index_rate=0.8, protect=0.33, pitch_semitones=0, device="cuda",
                 tag="raphael"):
        model_path=os.path.abspath(os.path.expanduser(model_path))
        index_path=os.path.abspath(os.path.expanduser(index_path))
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"Raphael RVC model not found: {model_path}")
        if not os.path.isfile(index_path):
            raise FileNotFoundError(f"Raphael RVC index not found: {index_path}")
        try:
            from infer_rvc_python import BaseLoader
        except ImportError as exc:
            raise RuntimeError("infer_rvc_python is not installed; run 'pip install -r requirements.txt'") from exc
        only_cpu=str(device).lower() in {"cpu","none"}
        self._converter=BaseLoader(only_cpu=only_cpu)
        self._tag=tag
        self._converter.apply_conf(tag=tag,file_model=model_path,pitch_algo=pitch_method,
            pitch_lvl=int(pitch_semitones),file_index=index_path,index_influence=float(index_rate),
            respiration_median_filtering=3,envelope_ratio=0.25,
            consonant_breath_protection=float(protect))
    def convert_array(self, samples, sample_rate: int) -> Tuple[np.ndarray,int]:
        audio=np.asarray(samples,dtype=np.float32)
        if audio.ndim>1: audio=np.mean(audio,axis=1)
        audio=np.ascontiguousarray(audio)
        result,output_rate=self._converter.generate_from_cache(
            audio_data=(audio,int(sample_rate)),tag=self._tag)
        return np.asarray(result,dtype=np.float32).reshape(-1),int(output_rate)
    def unload(self):
        fn=getattr(self._converter,"unload_models",None)
        if fn: fn()
