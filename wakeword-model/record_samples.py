"""
Graba muestras de audio para entrenar el detector de wake-word.

Uso:
  python record_samples.py --label pos --count 100   # di "solobino" en cada clip
  python record_samples.py --label neg --count 200   # habla otras cosas / silencio

Cada clip dura 1 s (WINDOW_SECONDS). Se guarda como wav mono 16 kHz en:
  data/positives/  (label pos)
  data/negatives/  (label neg)

Consejos para un buen dataset:
- Positivos (~150+): di "solobino" con distintos tonos, velocidades, distancias al
  micro, y algo de ruido de fondo real.
- Negativos (~300+): otras palabras, frases, silencio, ruido, TV, música.
  Cuantos más y más variados, menos falsos positivos.
"""

from __future__ import annotations

import argparse
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from features import SAMPLE_RATE, WINDOW_SECONDS, WINDOW_SAMPLES

DATA_DIR = Path(__file__).parent / "data"


def record_clip() -> np.ndarray:
    audio = sd.rec(WINDOW_SAMPLES, samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    return audio.reshape(-1)


def save_wav(path: Path, samples: np.ndarray) -> None:
    pcm16 = np.clip(samples, -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(pcm16.tobytes())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", choices=["pos", "neg"], required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--gap", type=float, default=0.6, help="pausa entre clips (s)")
    args = parser.parse_args()

    sub = "positives" if args.label == "pos" else "negatives"
    out_dir = DATA_DIR / sub
    out_dir.mkdir(parents=True, exist_ok=True)

    existing = len(list(out_dir.glob("*.wav")))
    prompt = "Di 'solobino'" if args.label == "pos" else "Habla / ruido / silencio"

    print(f"Grabando {args.count} clips de {WINDOW_SECONDS}s en {out_dir}")
    print(f"Ya existen {existing} clips. {prompt} cuando veas REC.\n")

    for i in range(args.count):
        print(f"[{i + 1}/{args.count}] preparado...", end="", flush=True)
        time.sleep(args.gap)
        print(" REC", end="", flush=True)
        clip = record_clip()
        idx = existing + i
        save_wav(out_dir / f"{args.label}_{idx:05d}.wav", clip)
        peak = float(np.max(np.abs(clip)))
        warn = "  (¡muy bajo!)" if peak < 0.02 else ""
        print(f"  ok  pico={peak:.2f}{warn}")

    print(f"\nListo. Total {sub}: {len(list(out_dir.glob('*.wav')))} clips.")


if __name__ == "__main__":
    main()
