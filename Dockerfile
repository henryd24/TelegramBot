FROM python:3.11-slim
WORKDIR /app
RUN pip install uv
COPY pyproject.toml ./
RUN uv pip compile pyproject.toml -o requirements.txt && \
    uv pip sync requirements.txt --system
COPY . .
USER 10001
ENTRYPOINT ["python", "main.py"]
