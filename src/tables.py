from  tabulate import tabulate
import pandas as pd
import requests,re

def xbox_games():
    gamesurl = 'https://vandal.elespanol.com/lanzamientos/97/xbox-series-x'
    html = requests.get(gamesurl).content
    df_list = pd.read_html(html)
    df = df_list[-1]
    df = df[['Fecha', 'Juego']]
    return tabulate(df, headers='keys', showindex=False)

def matches(d=None):
    matches = 'https://www.lapelotona.com/partidos-de-futbol-para-hoy-en-vivo/'
    html = requests.get(matches)
    position = 0
    if d != None:
        position = 1
    matches=pd.read_html(bytes(html.text.replace("<br>"," | "),encoding='utf-8'))[position]
    matches['Equipos'].replace("\|","vs",regex=True,inplace=True)
    hour = []
    for values in matches['Hora/Canal']:
        hour.append(re.search(r"^\d+:\d+\s[am|pm]+",values).group())
    matches['Hora'] = hour
    matches['Canal'] =  matches['Hora/Canal'].str.replace('^.*\| ','',regex=True)
    matches[['Competición','Canal']] = matches['Canal'].str.split('-',expand=True)
    matches = matches[['Equipos','Hora','Competición','Canal']]
    return tabulate(matches,headers='keys', tablefmt="github",showindex=False)