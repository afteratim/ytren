FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# ---------------------------------------------------------
# System packages
# ---------------------------------------------------------

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    gcc \
    g++ \
    make \
    libc6-dev \
    python3-dev \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# Node.js
# ---------------------------------------------------------

RUN curl -fsSL https://deb.nodesource.com/setup_26.x | bash - \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# Application
# ---------------------------------------------------------

WORKDIR /app

COPY requirements.txt .

RUN python -m pip install --upgrade \
    pip \
    setuptools \
    wheel

RUN pip install -r requirements.txt

# ---------------------------------------------------------
# Bgutil PO-token provider
# ---------------------------------------------------------

WORKDIR /opt

RUN git clone \
    --single-branch \
    --branch 2.0.0 \
    https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git \
    bgutil-ytdlp-pot-provider

WORKDIR /opt/bgutil-ytdlp-pot-provider/server

RUN npm ci --no-audit --no-fund

RUN npx tsc

# ---------------------------------------------------------
# Application source
# ---------------------------------------------------------

WORKDIR /app

COPY . .

# ---------------------------------------------------------
# Start
# ---------------------------------------------------------

CMD ["sh", "-c", "node /opt/bgutil-ytdlp-pot-provider/server/build/main.js --host 127.0.0.1 --port 4416 & exec gunicorn --bind 0.0.0.0:${PORT} --workers 1 --threads 4 --timeout 1200 wsgi:app"]
