FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    libxml2-dev \
    libxslt1-dev \
    tzdata \
    --no-install-recommends &&
    apt-get clean &&
    rm -rf /var/lib/apt/lists/*

ENV TZ=America/Bogota

RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ >/etc/timezone

WORKDIR /usr/src/app

COPY requirements.txt ./

RUN pip install --upgrade pip &&
    pip install --no-cache-dir lxml &&
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd -ms /bin/bash telegrambot
USER telegrambot

ENTRYPOINT ["python", "./main.py"]
