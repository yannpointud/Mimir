# Mimir backend production image.
# glibc-based slim (NOT alpine): faiss-cpu / numpy ship manylinux wheels that
# require glibc; alpine (musl) would force a slow source build.
FROM python:3.13-slim

# Create a non-root system user/group up front (Elevation-of-Privilege
# mitigation). Source stays root-owned/read-only; only the writable
# data + logs dirs are chowned to this user below.
RUN groupadd --system mimir && useradd --system --gid mimir --home-dir /app --shell /usr/sbin/nologin mimir

WORKDIR /app

# Install the hash-pinned runtime lockfile first for better layer caching. It
# lives at the repo root, which is the build context (compose sets context: .).
COPY requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# Copy the backend source. The root .dockerignore strips secrets (.env*),
# runtime data (data/, logs/) and caches from the context, so this wildcard
# COPY cannot capture them (Information Disclosure mitigation).
COPY backend/ /app/

# Create the writable runtime dirs and hand them to the non-root user. The
# named volume mounted at /app/data inherits this ownership on first init.
RUN mkdir -p /app/data /app/logs && chown -R mimir:mimir /app/data /app/logs

# Drop privileges before running the app.
USER mimir

EXPOSE 8000

# Liveness probe targets the process-only /health/live route.
# Uses the already-present Python interpreter via urllib -- no extra curl
# package, keeping the image minimal.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=3).status == 200 else 1)"

# Single worker, no auto-reload: the in-memory FAISS singleton and the
# sequential ingestion queue are process-local and are NOT safe across multiple
# worker processes, so production MUST run exactly one uvicorn worker.
# Do not add --workers or --reload here.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
