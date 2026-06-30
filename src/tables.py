from tabulate import tabulate
import pandas as pd
import requests
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO, StringIO
from datetime import datetime, timedelta
import textwrap
import re
from .logger import setup_logging
from scrapling.fetchers import Fetcher
from threading import Lock

logger = setup_logging()


# Shared Fetcher instance to avoid recreating Fetcher on every call
_shared_fetcher = None
_fetcher_lock = Lock()

def get_shared_fetcher(adaptive=True, **configure_kwargs) -> Fetcher:
    """Return a module-level shared Fetcher instance (lazy, thread-safe).

    The first call creates and configures the Fetcher; subsequent calls
    return the same instance to reduce memory/overhead.
    """
    global _shared_fetcher
    with _fetcher_lock:
        if _shared_fetcher is None:
            f = Fetcher()
            try:
                # Try to configure with provided kwargs (including adaptive)
                cfg = dict(adaptive=adaptive, **configure_kwargs)
                f.configure(**cfg)
            except Exception:
                try:
                    f.configure(adaptive=adaptive)
                except Exception:
                    pass
            _shared_fetcher = f
        return _shared_fetcher


def xbox_games() -> str:
    """
    Retrieves the latest Xbox Series X games from a website and returns them in a tabulated format.

    Returns:
        str: A tabulated representation of the latest Xbox Series X games, including the release date and game title.
    """
    gamesurl = 'https://vandal.elespanol.com/lanzamientos/97/xbox-series-x'
    fetcher = get_shared_fetcher(adaptive=False)
    page = fetcher.get(gamesurl)
    if hasattr(page, 'text'):
        html_text = page.text
    elif hasattr(page, 'content'):
        content = page.content
        if isinstance(content, (bytes, bytearray)):
            html_text = content.decode('utf-8', errors='replace')
        else:
            html_text = str(content)
    elif hasattr(page, 'extract'):
        extracted = page.extract()
        html_text = extracted[0] if isinstance(extracted, (list, tuple)) and extracted else str(extracted)
    else:
        html_text = str(page)

    try:
        df_list = pd.read_html(StringIO(html_text), header=0)
    except Exception:
        try:
            resp = requests.get(gamesurl)
            resp.raise_for_status()
            df_list = pd.read_html(StringIO(resp.content.decode('utf-8', errors='replace')), header=0)
        except Exception as e:
            logger.error("Error reading xbox games tables: %s", e)
            return ""
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
    # Asegurar que `text` sea str y manejar valores nulos
    try:
        if pd.isna(text):
            return ""
    except Exception:
        pass
    return "\n".join(textwrap.wrap(str(text), width))

def matches(position=0) -> BytesIO:
    """
    Genera imagen con tabla de partidos:
    Columna 1: Equipos
    Columna 2: Hora / tiempo restante
    Columna 3: Canales
    """
    matches_url = 'https://www.lapelotona.com/partidos-de-futbol-para-hoy-en-vivo/'
    fetcher = get_shared_fetcher()

    position_data = {
        0: [0, 1],  # Hoy
        1: [2, 3],  # Mañana
    }

    html = fetcher.get(matches_url)
    tables = html.css('.partidos-tabla', adaptive=True)

    TIME_RE = r"\b\d{1,2}:\d{2}\s*[ap]\.?m\.?\b"

    def clean_text(value) -> str:
        try:
            if pd.isna(value):
                return ""
        except Exception:
            pass

        text = str(value)
        text = text.replace("\xa0", " ")
        text = text.replace("\\n", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def normalize_time(value: str) -> str:
        match = re.search(TIME_RE, value, flags=re.IGNORECASE)
        if not match:
            return ""

        t = match.group(0).lower().replace(".", "")
        t = re.sub(r"(\d{1,2}:\d{2})\s*([ap])m", r"\1 \2m", t)
        return clean_text(t)

    def extract_teams(raw_text: str, first_cell: str) -> str:
        candidate = first_cell.replace("|", " vs ")

        if not re.search(r"\bvs\b", candidate, flags=re.IGNORECASE):
            time_match = re.search(TIME_RE, raw_text, flags=re.IGNORECASE)
            candidate = raw_text[:time_match.start()] if time_match else raw_text
            candidate = candidate.replace("|", " vs ")

        # Eliminar hora, competencia y canales si vienen pegados al equipo.
        candidate = re.sub(TIME_RE, "", candidate, flags=re.IGNORECASE)
        candidate = re.split(
            r"\bFIFA\b|Canales?:|Competici[oó]n|Canal",
            candidate,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        candidate = re.sub(r"\s*\|\s*", " vs ", candidate)
        candidate = re.sub(r"\bvs\b", "vs", candidate, flags=re.IGNORECASE)
        candidate = clean_text(candidate)

        return candidate

    def extract_channels(raw_text: str, cells: list[str]) -> str:
        text = clean_text(raw_text)
        text = text.replace("|", " ")

        markers = list(
            re.finditer(
                r"\bCanales?\s*:\s*",
                text,
                flags=re.IGNORECASE,
            )
        )

        if markers:
            channels = text[markers[-1].end():]
        else:
            channels = ""

            # Fallback: buscar de derecha a izquierda una celda que parezca contener canales
            for c in reversed(cells):
                c = clean_text(c).replace("|", " ")

                m = re.search(r"\bCanales?\s*:\s*(.*)$", c, flags=re.IGNORECASE)
                if m:
                    channels = m.group(1)
                    break

                if re.search(
                    r"\b(DGO|DSports|DIRECTV|DAZN|ESPN|FOX|TUDN|ViX|Prime|Amazon|RCN|Caracol|Win|Paramount|TNT|TyC)\b",
                    c,
                    flags=re.IGNORECASE,
                ):
                    channels = c
                    break

        # Si después de los canales viene pegado otro partido, cortarlo
        channels = re.split(
            rf"\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñüÜ\s\.\-]+?\s+vs\s+[A-ZÁÉÍÓÚÑ][A-Za-zÁÉÍÓÚÑáéíóúñüÜ\s\.\-]+?\s+{TIME_RE}",
            channels,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        # Cortar competencia o basura si quedó pegada
        channels = re.split(
            r"\bFIFA\s+Copa\b|\bCopa\s+Mundial\b|\bCompetici[oó]n\b|\bPrevia\b|\bVer\b|\bMás información\b",
            channels,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        # Limpieza final
        channels = re.sub(r"^\s*Canales?\s*:?\s*", "", channels, flags=re.IGNORECASE)
        channels = channels.replace(";", ",")
        channels = re.sub(r"\s*,\s*", ", ", channels)
        channels = re.sub(r"\s+", " ", channels)
        channels = channels.strip(" ,.-")

        return channels

    rows = []

    for idx, table in enumerate(tables):
        if idx not in position_data.get(position, []):
            continue

        try:
            extracted = table.extract()
            table_html = extracted[0] if isinstance(extracted, list) else extracted
            df = pd.read_html(StringIO(table_html))[0]

            for _, row in df.iterrows():
                cells = [clean_text(x) for x in row.tolist()]
                cells = [c for c in cells if c and c.lower() != "nan"]

                if not cells:
                    continue

                raw_text = clean_text(" ".join(cells))
                raw_text = raw_text.replace("|", " vs ")

                hora = normalize_time(raw_text)
                equipos = extract_teams(raw_text, cells[0])
                canales = extract_channels(raw_text, cells)

                if not equipos or not hora:
                    continue

                rows.append({
                    "Equipos": equipos,
                    "Hora": hora,
                    "Canales": canales,
                })

        except Exception as e:
            logger.error(f"Error processing table: {e}")

    if rows:
        matches_table = pd.DataFrame(rows)
    else:
        matches_table = pd.DataFrame(columns=["Equipos", "Hora", "Canales"])

    if not matches_table.empty:
        matches_table["_orden"] = range(len(matches_table))
        matches_table["_score_canales"] = matches_table["Canales"].fillna("").str.len()

        matches_table = (
            matches_table
            .sort_values(
                by=["Equipos", "Hora", "_score_canales"],
                ascending=[True, True, False],
            )
            .drop_duplicates(subset=["Equipos", "Hora"], keep="first")
            .sort_values("_orden")
            .drop(columns=["_orden", "_score_canales"])
            .reset_index(drop=True)
        )

    if position == 0:
        def time_(match_time_str):
            try:
                if not isinstance(match_time_str, str) or not match_time_str.strip():
                    return False, None

                clean_hour = re.sub(r"\s*\(.*?\)", "", match_time_str).strip()
                today_str = datetime.now().strftime("%Y-%m-%d")

                parse_attempts = [
                    "%Y-%m-%d %I:%M %p",
                    "%Y-%m-%d %H:%M",
                ]

                match_time = None

                for fmt in parse_attempts:
                    try:
                        match_time = datetime.strptime(f"{today_str} {clean_hour}", fmt)
                        break
                    except ValueError:
                        continue

                if match_time is None:
                    logger.debug("No se pudo parsear hora: %r", match_time_str)
                    return False, None

                current_time = datetime.now()

                if match_time <= current_time <= match_time + timedelta(minutes=90):
                    return True, "(En juego)"

                if match_time > current_time:
                    time_until_start = match_time - current_time
                    total_seconds = int(time_until_start.total_seconds())
                    hours, remainder = divmod(total_seconds, 3600)
                    minutes = remainder // 60

                    if hours > 0:
                        return True, f"(Faltan {hours}h {minutes}m)"

                    return True, f"(Faltan {minutes}m)"

                return False, None

            except Exception as e:
                logger.debug("time_ error parsing %r: %s", match_time_str, e)
                return False, None

        match_ = matches_table["Hora"].apply(time_)
        matches_table["Estado"] = match_.apply(lambda x: x[1])
        matches_table = matches_table[match_.apply(lambda x: x[0])]

        if not matches_table.empty:
            matches_table["Hora"] = matches_table["Hora"] + " " + matches_table["Estado"]

        matches_table = matches_table.drop(columns=["Estado"], errors="ignore")

    elif position == 1:
        if not matches_table.empty:
            matches_table["Hora"] = matches_table["Hora"] + " (Mañana)"

    if matches_table.empty:
        fig, ax = plt.subplots(figsize=(5, 2))
        ax.text(
            0.5,
            0.5,
            "No hay partidos disponibles",
            horizontalalignment="center",
            verticalalignment="center",
            fontsize=12,
        )
        ax.axis("off")

        img_io = BytesIO()
        plt.savefig(img_io, format="png", bbox_inches="tight", pad_inches=0)
        img_io.seek(0)
        plt.close(fig)

        return img_io

    logger.debug("Final matches table:\n%s", matches_table.head())

    matches_table["Equipos"] = matches_table["Equipos"].apply(lambda x: wrap_text(x, width=32))
    matches_table["Hora"] = matches_table["Hora"].apply(lambda x: wrap_text(x, width=22))
    matches_table["Canales"] = matches_table["Canales"].apply(lambda x: wrap_text(x, width=42))

    def line_count(s):
        try:
            return str(s).count("\n") + 1
        except Exception:
            return 1

    lines_per_row = matches_table.apply(lambda col: col.map(line_count)).max(axis=1).tolist()

    header_unit = 2
    row_units = [max(2, int(x)) for x in lines_per_row]
    total_units = header_unit + sum(row_units)

    height_per_unit = 0.38
    fig_height = max(4, total_units * height_per_unit)

    fig, ax = plt.subplots(figsize=(15, fig_height))
    ax.axis("tight")
    ax.axis("off")

    mpl_table = ax.table(
        cellText=matches_table.values,
        colLabels=matches_table.columns,
        cellLoc="center",
        loc="center",
        colWidths=[0.34, 0.20, 0.46],
    )

    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(9)
    mpl_table.scale(1.05, 1)

    header_color = "#40466e"
    row_colors = ["#f1f1f2", "w"]
    edge_color = "black"

    unit_height = 1.0 / float(total_units)

    for (i, j), cell in mpl_table._cells.items():
        cell.set_edgecolor(edge_color)

        if i == 0:
            cell.set_text_props(weight="bold", color="w")
            cell.set_facecolor(header_color)
            cell.set_height(header_unit * unit_height)
        else:
            cell.set_facecolor(row_colors[i % len(row_colors)])

            try:
                unit = row_units[i - 1]
            except Exception:
                unit = 2

            cell.set_height(unit * unit_height)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)

    img_io = BytesIO()
    plt.savefig(img_io, format="png", bbox_inches="tight", pad_inches=0, dpi=200)
    img_io.seek(0)

    plt.close(fig)

    return img_io