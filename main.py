import argparse
import telebot, logging
from src.money import google_trm
from src.tables import xbox_games, matches
from src.nrandom import most_common_number
import gc
import requests

# Inicializa una sesión global para reutilizar conexiones HTTP
session = requests.Session()

parser = argparse.ArgumentParser(description='Telegram Bot for Caguan Group')
parser.add_argument('-t', '--token', help='Token to connect in telegram', required=True)
parser.add_argument('-d', '--debug', help='Debug mode', action='store_true', required=False, default=False)
args = vars(parser.parse_args())

# =================================== Init Config =====================================================
if args['token'] is not None:
    TOKEN = args['token']
else:
    print("Please set TOKEN parameter")
    raise SystemError

bot = telebot.TeleBot(TOKEN, parse_mode=None)
if args['debug']:
    logging.basicConfig(level=logging.DEBUG)
else:
    logging.basicConfig(level=logging.WARNING) 

# =================================== Telegram Config ================================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message) -> None:
    bot.reply_to(message, "Que se dice Caguaneros")


@bot.message_handler(commands=['trm'])
def trm(message) -> None:
    try:
        logging.info('Getting TRM from Google')
        msg = google_trm() 
        bot.reply_to(message, msg)
        logging.info('Sending TRM')
    except Exception as e:
        logging.error("Exception occurred", exc_info=True)
    finally:
        logging.info('--------------------------------')
        logging.info(gc.collect()) 
        logging.info('--------------------------------')


@bot.message_handler(commands=['upgames'])
def upcoming_releases(message) -> None:
    try:
        logging.info('Getting games')
        table = xbox_games() 
        bot.reply_to(message, table)
        logging.info('Sending games')
    except Exception as e:
        logging.error("Exception occurred", exc_info=True)
    finally:
        logging.info('--------------------------------')
        logging.info(gc.collect()) 
        logging.info('--------------------------------')


@bot.message_handler(commands=['matches', 'tmatches'])
def sending_matches(message) -> None:
    try:
        logging.info('Getting Matches')
        data = None
        if '/matches' in message.text:
            data = matches(position=0) 
            data.name = "todayMatches.png"
            bot.send_document(chat_id=message.chat.id, document=data, reply_to_message_id=message.message_id)
           
           
        elif '/tmatches' in message.text:
            data = matches(position=1) 
            data.name = "tomorrowMatches.png"
            bot.send_document(chat_id=message.chat.id, document=data, reply_to_message_id=message.message_id)
           
           
    except Exception as e:
        bot.reply_to(message, "Not matches for today or failed to send message, try one more time")
        logging.error("Exception occurred", exc_info=True)
    finally:
        if data:
            data.close() 
        data = None 
        logging.info('--------------------------------')
        logging.info(gc.collect()) 
        logging.info('--------------------------------')


@bot.message_handler(commands=['random'])
def random_number(message) -> None:
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
        bot.reply_to(message, "Ocurrió un error. Inténtalo de nuevo.")
        logging.error("Ocurrió una excepción", exc_info=True)
    finally:
        logging.info('--------------------------------')
        logging.info(gc.collect()) 
        logging.info('--------------------------------')


def main() -> None:
    try:
        logging.info('Iniciando Bot')
        logging.info('--------------------------------')
        bot.infinity_polling()
    except:
        logging.info('Finalizando Bot')
        logging.info('--------------------------------')


if __name__ == "__main__":
    from datetime import datetime
    logging.info(f'Fecha actual: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    main()
