FROM python:3.11.8-slim
RUN mkdir -p /tmp/matplotlib_cache && chmod 777 /tmp/matplotlib_cache
ENV MPLBACKEND=Agg
ENV MPLCONFIGDIR=/tmp/matplotlib_cache
WORKDIR /app
RUN pip install uv
COPY pyproject.toml ./
RUN uv pip compile pyproject.toml -o requirements.txt && \
    uv pip sync requirements.txt --system
COPY . .
USER 10001
ENTRYPOINT ["python", "main.py"]
