FROM python:3.8-slim

WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir /tmp/telegrambot
CMD [ "python", "./main.py" ]