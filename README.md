# Telegram Bot for CaguanGroup

---

> **Parameters:** </p>
> -t,--token: Telegram bot token to connect in telegram *</p>

## Run bot python

_Requirements: python 3 and pip_

To run the bot we must first install the necessary libraries that are in the file requerimenst.txt:

- ```bash
    pip install -r requirements.txt

- ```bash
    python main.py <parameters>

---

## Run bot with Dockerfile

To run it with docker:

- ```bash
    docker build -t telegrambot .

- ```bash
    docker run telegrambot <parameters>

If you need pass session file use volumes or add into root folder after pass the path in --file parameter.

---


