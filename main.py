import telebot
import os
import gettrm
TOKEN = os.environ['TOKEN']
bot = telebot.TeleBot(TOKEN, parse_mode=None)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.reply_to(message, "Que se dice jijueputas")

@bot.message_handler(commands=['trm'])
def trm(message):
    data = gettrm.parse_book()
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

def main():
    bot.infinity_polling()
    
if __name__ == "__main__":
    main()