# Multi-target image: `--target backend` (FastAPI) or `--target frontend` (Streamlit).

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN useradd --create-home --uid 1000 app
WORKDIR /app

# ---------------------------------------------------------------- backend
FROM base AS backend
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements.txt
# CPU-only PyTorch keeps the image small; Sentence Transformers uses it for embeddings.
RUN pip install --extra-index-url https://download.pytorch.org/whl/cpu -r backend/requirements.txt
COPY backend backend
COPY knowledge_base knowledge_base
COPY scripts scripts
RUN mkdir -p data/uploads data/processed data/reports data/index data/models data/sample && chown -R app:app /app
USER app
WORKDIR /app/backend
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD curl -fs http://localhost:8000/health || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers"]

# --------------------------------------------------------------- frontend
FROM base AS frontend
COPY frontend/requirements.txt frontend/requirements.txt
RUN pip install -r frontend/requirements.txt
COPY frontend frontend
RUN chown -R app:app /app
USER app
WORKDIR /app/frontend
EXPOSE 8501
CMD ["sh", "-c", "streamlit run app.py --server.address 0.0.0.0 --server.port ${PORT:-8501} --server.headless true"]
