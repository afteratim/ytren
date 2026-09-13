FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1


# ============================================================
# SYSTEM DEPENDENCIES
# ============================================================

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    gcc \
    g++ \
    make \
    libc6-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*


# ============================================================
# APPLICATION
# ============================================================

WORKDIR /app


# ============================================================
# PYTHON DEPENDENCIES
# ============================================================

COPY requirements.txt .

RUN python -m pip install --upgrade \
    pip \
    setuptools \
    wheel

RUN pip install -r requirements.txt


# ============================================================
# COPY APPLICATION
# ============================================================

COPY . .


# ============================================================
# START SERVER
# ============================================================

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 1200 wsgi:app"]
