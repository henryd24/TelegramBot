import argparse
import telebot,logging
from src import *

parser = argparse.ArgumentParser(description='Telegram Bot for Caguan Group')
parser.add_argument('-t','--token', help='Token to connect in telegram', required=True)
args = vars(parser.parse_args())

#================================Init Config=====================================================
if args['token'] is not None:
    TOKEN = args['token']
else:
    print("Please set TOKEN parameter")
    raise SystemError

bot = telebot.TeleBot(TOKEN, parse_mode=None)
logging.basicConfig(level=logging.DEBUG)

#===================================Telegram Config================================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.reply_to(message, "Que se dice Caguaneros")

@bot.message_handler(commands=['trm'])
def trm(message):
    try:
        logging.info('Getting TRM from Google')
        msg = google_trm()
        bot.reply_to(message, msg)
        logging.info('Sending TRM')
    except Exception as e:
        logging.error("Exception ocurred", exc_info=True)

@bot.message_handler(commands=['upgames'])
def upcoming_releases(message):
    try:
        logging.info('Getting games')
        table = xbox_games()
        bot.reply_to(message, table)
        logging.info('Sending games')
    except Exception as e:
        logging.error("Exception ocurred", exc_info=True)
        
@bot.message_handler(commands=['matches','tmatches'])
def sending_matches(message):
    try:
        logging.info('Getting Matches')
        if '/matches' in message.text:
            data = matches()
<<<<<<< HEAD
            bot.send_message(chat_id=message.chat.id,text=f'<pre>{data}</pre>',
                             parse_mode="HTML",reply_to_message_id=message.message_id)
        elif '/tmatches' in message.text:
            data = matches(d=1)
            bot.send_message(chat_id=message.chat.id,text=f'<pre>{data}</pre>',
                             parse_mode="HTML",reply_to_message_id=message.message_id)
=======
            data.name = "todayMatches.png"
            bot.send_document(chat_id=message.chat.id,
                            document=data ,reply_to_message_id=message.message_id)
        elif '/tmatches' in message.text:
            data = matches(d=1)
            data.name = "tomorrowMatches.png"
            bot.send_document(chat_id=message.chat.id,
                            document=data ,reply_to_message_id=message.message_id)
>>>>>>> develop
    except Exception as e:
        bot.reply_to(message, "Not matches for today or failed send message, try one more time")
        logging.error("Exception ocurred", exc_info=True)

@bot.message_handler(commands=['random'])
def random_number(message):
    try:
        logging.info('Se solicitó un número aleatorio')
        repetitions = 100
        args = message.text.split()[1:]
        if len(args) != 2:
            bot.reply_to(message, "Por favor, envía el comando en el formato: /random start end")
            return
        start, end = map(int, args)
        number, count = most_common_number(start, end, repetitions=repetitions)
        msg = f"Número: {number}\nRepeticiones: {count}."
        bot.reply_to(message, msg)
        logging.info('Número enviado con éxito')
    except Exception as e:
        logging.error("Ocurrió una excepción", exc_info=True)
        bot.reply_to(message, "Ocurrió un error. Inténtalo de nuevo.")

def main():
    try:
        logging.info('Iniciando Bot')
        logging.info('--------------------------------')
        bot.infinity_polling()
    except:
        logging.info('Finalizando Bot')
        logging.info('--------------------------------')
        
if __name__ == "__main__":
    main()  
