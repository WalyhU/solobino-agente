# Sandbox del backend de Solobino: CPU, sin GPU, sin pantalla.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SOLOBINO_HOST=0.0.0.0 \
    SOLOBINO_PORT=8000 \
    WHISPER_MODEL_SIZE=tiny \
    WHISPER_DEVICE=cpu \
    WHISPER_COMPUTE_TYPE=int8

WORKDIR /app

COPY voice-backend/requirements.txt voice-backend/requirements.txt
RUN pip install -r voice-backend/requirements.txt

COPY voice-backend/ voice-backend/
COPY wakeword-model/features.py wakeword-model/wakeword.onnx wakeword-model/wakeword_meta.json wakeword-model/

# Usuario sin privilegios dentro del contenedor.
# La carpeta de caché debe existir con este dueño: así el volumen nombrado
# hereda los permisos y Whisper puede descargar el modelo.
RUN useradd --create-home solobino \
 && mkdir -p /home/solobino/.cache/huggingface \
 && chown -R solobino /app /home/solobino/.cache
USER solobino

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "voice-backend/main.py"]
