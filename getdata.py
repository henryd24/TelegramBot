from bs4 import BeautifulSoup
import requests
import pandas as pd

bse_list = ['quote/USD-COP', 'quote/EUR-COP']
start_url = 'https://google.com/finance/'
gamesurl = 'https://vandal.elespanol.com/lanzamientos/97/xbox-series-x'

def parse_book():
    datos = []
    for path in bse_list:
        response = requests.get(start_url+path)
        html = BeautifulSoup(response.text,'html.parser')
        stock_name = html.find(class_='zzDege').text.strip()
        current_price = html.find(class_='YMlKec fxKbKc').text.strip()
        previous_closing = html.find(class_='P6K39c').text.strip()

        datos.append( {
            "stock_name": stock_name,
            "current_price": current_price,
            "previous_closing": previous_closing,
        })
    return datos

def upcoming_releases():
    html = requests.get(gamesurl).content
    df_list = pd.read_html(html)
    df = df_list[-1]
    df = df[['Fecha', 'Juego', 'Plat.']]
    df.to_csv('/tmp/telegrambot/juegos.csv',index=False)