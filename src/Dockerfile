FROM python:3.10-slim

WORKDIR /app

ENV PIP_PROGRESS_BAR=off \
    PYTHONDONTWRITEBYTECODE=1 \
    STREAMLIT_SERVER_FILE_WATCHER_TYPE=none \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Application source. Credentials are never baked into the image; see
# docker-compose.firebase.yml for optional Firestore logging.
COPY . .

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1

CMD ["streamlit", "run", "biosignal_viz.py", "--server.port=8501", "--server.address=0.0.0.0"]
