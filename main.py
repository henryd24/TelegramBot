import argparse
import telebot,instaloader,logging
from src import *

parser = argparse.ArgumentParser(description='Telegram Bot for Caguan Group')
parser.add_argument('-t','--token', help='Token to connect in telegram', required=True)
parser.add_argument('-f','--file', help='If set a session file', required=False)
parser.add_argument('-u','--user', help='Instagram user', required=False)
parser.add_argument('-p','--password', help='Instagram password', required=False)
args = vars(parser.parse_args())

#================================Init Config=====================================================
if args['token'] is not None:
    TOKEN = args['token']
else:
    print("Please set TOKEN parameter")
    raise SystemError

L = instaloader.Instaloader(max_connection_attempts = 5)
if args['user'] is not None and args['password'] is not None:
    INSTA_USER = args['user']
    INSTA_PASS = args['password']
    L.login(INSTA_USER, INSTA_PASS)
elif args['file'] is not None and args['user'] is not None:
    L.load_session_from_file(username=args['user'],filename=args['file'])

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
        
@bot.message_handler(commands=['ig'])
def instagram(message):
    try:
        logging.info('Getting Image/Video from Instagram')
        splitting = message.text.split(' ')
        if len(splitting) == 2:
            data,video_check = get_imgvid_instagram(splitting[1],L)
            if video_check is not None:
                bot.send_video(chat_id=message.chat.id,
                            video=video_check,reply_to_message_id=message.message_id)
            else:
                bot.send_photo(chat_id=message.chat.id,
                            photo=data,reply_to_message_id=message.message_id)
            logging.info('Sending Image/Video')
        else:
            bot.reply_to(message, "Not Instagram URL")
    except Exception as e:
        bot.reply_to(message, "Video could not be sent (probably too large > 20 MB or bad url ); If not, try again ")
        logging.error("Exception ocurred", exc_info=True)


@bot.message_handler(commands=['fb'])
def facebook(message):
    try:
        logging.info('Getting Image/Video from Facebook')
        splitting = message.text.split(' ')
        if len(splitting) == 2:
            data = get_imgvid_facebook(splitting[1])
            print(data)
            bot.send_video(chat_id=message.chat.id,
                        video=data,reply_to_message_id=message.message_id)
            logging.info('Sending Image/Video')
    except Exception as e:
        bot.reply_to(message, "Video could not be sent (probably too large > 20 MB or bad url ); If not, try again ")
        logging.error("Exception ocurred", exc_info=True)


@bot.message_handler(commands=['matches','tmatches'])
def sending_matches(message):
    try:
        logging.info('Getting Matches')
        if '/matches' in message.text:
            data = matches()
            bot.send_photo(chat_id=message.chat.id,
                            photo=data,reply_to_message_id=message.message_id)
        elif '/tmatches' in message.text:
            data = matches(d=1)
            bot.send_photo(chat_id=message.chat.id,
                            photo=data,reply_to_message_id=message.message_id)
    except Exception as e:
        bot.reply_to(message, "Not matches for today or failed send message, try one more time")
        logging.error("Exception ocurred", exc_info=True)

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