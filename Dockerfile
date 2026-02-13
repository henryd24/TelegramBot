FROM astral/uv:python3.11-alpine AS builder
RUN apk add --no-cache \
    gcc \
    g++ \
    musl-dev \
    linux-headers \
    freetype-dev \
    libpng-dev \
    openblas-dev
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

FROM python:3.11-alpine
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Bogota \
    MPLBACKEND=Agg \
    MPLCONFIGDIR=/tmp/matplotlib_cache \
    PATH="/app/.venv/bin:$PATH"
RUN apk add --no-cache libstdc++ freetype libpng openblas
WORKDIR /app
RUN mkdir -p /tmp/matplotlib_cache && chmod 777 /tmp/matplotlib_cache
COPY --from=builder /app/.venv /app/.venv
COPY main.py .
COPY ./src ./src
USER 10001
ENTRYPOINT ["python", "main.py"]