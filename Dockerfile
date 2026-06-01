# Root Dockerfile — used by Hugging Face Spaces (Docker SDK), which requires the
# Dockerfile at the repo root and serves the container on port 7860.
#
# This is identical to worker/Dockerfile (the one Render uses via an explicit
# Dockerfile Path). Both build the generation worker; keep them in sync.
FROM python:3.12-slim

# GEOS for shapely / libgomp for scipy threading.
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

CMD ["sh", "-c", "uvicorn worker.app:app --host 0.0.0.0 --port ${PORT:-7860}"]
