# Generation worker image. Build context = repo root:
#   docker build -f worker/Dockerfile -t mapgen-worker .
# Hugging Face Spaces (Docker SDK) builds this automatically and serves on 7860.
FROM python:3.12-slim

# GEOS for shapely / libgomp for scipy threading (manylinux wheels usually
# bundle these, but install them to be safe across base images).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 libgeos-c1v5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first for better layer caching.
COPY requirements-mapgen.txt ./requirements-mapgen.txt
COPY worker/requirements.txt ./worker-requirements.txt
RUN pip install --no-cache-dir -r requirements-mapgen.txt -r worker-requirements.txt

# App code (the mapgen package + the worker entrypoint).
COPY mapgen ./mapgen
COPY worker ./worker

ENV WORKER_OUTPUTS=/tmp/mapgen-out \
    PORT=7860
EXPOSE 7860

# Honour $PORT (HF Spaces=7860, Cloud Run/Render inject their own).
CMD ["sh", "-c", "uvicorn worker.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
