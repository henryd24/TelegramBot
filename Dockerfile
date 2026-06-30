FROM astral/uv:python3.12-trixie-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libfreetype6-dev \
    libpng-dev \
    libopenblas-dev \
    python3-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Bogota \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib_cache \
    PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends \
    libstdc++6 \
    libfreetype6 \
    libpng16-16 \
    libopenblas0 \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN mkdir -p /tmp/matplotlib_cache && chmod 777 /tmp/matplotlib_cache
COPY --from=builder /app/.venv /app/.venv
COPY main.py .
COPY ./src ./src
USER 10001
ENTRYPOINT ["python", "main.py"]