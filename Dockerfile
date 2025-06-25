FROM python:3.11-slim AS builder
RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt1-dev \
    tzdata \
    --no-install-recommends && \ 
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --target=/app/requirements lxml
RUN pip install --no-cache-dir --target=/app/requirements -r requirements.txt


FROM python:3.11-slim
RUN useradd -ms /bin/bash telegrambot
COPY --from=builder /app/requirements /usr/local/lib/python3.11/site-packages
ENV TZ=America/Bogota
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ >/etc/timezone
WORKDIR /app
COPY . /app
USER telegrambot
ENTRYPOINT ["python", "./main.py"]
