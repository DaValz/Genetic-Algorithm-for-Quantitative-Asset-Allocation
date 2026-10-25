FROM python:3.12-slim

# Several sessions share one process: single-threaded BLAS avoids oversubscribing the CPU when many users launch the
# algorithm together (measured: ~2x faster risk previews with 8 simultaneous launches on a 12-core machine).
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# the app reads its prices from the bundled archive: fail the build, not the first user, if it is missing
RUN python -c "from goalga import snapshot; assert snapshot.available(), 'data/prices_monthly.parquet is missing'"
# non-root user; /data holds the accounts database (SQLite) - mount a volume there, or set GOALGA_DATABASE_URL
RUN useradd --create-home --uid 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

ENV GOALGA_DB_PATH=/data/goalga.db
VOLUME ["/data"]

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
