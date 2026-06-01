"""
CNN propia para detección de wake-word "solobino" (clasificación binaria).

Arquitectura definida desde cero (no es un modelo preentrenado). Entrada:
log-mel spectrogram (1, N_MELS, N_FRAMES). Salida: 1 logit -> sigmoide -> P(wake).
Modelo pequeño (~80k parámetros), de sobra para la GPU y para correr en CPU.
"""

from __future__ import annotations

import torch
import torch.nn as nn


class WakeWordCNN(nn.Module):
    def __init__(self) -> None:
        super().__init__()

        def block(in_ch: int, out_ch: int) -> nn.Sequential:
            return nn.Sequential(
                nn.Conv2d(in_ch, out_ch, kernel_size=3, padding=1),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
                nn.MaxPool2d(2),
            )

        self.features = nn.Sequential(
            block(1, 16),    # (1,40,98)  -> (16,20,49)
            block(16, 32),   # -> (32,10,24)
            block(32, 64),   # -> (64,5,12)
        )
        self.pool = nn.AdaptiveAvgPool2d(1)   # -> (64,1,1)
        self.classifier = nn.Sequential(
            nn.Flatten(),
            nn.Dropout(0.3),
            nn.Linear(64, 1),                 # 1 logit
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (B, 1, N_MELS, N_FRAMES)
        x = self.features(x)
        x = self.pool(x)
        return self.classifier(x).squeeze(1)  # (B,)
