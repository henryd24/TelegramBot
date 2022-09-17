from operator import index
import telebot
import os
import getdata
TOKEN = os.environ['TOKEN']
bot = telebot.TeleBot(TOKEN, parse_mode=None)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.reply_to(message, "Que se dice Caguaneros")

@bot.message_handler(commands=['trm'])
def trm(message):
    msg = getdata.parse_book()
    bot.reply_to(message, msg)


@bot.message_handler(commands=['upgames'])
def upcoming_releases(message):
    table = getdata.upcoming_releases()
    bot.reply_to(message, table)

def main():
    try:
        print('Iniciando Bot')
        print('--------------------------------')
        bot.infinity_polling()
    except:
        print('Finalizando Bot')
        print('--------------------------------')
        
    
if __name__ == "__main__":
    main()