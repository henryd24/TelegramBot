from  tabulate import tabulate
import pandas as pd
import requests

gamesurl = 'https://vandal.elespanol.com/lanzamientos/97/xbox-series-x'

def xbox_games():
    html = requests.get(gamesurl).content
    df_list = pd.read_html(html)
    df = df_list[-1]
    df = df[['Fecha', 'Juego']]
    return tabulate(df, headers='keys', showindex=False)