# Detector de wake-word "solobino" — red neuronal propia

CNN de clasificación binaria (¿se dijo "solobino"?) definida y entrenada **desde
cero** en PyTorch. Se entrena en un entorno aparte con GPU, se exporta a **ONNX**,
y el backend lo ejecuta con `onnxruntime` (sin necesidad de PyTorch).

## Por qué dos entornos

El backend corre en **Python 3.14**, que aún no tiene wheels de PyTorch. Por eso:

- **Entrenar**: entorno separado con **Python 3.13 + PyTorch CUDA** (GPU NVIDIA).
- **Inferir**: el backend (Python 3.14) carga `wakeword.onnx` con `onnxruntime`
  (ya instalado). El front-end de features (`features.py`) es NumPy puro y se
  comparte entre ambos lados para que las features sean idénticas.

## Pipeline

```
record_samples.py ─► data/positives/*.wav , data/negatives/*.wav
                          │
                     dataset.py (log-mel + augmentation)
                          │
                     train.py (CNN model.py, GPU) ─► wakeword.onnx + wakeword_meta.json
                          │
        voice-backend/wakeword_infer.py (onnxruntime) ─► detección en vivo
```

## 1. Crear el entorno de entrenamiento (una vez)

Instala **Python 3.13** desde python.org (puede coexistir con el 3.14). Luego:

```powershell
cd wakeword-model
py -3.13 -m venv venv-train
./venv-train/Scripts/Activate.ps1
pip install torch --index-url https://download.pytorch.org/whl/cu124
pip install -r requirements-train.txt
python -c "import torch; print('CUDA:', torch.cuda.is_available())"   # debe decir True
```

## 1b. Verificar el entorno (smoke test)

Antes de grabar 450 clips, confirma que todo funciona:

```powershell
python smoke_test.py
```

Debe imprimir `cuda disponible: True` y `TODO OK`. Si falla aquí, arregla el
entorno antes de seguir.

## 2. Grabar muestras

Con el entorno activo (necesita micrófono):

```powershell
python record_samples.py --label pos --count 150   # di "solobino" en cada REC
python record_samples.py --label neg --count 300   # otras palabras, silencio, ruido
```

Recomendado: **150+ positivos** y **300+ negativos**, variados (tono, velocidad,
distancia, ruido de fondo). Más datos = menos falsos positivos.

## 3. Entrenar y exportar

```powershell
python train.py --epochs 40 --batch 32
```

Genera en esta carpeta:
- `wakeword.onnx` — modelo para el backend.
- `wakeword_meta.json` — parámetros de features + umbral óptimo (F1 en validación).
- `wakeword_best.pt` — checkpoint PyTorch.

## 4. Usar en el backend

`voice-backend/wakeword_infer.py` busca `wakeword.onnx` en esta carpeta. El
instalador del cliente incluye el modelo y evalúa ventanas de audio solapadas
en Windows y macOS; el backend confirma con Whisper los candidatos. Si el
detector local no carga, el cliente vuelve al detector remoto. Para usar la CNN
también en el backend, configura `WAKEWORD_USE_CNN=true`; por defecto allí se
usa Whisper.

Para reentrenar (más datos u otra palabra), repite los pasos y reinicia el backend.

## Ajustes

- **Demasiados falsos positivos**: graba más negativos y sube el umbral en
  `wakeword_meta.json` (p. ej. 0.6–0.7).
- **No detecta la voz**: graba más positivos y reentrena.
- **Calibración del cliente**: el umbral efectivo tiene un mínimo de 0.70 y
  una ventana requiere 0.82 de confianza, o dos ventanas consecutivas al
  umbral mínimo. Cada candidato requiere confirmación textual de Whisper.
  Prueba con voces y micrófonos que no estén en el conjunto de entrenamiento.
- **Cambiar de palabra**: regraba positivos diciendo la palabra nueva y reentrena
  (el modelo no depende del texto, solo del sonido).

## Archivos

| Archivo | Rol |
|---|---|
| `features.py` | Log-mel en NumPy. **Compartido** con el backend (paridad de features). |
| `record_samples.py` | Captura clips de 1 s del micrófono. |
| `dataset.py` | Dataset PyTorch + data augmentation. |
| `model.py` | Arquitectura CNN (desde cero). |
| `train.py` | Entrenamiento, umbral y export ONNX. |
