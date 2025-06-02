import argparse
import telebot
from src.logger import setup_logging
from src.money import google_trm
from src.tables import xbox_games, matches
from src.nrandom import most_common_number
import gc
import requests

session = requests.Session()

parser = argparse.ArgumentParser(description='Telegram Bot for Caguan Group')
parser.add_argument('-t', '--token', help='Token to connect in telegram', required=True)
args = vars(parser.parse_args())

logger = setup_logging()
# =================================== Init Config =====================================================
if args['token'] is not None:
    TOKEN = args['token']
else:
    print("Please set TOKEN parameter")
    raise SystemError

bot = telebot.TeleBot(TOKEN, parse_mode=None)

# =================================== Telegram Config ================================================
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message) -> None:
    bot.reply_to(message, "Que se dice Caguaneros")


@bot.message_handler(commands=['trm'])
def trm(message) -> None:
    try:
        logger.info('Getting TRM from Google')
        msg = google_trm() 
        bot.reply_to(message, msg)
        logger.info('Sending TRM')
    except Exception as e:
        logger.error("Exception occurred", exc_info=True)
    finally:
        logger.info('--------------------------------')
        logger.info(gc.collect()) 
        logger.info('--------------------------------')


@bot.message_handler(commands=['upgames'])
def upcoming_releases(message) -> None:
    try:
        logger.info('Getting games')
        table = xbox_games() 
        bot.reply_to(message, table)
        logger.info('Sending games')
    except Exception as e:
        logger.error("Exception occurred", exc_info=True)
    finally:
        logger.info('--------------------------------')
        logger.info(gc.collect()) 
        logger.info('--------------------------------')


@bot.message_handler(commands=['matches', 'tmatches'])
def sending_matches(message) -> None:
    try:
        logger.info('Getting Matches')
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
        logger.error("Exception occurred", exc_info=True)
    finally:
        if data:
            data.close() 
        data = None 
        logger.info('--------------------------------')
        logger.info(gc.collect()) 
        logger.info('--------------------------------')


@bot.message_handler(commands=['random'])
def random_number(message) -> None:
    try:
        logger.info('Se solicitó un número aleatorio')
        repetitions = 100
        args = message.text.split()[1:]
        if len(args) != 2:
            bot.reply_to(message, "Por favor, envía el comando en el formato: /random start end")
            return
        start, end = map(int, args)
        number, count = most_common_number(start, end, repetitions=repetitions) 
        msg = f"Número: {number}\nRepeticiones: {count}."
        bot.reply_to(message, msg)
        logger.info('Número enviado con éxito')
    except Exception as e:
        bot.reply_to(message, "Ocurrió un error. Inténtalo de nuevo.")
        logger.error("Ocurrió una excepción", exc_info=True)
    finally:
        logger.info('--------------------------------')
        logger.info(gc.collect()) 
        logger.info('--------------------------------')


def main() -> None:
    try:
        logger.info('Iniciando Bot')
        logger.info('--------------------------------')
        bot.infinity_polling()
    except:
        logger.info('Finalizando Bot')
        logger.info('--------------------------------')


if __name__ == "__main__":
    from datetime import datetime
    logger.info(f'Fecha actual: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    main()
