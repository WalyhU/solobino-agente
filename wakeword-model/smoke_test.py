"""
Prueba rápida del pipeline ANTES de grabar datos reales.

Verifica, sin tocar tus datos:
  1. PyTorch ve la GPU.
  2. El modelo hace forward + backward + step.
  3. La exportación a ONNX funciona.
  4. onnxruntime carga el ONNX y produce la misma salida.

Uso (en el entorno de entrenamiento):
  python smoke_test.py

Si todo dice OK, el entorno está sano y puedes grabar + entrenar de verdad.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import torch

from features import N_FRAMES, N_MELS
from model import WakeWordCNN


def main() -> None:
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"1) PyTorch device: {device}  (cuda disponible: {torch.cuda.is_available()})")
    if device == "cuda":
        print(f"   GPU: {torch.cuda.get_device_name(0)}")

    model = WakeWordCNN().to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"   Parámetros del modelo: {n_params:,}")

    # 2) forward + backward
    x = torch.randn(8, 1, N_MELS, N_FRAMES, device=device)
    y = torch.randint(0, 2, (8,), device=device).float()
    opt = torch.optim.Adam(model.parameters(), lr=1e-3)
    loss_fn = torch.nn.BCEWithLogitsLoss()
    for step in range(5):
        opt.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        opt.step()
    print(f"2) forward/backward OK (loss final={loss.item():.4f})")

    # 3) export ONNX (a archivo temporal, NO al modelo real)
    model.eval()
    tmp = Path(tempfile.gettempdir()) / "wakeword_smoke.onnx"
    dummy = torch.randn(1, 1, N_MELS, N_FRAMES, device=device)
    torch.onnx.export(
        model, dummy, str(tmp),
        input_names=["mel"], output_names=["logit"],
        dynamic_axes={"mel": {0: "batch"}, "logit": {0: "batch"}},
        opset_version=17,
    )
    print(f"3) Export ONNX OK -> {tmp}")

    # 4) onnxruntime roundtrip
    import onnxruntime as ort
    sess = ort.InferenceSession(str(tmp), providers=["CPUExecutionProvider"])
    inp = dummy.cpu().numpy()
    onnx_out = sess.run(["logit"], {"mel": inp})[0].reshape(-1)
    with torch.no_grad():
        torch_out = model(dummy).cpu().numpy().reshape(-1)
    diff = float(np.abs(onnx_out - torch_out).max())
    print(f"4) onnxruntime OK (diff vs torch={diff:.2e})")

    tmp.unlink(missing_ok=True)
    print("\nTODO OK. Entorno listo para grabar y entrenar.")


if __name__ == "__main__":
    main()
