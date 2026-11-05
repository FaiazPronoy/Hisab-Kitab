FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/models FASTEMBED_CACHE_PATH=/opt/models/fastembed
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr libglib2.0-0 libgomp1 \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements-dev.txt ./
ARG DEV=0
RUN pip install -r requirements.txt && if [ "$DEV" = "1" ]; then pip install -r requirements-dev.txt; fi

# fetch OCR and embedding models at build time so workers start offline
RUN mkdir -p /opt/models && python -c "from rapidocr import RapidOCR; RapidOCR()" \
    && python -c "from fastembed import TextEmbedding; list(TextEmbedding('BAAI/bge-small-en-v1.5').embed(['warm up']))" \
    && chmod -R a+rwX /opt/models

COPY backend/ ./
COPY eval ./eval
COPY scripts ./scripts
RUN useradd -m -u 1000 app && mkdir -p /data/storage && chown -R app /data /app
USER app
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
