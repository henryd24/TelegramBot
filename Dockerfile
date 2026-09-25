# ==============================================================================
# Stage 1: Builder (instala dependencias con uv sin paquetes de compilación C++)
# ==============================================================================
FROM astral/uv:python3.12-trixie-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project --no-dev && \
    find /app/.venv -type d \( -name "tests" -o -name "test" \) -exec rm -rf {} + 2>/dev/null || true

# ==============================================================================
# Stage 2: Runtime ligero (sin matplotlib/openblas ni capas duplicadas por chown)
# ==============================================================================
FROM python:3.12-slim-trixie

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=America/Bogota \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Copiar directamente con --chown evita duplicar la capa de .venv con RUN chown -R
COPY --from=builder --chown=10001:10001 /app/.venv /app/.venv
COPY --chown=10001:10001 main.py ./
COPY --chown=10001:10001 ./src ./src

USER 10001:10001

ENTRYPOINT ["python", "main.py"]