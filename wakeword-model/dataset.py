"""
Dataset de wake-word para PyTorch.

Carga los wav de data/positives (label 1) y data/negatives (label 0), calcula
log-mel con features.py (mismo código que la inferencia) y aplica data
augmentation en entrenamiento para que el modelo generalice con pocos datos.
"""

from __future__ import annotations

import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from features import (
    N_FRAMES,
    N_MELS,
    WINDOW_SAMPLES,
    fix_length,
    load_audio,
    log_mel,
)

DATA_DIR = Path(__file__).parent / "data"


def list_samples() -> list[tuple[Path, int]]:
    items: list[tuple[Path, int]] = []
    for wav in (DATA_DIR / "positives").glob("*.wav"):
        items.append((wav, 1))
    for wav in (DATA_DIR / "negatives").glob("*.wav"):
        items.append((wav, 0))
    return items


def _augment_waveform(samples: np.ndarray) -> np.ndarray:
    """Aumentos en el dominio del tiempo (solo entrenamiento)."""
    samples = fix_length(samples)

    # Desplazamiento temporal (la palabra no siempre arranca en t=0).
    shift = random.randint(-WINDOW_SAMPLES // 5, WINDOW_SAMPLES // 5)
    samples = np.roll(samples, shift)

    # Ganancia aleatoria.
    samples = samples * random.uniform(0.6, 1.3)

    # Ruido gaussiano leve.
    if random.random() < 0.5:
        samples = samples + np.random.normal(0, random.uniform(0.001, 0.01), samples.shape)

    return samples.astype(np.float32)


def _spec_augment(mel: np.ndarray) -> np.ndarray:
    """Enmascara bandas de frecuencia y tiempo (SpecAugment)."""
    mel = mel.copy()
    if random.random() < 0.5:  # máscara de frecuencia
        f = random.randint(1, N_MELS // 5)
        f0 = random.randint(0, N_MELS - f)
        mel[f0 : f0 + f, :] = 0.0
    if random.random() < 0.5:  # máscara de tiempo
        t = random.randint(1, N_FRAMES // 5)
        t0 = random.randint(0, N_FRAMES - t)
        mel[:, t0 : t0 + t] = 0.0
    return mel


class WakeWordDataset(Dataset):
    def __init__(self, items: list[tuple[Path, int]], train: bool) -> None:
        self.items = items
        self.train = train
        # Cachea las waveforms (datasets pequeños caben en RAM).
        self._cache: dict[Path, np.ndarray] = {}

    def __len__(self) -> int:
        return len(self.items)

    def _waveform(self, path: Path) -> np.ndarray:
        if path not in self._cache:
            self._cache[path] = fix_length(load_audio(str(path)))
        return self._cache[path]

    def __getitem__(self, i: int):
        path, label = self.items[i]
        samples = self._waveform(path)

        if self.train:
            samples = _augment_waveform(samples)

        mel = log_mel(samples)
        if self.train:
            mel = _spec_augment(mel)

        x = torch.from_numpy(mel).unsqueeze(0)  # (1, N_MELS, N_FRAMES)
        y = torch.tensor(float(label))
        return x, y
