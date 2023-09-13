from  tabulate import tabulate
import pandas as pd
import requests,re
import numpy as np
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime, timedelta

def xbox_games():
    gamesurl = 'https://vandal.elespanol.com/lanzamientos/97/xbox-series-x'
    html = requests.get(gamesurl).content
    df_list = pd.read_html(html)
    df = df_list[-1]
    df = df[['Fecha', 'Juego']]
    return tabulate(df, headers='keys', showindex=False)

def matches(position=0):
    matches = 'https://www.lapelotona.com/partidos-de-futbol-para-hoy-en-vivo/'
    html = requests.get(matches)
    cleaned_html = re.sub(r'<br\s*/?>', ' | ', html.text)
    matches = pd.read_html(bytes(cleaned_html, encoding='utf-8'))[position]
    matches['Equipos'].replace("\|","vs",regex=True,inplace=True)
    hour = []
    for values in matches['Hora/Canal']:
        hour.append(re.search(r"^\d+:\d+\s[am|pm]+",values).group())
    matches['Hora'] = hour
    matches['Canal'] =  matches['Hora/Canal'].str.replace('^.*\| ','',regex=True)
    df_split = matches['Canal'].str.rsplit('-', n=1, expand=True)
    if df_split.shape[1] > 2:
        df_split[0] = df_split.iloc[:, :-1].apply(lambda x: '-'.join(x.dropna()), axis=1)
        df_split = df_split.iloc[:, [-2, -1]]
    matches[['Competición', 'Canal']] = df_split
    matches = matches[['Equipos','Hora','Competición','Canal']]
    if position==0:
        current_hour_less_2 = (datetime.now() - timedelta(hours=2)).time()
        matches = matches[pd.to_datetime(matches['Hora'], format='%I:%M %p').dt.time > current_hour_less_2]
    fig,_ = render_mpl_table(matches, header_columns=0, col_width=9.0)
    plot_file = BytesIO()
    fig.savefig(plot_file,format='png',bbox_inches='tight')
    plot_file.seek(0)
    return plot_file

def render_mpl_table(data, col_width=5.0, row_height=1.0, font_size=18,
                     header_color='#40466e', row_colors=['#f1f1f2', 'w'], edge_color='w',
                     bbox=[0, 0, 1, 1], header_columns=0,
                     ax=None, **kwargs):
    if ax is None:
        size = (np.array(data.shape[::-1]) + np.array([0, 1])) * np.array([col_width, row_height])
        fig, ax = plt.subplots(figsize=size)
        ax.axis('off')
    mpl_table = ax.table(cellText=data.values, bbox=bbox, colLabels=data.columns, **kwargs)
    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(font_size)

    for k, cell in mpl_table._cells.items():
        cell.set_edgecolor(edge_color)
        if k[0] == 0 or k[1] < header_columns:
            cell.set_text_props(weight='bold', color='w')
            cell.set_facecolor(header_color)
        else:
            cell.set_facecolor(row_colors[k[0]%len(row_colors) ])
    return ax.get_figure(), ax
