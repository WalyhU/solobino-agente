"""
Extracción de características de audio (log-mel spectrogram), en NumPy puro.

Este módulo lo usan TANTO el entrenamiento (PyTorch) COMO la inferencia del
backend (onnxruntime). Compartirlo garantiza que las features sean idénticas en
ambos lados; cualquier diferencia rompería el modelo.

Decodificación de audio vía PyAV (`av`), que ya es dependencia de faster-whisper.
Soporta wav (entrenamiento) y webm/opus (audio que manda Electron).
"""

from __future__ import annotations

import io

import numpy as np

# --- Parámetros del front-end de audio (FIJOS: cámbialos en un solo sitio) ---
SAMPLE_RATE = 16000
N_FFT = 400          # 25 ms
HOP = 160            # 10 ms
N_MELS = 40
FMIN = 20.0
FMAX = 8000.0
WINDOW_SECONDS = 1.0
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SECONDS)   # 16000
# Frames resultantes para una ventana de 1 s (framing sin centrado):
N_FRAMES = 1 + (WINDOW_SAMPLES - N_FFT) // HOP        # 98

_EPS = 1e-10


def _hz_to_mel(hz: np.ndarray) -> np.ndarray:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: np.ndarray) -> np.ndarray:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank() -> np.ndarray:
    """Matriz de filtros mel (N_MELS, N_FFT//2 + 1)."""
    n_freqs = N_FFT // 2 + 1
    fft_freqs = np.linspace(0, SAMPLE_RATE / 2, n_freqs)

    mel_min, mel_max = _hz_to_mel(np.array([FMIN])), _hz_to_mel(np.array([FMAX]))
    mel_points = np.linspace(mel_min[0], mel_max[0], N_MELS + 2)
    hz_points = _mel_to_hz(mel_points)

    fb = np.zeros((N_MELS, n_freqs), dtype=np.float32)
    for m in range(1, N_MELS + 1):
        f_left, f_center, f_right = hz_points[m - 1], hz_points[m], hz_points[m + 1]
        left = (fft_freqs - f_left) / max(f_center - f_left, 1e-6)
        right = (f_right - fft_freqs) / max(f_right - f_center, 1e-6)
        fb[m - 1] = np.clip(np.minimum(left, right), 0.0, None)
    return fb


_MEL_FB = _mel_filterbank()
_HANN = np.hanning(N_FFT).astype(np.float32)


def fix_length(samples: np.ndarray) -> np.ndarray:
    """Recorta o rellena con ceros a exactamente WINDOW_SAMPLES."""
    if len(samples) >= WINDOW_SAMPLES:
        return samples[:WINDOW_SAMPLES]
    out = np.zeros(WINDOW_SAMPLES, dtype=np.float32)
    out[: len(samples)] = samples
    return out


def log_mel(samples: np.ndarray) -> np.ndarray:
    """
    samples: float32 mono @ 16 kHz, longitud arbitraria.
    Devuelve log-mel (N_MELS, N_FRAMES) float32, normalizado por-instancia.
    """
    samples = fix_length(np.asarray(samples, dtype=np.float32))

    # Framing (sin centrado).
    n_frames = 1 + (len(samples) - N_FFT) // HOP
    idx = np.arange(N_FFT)[None, :] + HOP * np.arange(n_frames)[:, None]
    frames = samples[idx] * _HANN                      # (n_frames, N_FFT)

    spectrum = np.fft.rfft(frames, n=N_FFT, axis=1)
    power = (np.abs(spectrum) ** 2).astype(np.float32)  # (n_frames, n_freqs)

    mel = power @ _MEL_FB.T                              # (n_frames, N_MELS)
    log = np.log(mel + _EPS).T                           # (N_MELS, n_frames)

    # Normalización por instancia (media 0, std 1). Estabiliza el entrenamiento.
    log = (log - log.mean()) / (log.std() + 1e-5)
    return log.astype(np.float32)


def load_audio(source) -> np.ndarray:
    """
    Decodifica audio a float32 mono @ 16 kHz usando PyAV.
    `source`: ruta a archivo (str) o bytes (p. ej. webm de Electron).
    """
    import av  # PyAV; dependencia de faster-whisper.

    if isinstance(source, (bytes, bytearray)):
        container = av.open(io.BytesIO(bytes(source)))
    else:
        container = av.open(source)

    resampler = av.audio.resampler.AudioResampler(
        format="flt", layout="mono", rate=SAMPLE_RATE
    )

    chunks: list[np.ndarray] = []
    try:
        for frame in container.decode(audio=0):
            for rs in resampler.resample(frame):
                arr = rs.to_ndarray().reshape(-1).astype(np.float32)
                chunks.append(arr)
    finally:
        container.close()

    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks)
