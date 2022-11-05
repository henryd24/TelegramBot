import telebot,os,instaloader,logging
from src import *
#================================Init Config=====================================================
if os.environ.get('TOKEN') is not None:
    TOKEN = os.environ.get('TOKEN')
else:
    print("Env variable TOKEN doesn't exist")
    raise SystemError

if os.environ.get('INSTA_USER') is not None and os.environ.get('INSTA_PASS') is not None:
    INSTA_USER = os.environ.get('INSTA_USER')
    INSTA_PASS = os.environ.get('INSTA_PASS')
    L = instaloader.Instaloader()
    L.login(INSTA_USER, INSTA_PASS)
else:
    L = instaloader.Instaloader()

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
        splitting = message.text.split('/ig ')
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
        splitting = message.text.split('/fb ')
        if len(splitting) == 2:
            data = get_imgvid_facebook(splitting[1])
            bot.send_video(chat_id=message.chat.id,
                        video=data,reply_to_message_id=message.message_id)
            logging.info('Sending Image/Video')
    except Exception as e:
        bot.reply_to(message, "Video could not be sent (probably too large > 20 MB or bad url ); If not, try again ")
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