from tabulate import tabulate
import pandas as pd
import requests
import re
import matplotlib.pyplot as plt
from io import BytesIO
from datetime import datetime, timedelta
import textwrap

def xbox_games() -> str:
    """
    Retrieves the latest Xbox Series X games from a website and returns them in a tabulated format.

    Returns:
        str: A tabulated representation of the latest Xbox Series X games, including the release date and game title.
    """
    gamesurl = 'https://vandal.elespanol.com/lanzamientos/97/xbox-series-x'
    html = requests.get(gamesurl).content
    df_list = pd.read_html(html)
    df = df_list[-1]
    df = df[['Fecha', 'Juego']]
    return tabulate(df, headers='keys', showindex=False)

def wrap_text(text, width=20) -> str:
    """
    Wraps the input text to a specified width.
    This function takes a string and wraps it so that each line does not exceed
    the specified width. The wrapped text is returned as a single string with
    newline characters separating the lines.
    Args:
        text (str): The input text to be wrapped.
        width (int, optional): The maximum width of each line. Defaults to 20.
    Returns:
        str: The wrapped text with lines separated by newline characters.
    """
    return "\n".join(textwrap.wrap(text, width))

def matches(position=0) -> BytesIO:
    """
    Retrieves football matches information from a website and returns a plot file.

    Args:
        position (int, optional): The position of the match table to retrieve. Defaults to 0.

    Returns:
        BytesIO: A plot file containing the matches information.
    """
    matches_url = 'https://www.lapelotona.com/partidos-de-futbol-para-hoy-en-vivo/'
    html = requests.get(matches_url).text
    cleaned_html = re.sub(r'<br\s*/?>', ' | ', html)
    matches_table = pd.read_html(bytes(cleaned_html, encoding='utf-8'))[position]
    
    matches_table['Equipos'].replace("\\|", "vs", regex=True, inplace=True)
    matches_table['Hora'] = matches_table['Hora/Canal'].str.extract(r"(\d+:\d+\s[ap]m)")
    matches_table['Canal'] = matches_table['Hora/Canal'].str.split('|').str[-1]
    df_split = matches_table['Canal'].str.rsplit('-', n=1, expand=True)
    
    matches_table[['Competición', 'Canal']] = df_split
    matches_table = matches_table[['Equipos', 'Hora', 'Competición', 'Canal']]

    if position == 0:
        def time_(match_time_str):
            today_str = datetime.now().strftime("%Y-%m-%d")
            match_time = datetime.strptime(today_str + " " + match_time_str, "%Y-%m-%d %I:%M %p")
            current_time = datetime.now()

            if match_time <= current_time <= match_time + timedelta(minutes=90):
                return True, "(En juego)"
            
            if match_time > current_time:
                time_until_start = match_time - current_time
                hours, remainder = divmod(time_until_start.seconds, 3600)
                minutes = remainder // 60
                return True, f"(Faltan {hours}h {minutes}m)" if hours > 0 else f"(Faltan {minutes}m)"
            
            return False, None

        match_ = matches_table['Hora'].apply(time_)
        matches_table[''] = match_.apply(lambda x: x[1])
        matches_table = matches_table[match_.apply(lambda x: x[0])]
        matches_table['Hora'] = matches_table['Hora'] + " " + matches_table['']

    elif position == 1:
        matches_table[''] = "(Mañana)"
        matches_table['Hora'] = matches_table['Hora'] + " " + matches_table['']

    matches_table = matches_table.drop(columns=[''])

    if matches_table.empty:
        fig, ax = plt.subplots(figsize=(5, 2))
        ax.text(0.5, 0.5, 'No hay partidos disponibles', horizontalalignment='center', verticalalignment='center', fontsize=12)
        ax.axis('off')
        img_io = BytesIO()
        plt.savefig(img_io, format='png', bbox_inches='tight', pad_inches=0)
        img_io.seek(0)
        plt.close(fig)
        return img_io

   
    matches_table['Equipos'] = matches_table['Equipos'].apply(lambda x: wrap_text(x, width=30))
    matches_table['Competición'] = matches_table['Competición'].apply(lambda x: wrap_text(x, width=25))
    matches_table['Canal'] = matches_table['Canal'].apply(lambda x: wrap_text(x, width=30))

    fig, ax = plt.subplots(figsize=(15, 10)) 
    ax.axis('tight')
    ax.axis('off')

    mpl_table = ax.table(cellText=matches_table.values, colLabels=matches_table.columns, cellLoc='center', loc='center')

    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(10)

   
    mpl_table.scale(1.2, 2) 

   
    header_color = '#40466e'
    row_colors = ['#f1f1f2', 'w']
    edge_color = 'black'

    for (i, j), cell in mpl_table._cells.items():
        cell.set_edgecolor(edge_color)
        if i == 0:
            cell.set_text_props(weight='bold', color='w')
            cell.set_facecolor(header_color)
        else:
            cell.set_facecolor(row_colors[i % len(row_colors)])
        if j in (0, 1, 2, 3): 
            cell.set_height(cell.get_height() * 1.2) 

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    img_io = BytesIO()
    plt.savefig(img_io, format='png', bbox_inches='tight', pad_inches=0)
    img_io.seek(0)
    
    plt.close(fig)
    
    return img_io