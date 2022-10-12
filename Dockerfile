FROM python:3.8-slim
RUN apt-get update
RUN apt-get install libxml2-dev libxslt1-dev python-dev -y
WORKDIR /usr/src/app
COPY requirements.txt ./
RUN pip install --upgrade pip
RUN pip install lxml
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir /tmp/telegrambot
CMD [ "python", "./main.py" ]
