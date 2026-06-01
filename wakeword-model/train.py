"""
Entrena la CNN de wake-word y exporta a ONNX para el backend.

Uso (en el entorno de entrenamiento, Python 3.12 + torch CUDA):
  python train.py --epochs 40 --batch 32

Salidas (en este directorio):
  wakeword.onnx        modelo para onnxruntime (lo usa el backend)
  wakeword_meta.json   parámetros de features + umbral de decisión
  wakeword_best.pt     checkpoint PyTorch (por si quieres seguir entrenando)
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from dataset import WakeWordDataset, list_samples
from features import HOP, N_FFT, N_FRAMES, N_MELS, SAMPLE_RATE, WINDOW_SAMPLES
from model import WakeWordCNN

HERE = Path(__file__).parent
SEED = 42


def set_seed() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)


def split(items, val_frac=0.2):
    random.shuffle(items)
    n_val = max(1, int(len(items) * val_frac))
    return items[n_val:], items[:n_val]


@torch.no_grad()
def evaluate(model, loader, device):
    model.eval()
    probs, labels = [], []
    for x, y in loader:
        logit = model(x.to(device))
        probs.append(torch.sigmoid(logit).cpu().numpy())
        labels.append(y.numpy())
    return np.concatenate(probs), np.concatenate(labels)


def best_threshold(probs, labels):
    """Umbral que maximiza F1 en validación."""
    best_t, best_f1 = 0.5, -1.0
    for t in np.linspace(0.1, 0.9, 81):
        pred = (probs >= t).astype(int)
        tp = int(((pred == 1) & (labels == 1)).sum())
        fp = int(((pred == 1) & (labels == 0)).sum())
        fn = int(((pred == 0) & (labels == 1)).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        if f1 > best_f1:
            best_f1, best_t = f1, float(t)
    return best_t, best_f1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--lr", type=float, default=1e-3)
    args = parser.parse_args()

    set_seed()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Dispositivo: {device}")

    items = list_samples()
    n_pos = sum(1 for _, y in items if y == 1)
    n_neg = len(items) - n_pos
    print(f"Muestras: {len(items)} (pos={n_pos}, neg={n_neg})")
    if n_pos < 20 or n_neg < 20:
        print("AVISO: pocas muestras. Graba más con record_samples.py para buen resultado.")

    train_items, val_items = split(items)
    train_ds = WakeWordDataset(train_items, train=True)
    val_ds = WakeWordDataset(val_items, train=False)
    train_dl = DataLoader(train_ds, batch_size=args.batch, shuffle=True)
    val_dl = DataLoader(val_ds, batch_size=args.batch)

    model = WakeWordCNN().to(device)

    # Pondera la clase positiva si hay desbalance.
    pos_weight = torch.tensor([n_neg / max(n_pos, 1)], device=device)
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = torch.optim.Adam(model.parameters(), lr=args.lr, weight_decay=1e-4)

    best_acc = -1.0
    best_state = None

    for epoch in range(1, args.epochs + 1):
        model.train()
        total_loss = 0.0
        for x, y in train_dl:
            x, y = x.to(device), y.to(device)
            optimizer.zero_grad()
            loss = criterion(model(x), y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item() * len(x)

        probs, labels = evaluate(model, val_dl, device)
        acc = float(((probs >= 0.5).astype(int) == labels).mean())
        print(f"epoch {epoch:3d}  loss={total_loss / len(train_ds):.4f}  val_acc={acc:.3f}")

        if acc >= best_acc:
            best_acc = acc
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

    # Restaura el mejor modelo y fija umbral.
    model.load_state_dict(best_state)
    probs, labels = evaluate(model, val_dl, device)
    threshold, f1 = best_threshold(probs, labels)
    print(f"\nMejor val_acc={best_acc:.3f}  umbral={threshold:.3f}  F1={f1:.3f}")

    torch.save(best_state, HERE / "wakeword_best.pt")

    # Exportar a ONNX (el backend infiere con onnxruntime, sin torch).
    model.eval()
    dummy = torch.randn(1, 1, N_MELS, N_FRAMES, device=device)
    onnx_path = HERE / "wakeword.onnx"
    torch.onnx.export(
        model,
        dummy,
        str(onnx_path),
        input_names=["mel"],
        output_names=["logit"],
        dynamic_axes={"mel": {0: "batch"}, "logit": {0: "batch"}},
        opset_version=17,
    )

    meta = {
        "sample_rate": SAMPLE_RATE,
        "n_mels": N_MELS,
        "n_frames": N_FRAMES,
        "n_fft": N_FFT,
        "hop": HOP,
        "window_samples": WINDOW_SAMPLES,
        "threshold": threshold,
        "val_acc": best_acc,
        "val_f1": f1,
    }
    (HERE / "wakeword_meta.json").write_text(json.dumps(meta, indent=2))

    print(f"Exportado: {onnx_path.name} + wakeword_meta.json")


if __name__ == "__main__":
    main()
