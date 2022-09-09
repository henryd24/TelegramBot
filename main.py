from tkinter import N
from pip import main
import telebot
import os

def init_telegram():
    global bot
    TOKEN = os.environ['TOKEN']
    bot = telebot.TeleBot(TOKEN, parse_mode=None)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.reply_to(message, "Que se dice jijueputas, a ver que quieren ver?")

@bot.message_handler(commands=['trm'])
def trm(message):
	bot.reply_to(message, "Que se dice jijueputas, a ver que quieren ver?")

def main():
    init_telegram()
    
if __name__ == "__main__":
    main()