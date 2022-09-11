import telebot
import os
import getdata
TOKEN = os.environ['TOKEN']
bot = telebot.TeleBot(TOKEN, parse_mode=None)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.reply_to(message, "Que se dice jijueputas")

@bot.message_handler(commands=['trm'])
def trm(message):
    msg = getdata.parse_book()
    bot.reply_to(message, msg)


@bot.message_handler(commands=['upgames'])
def upcoming_releases(message):
    getdata.upcoming_releases()
    doc = open('/tmp/telegrambot/juegos.csv','rb')
    bot.send_document(message.chat.id,doc)
    doc.close()

def main():
    bot.infinity_polling()
    
if __name__ == "__main__":
    main()