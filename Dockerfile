FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt1-dev \
    --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /usr/src/app

COPY requirements.txt ./

RUN pip install --upgrade pip && \
    pip install --no-cache-dir lxml && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -ms /bin/bash telegrambot
USER telegrambot

ENTRYPOINT ["python", "./main.py"]
