from bs4 import BeautifulSoup
import logging,requests,re,instaloader,youtube_dl
import pandas as pd
from  tabulate import tabulate

bse_list = ['quote/USD-COP', 'quote/EUR-COP']
start_url = 'https://google.com/finance/'
gamesurl = 'https://vandal.elespanol.com/lanzamientos/97/xbox-series-x'

def parse_book():
    msg = ''
    for path in reversed(bse_list):
        response = requests.get(start_url+path)
        html = BeautifulSoup(response.text,'html.parser')
        stock_name = html.find(class_='zzDege').text.strip()
        current_price = html.find(class_='YMlKec fxKbKc').text.strip()
        previous_closing = html.find(class_='P6K39c').text.strip()
        txt = """Conversion: {stock_name}
Valor Actual: {current_price}
Cierre Anterior: {previous_closing}
-------------------\n""".format(stock_name=stock_name,
                                current_price=current_price,
                                previous_closing=previous_closing)
        msg = txt+msg
    return msg

def upcoming_releases():
    html = requests.get(gamesurl).content
    df_list = pd.read_html(html)
    df = df_list[-1]
    df = df[['Fecha', 'Juego']]
    return tabulate(df, headers='keys', showindex=False)

def instagram(message,L):
    if 'https://www.instagram.com/stories' in message:
        regex_code = re.search("https:\/\/www\.instagram\.com\/(stories)\/.*\/(\d+)", message)
        code = int(regex_code.group(2))
        post = instaloader.StoryItem.from_mediaid(L.context,code)
        photo_url = post.url
        video_url = post.video_url
        return photo_url,video_url
    else:
        regex_code = re.search("https:\/\/www\.instagram\.com\/(p|reel)\/(\w*)", message)
        code = regex_code.group(2)
        post = instaloader.Post.from_shortcode(L.context,code)
        photo_url = post.url
        video_url = post.video_url
        data = requests.get(photo_url).content
        return data,video_url

def facebook(url):
    try:
        secondCheck = False
        if 'https://m' in url:
            url = url.replace('https://m','https://www')
            secondCheck=True
        ydl = youtube_dl.YoutubeDL({'outtmpl': '%(id)s.%(ext)s'})
        with ydl:
            result = ydl.extract_info(
            url,
            download=False # We just want to extract the info
        )
        if 'entries' in result:
        # Can be a playlist or a list of videos
            video = result['entries'][0]
        else:
        # Just a video
            video = result
        if 'url' not in video:
        # If video is large
            video = video['formats'][5]
        
        video_url = video['url']
        
        if secondCheck:
            video_url = facebook(video_url)
            
        return video_url
    
    except Exception as e:
        logging.error("Exception ocurred getting url", exc_info=True)