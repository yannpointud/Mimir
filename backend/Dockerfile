# Mimir backend production image.
# glibc-based slim (NOT alpine): faiss-cpu / numpy ship manylinux wheels that
# require glibc; alpine (musl) would force a slow source build (RESEARCH A1).
FROM python:3.11-slim

# Create a non-root system user/group up front (Elevation-of-Privilege
# mitigation T-05-05-02). Source stays root-owned/read-only; only the writable
# data + logs dirs are chowned to this user below.
RUN groupadd --system mimir && useradd --system --gid mimir --home-dir /app --shell /usr/sbin/nologin mimir

WORKDIR /app

# Install dependencies first for better layer caching. requirements.txt lives at
# the repo root, which is the build context (compose sets context: .).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the backend source. The root .dockerignore strips secrets (.env*),
# runtime data (data/, logs/) and caches from the context, so this wildcard
# COPY cannot capture them (Information Disclosure mitigation T-05-05-01).
COPY backend/ /app/

# Create the writable runtime dirs and hand them to the non-root user. The
# named volume mounted at /app/data inherits this ownership on first init
# (RESEARCH Pitfall 2: volume ownership).
RUN mkdir -p /app/data /app/logs && chown -R mimir:mimir /app/data /app/logs

# Drop privileges before running the app.
USER mimir

EXPOSE 8000

# Liveness probe targets the process-only /health/live route from plan 05-01.
# Uses the already-present Python interpreter via urllib -- no extra curl
# package, keeping the image minimal (RESEARCH Open Question 3).
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/api/v1/health/live', timeout=3).status == 200 else 1)"

# Single worker, no auto-reload: the in-memory FAISS singleton and the
# sequential ingestion queue are process-local and are NOT safe across multiple
# worker processes, so production MUST run exactly one uvicorn worker
# (RESEARCH Pitfall 5). Do not add --workers or --reload here.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
