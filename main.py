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
    data = getdata.parse_book()
    msg = ''
    for trm in reversed(data):
        txt = """Conversion: {stock_name}
Valor Actual: {current_price}
Cierre Anterior: {previous_closing}
-------------------\n""".format(stock_name=trm['stock_name'],
                                current_price=trm['current_price'],
                                previous_closing=trm['previous_closing'])
        msg = txt+msg
    bot.reply_to(message, msg)


@bot.message_handler(commands=['upgames'])
def upcoming_releases(message):
    getdata.upcoming_releases()
    with open('/tmp/telegrambot/juegos.csv','rb') as file:
        doc = file.read()
        bot.send_document(message.chat.id,doc)

def main():
    bot.infinity_polling()
    
if __name__ == "__main__":
    main()