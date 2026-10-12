"""
Inferencia del detector de wake-word en el backend, con onnxruntime.

Carga el modelo entrenado (wakeword-model/wakeword.onnx) y decide si un clip de
audio contiene "solobino". No requiere PyTorch: solo onnxruntime + numpy + av,
que ya están en el venv del backend. Reutiliza features.py del entrenamiento
para que las features sean idénticas a las usadas al entrenar.

Si el modelo aún no existe (no se ha entrenado), `WakeWordDetector.available`
es False y el backend cae al detector basado en Whisper.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

# Hacer importable features.py del proyecto del modelo.
_MODEL_DIR = (Path(sys._MEIPASS) if getattr(sys, "frozen", False)
              else Path(__file__).resolve().parent.parent) / "wakeword-model"
if str(_MODEL_DIR) not in sys.path:
    sys.path.insert(0, str(_MODEL_DIR))

_ONNX_PATH = _MODEL_DIR / "wakeword.onnx"
_META_PATH = _MODEL_DIR / "wakeword_meta.json"


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


class WakeWordDetector:
    def __init__(self) -> None:
        self.available = False
        self.session = None
        self.threshold = 0.5
        self._log_mel = None
        self._load_audio = None
        self._window = 16000
        self._hop = 8000

        if not _ONNX_PATH.exists():
            print(f"[WakeWord-CNN] No hay modelo en {_ONNX_PATH}. Usando Whisper como fallback.")
            return

        try:
            import onnxruntime as ort
            from features import WINDOW_SAMPLES, load_audio, log_mel

            # Preferir GPU si onnxruntime-gpu está instalado: baja inferencia de ~50ms a ~5ms.
            providers = ["CPUExecutionProvider"]
            try:
                available = set(ort.get_available_providers())
                if "CUDAExecutionProvider" in available:
                    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
            except Exception:
                pass

            self.session = ort.InferenceSession(str(_ONNX_PATH), providers=providers)
            print(f"[WakeWord-CNN] Providers activos: {self.session.get_providers()}")
            self._log_mel = log_mel
            self._load_audio = load_audio
            self._window = WINDOW_SAMPLES
            self._hop = WINDOW_SAMPLES // 2

            if _META_PATH.exists():
                meta = json.loads(_META_PATH.read_text())
                self.threshold = float(meta.get("threshold", 0.5))

            # Override manual del umbral (sube para reducir falsos positivos).
            import os
            env_thr = os.getenv("WAKEWORD_THRESHOLD")
            if env_thr:
                try:
                    self.threshold = float(env_thr)
                except ValueError:
                    pass

            self.available = True
            print(f"[WakeWord-CNN] Modelo cargado. Umbral={self.threshold:.3f}")
        except Exception as e:
            print(f"[WakeWord-CNN] No se pudo cargar el modelo: {e}. Usando Whisper.")
            self.available = False

    def _windows(self, samples: np.ndarray) -> list[np.ndarray]:
        if len(samples) <= self._window:
            return [samples]
        out = []
        for start in range(0, len(samples) - self._window + 1, self._hop):
            out.append(samples[start : start + self._window])
        # Incluir el final por si la palabra cae justo al borde.
        out.append(samples[-self._window :])
        return out

    def score(self, audio_bytes: bytes) -> float:
        """Devuelve la probabilidad máxima de wake-word sobre el clip."""
        if not self.available:
            return 0.0

        samples = self._load_audio(audio_bytes)
        return self.score_samples(samples)

    def score_samples(self, samples: np.ndarray) -> float:
        """Evalúa PCM mono float32 a 16 kHz sin decodificar un contenedor."""
        if not self.available:
            return 0.0
        samples = np.asarray(samples, dtype=np.float32)
        if len(samples) == 0:
            return 0.0

        mels = [self._log_mel(w) for w in self._windows(samples)]
        batch = np.stack(mels)[:, None, :, :].astype(np.float32)  # (N,1,mels,frames)

        logits = self.session.run(["logit"], {"mel": batch})[0].reshape(-1)
        return float(_sigmoid(logits).max())

    def is_wake(self, audio_bytes: bytes) -> tuple[bool, float]:
        prob = self.score(audio_bytes)
        return prob >= self.threshold, prob
