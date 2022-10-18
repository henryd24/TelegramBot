import telebot
import os
import getdata
import logging
import instaloader

TOKEN = os.environ['TOKEN']
INSTA_USER = os.environ['INSTA_USER']
INSTA_PASS = os.environ['INSTA_PASS']
logging.basicConfig(level=logging.DEBUG)

L = instaloader.Instaloader()
L.login(INSTA_USER, INSTA_PASS)

bot = telebot.TeleBot(TOKEN, parse_mode=None)

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.reply_to(message, "Que se dice Caguaneros")

@bot.message_handler(commands=['trm'])
def trm(message):
    try:
        logging.info('Getting TRM from Google')
        msg = getdata.parse_book()
        bot.reply_to(message, msg)
        logging.info('Sending TRM')
    except Exception as e:
        logging.error("Exception ocurred", exc_info=True)



@bot.message_handler(commands=['upgames'])
def upcoming_releases(message):
    try:
        logging.info('Getting games')
        table = getdata.upcoming_releases()
        bot.reply_to(message, table)
        logging.info('Sending games')
    except Exception as e:
        logging.error("Exception ocurred", exc_info=True)
        
@bot.message_handler(commands=['instagram'])
def instagram(message):
    try:
        logging.info('Getting Image/Video from Instagram')
        splitting = message.text.split('/instagram ')
        if len(splitting) == 2:
            data,video_check = getdata.instagram(splitting[1],L)
            if video_check is not None:
                bot.send_video_note(chat_id=message.chat.id,
                            data=video_check,reply_to_message_id=message.message_id)
            else:
                bot.send_photo(chat_id=message.chat.id,
                            photo=data,reply_to_message_id=message.message_id)
            logging.info('Sending Image/Video')
        else:
            bot.reply_to(message, "Not Instagram URL")
    except Exception as e:
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