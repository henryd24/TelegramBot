from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html
from io import BytesIO, StringIO
import re
from threading import Lock
import textwrap
import time
import unicodedata

import pandas as pd
import requests
from scrapling.fetchers import Fetcher
from tabulate import tabulate
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from .logger import setup_logging

logger = setup_logging(__name__)

COLOMBIA_TZ = timezone(timedelta(hours=-5))

# Shared Fetcher instances keyed by configuration to avoid mutating config across callers
_shared_fetchers: dict[tuple, Fetcher] = {}
_fetcher_lock = Lock()

# HTTP session for JSON APIs
_api_session = requests.Session()
_api_session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "es-CO,es-419;q=0.9,es;q=0.8",
})

# In-memory TTL caches
_xbox_cache: dict[str, object] = {"df": None, "timestamp": 0.0}
_xbox_lock = Lock()
XBOX_CACHE_TTL = 3600  # 1 hora

_matches_cache: dict[int, dict[str, object]] = {
    0: {"data": None, "timestamp": 0.0},
    1: {"data": None, "timestamp": 0.0},
}
_tv_networks_cache: dict[int, list[str]] = {}
_matches_lock = Lock()
MATCHES_CACHE_TTL = 180  # 3 minutos para refrescar marcadores en vivo

SCORES365_ALLSCORES_URL = "https://webws.365scores.com/web/games/allscores/"
SCORES365_GAME_URL = "https://webws.365scores.com/web/game/"
LAPELOTONA_URL = "https://www.lapelotona.com/partidos-de-futbol-para-hoy-en-vivo/"

FEATURED_LEAGUE_KEYWORDS = (
    "betplay",
    "dimayor",
    "colombia",
    "primera a",
    "copa colombia",
    "champions",
    "campeones",
    "libertadores",
    "sudamericana",
    "premier league",
    "laliga",
    "la liga",
    "serie a",
    "bundesliga",
    "ligue 1",
    "europa league",
    "conference league",
    "nations league",
    "eliminatorias",
    "mundial",
    "copa america",
    "copa américa",
    "mls",
    "liga mx",
    "liga profesional",
    "brasileir",
    "copa del rey",
    "fa cup",
)

DAYS_ES = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
    6: "Domingo",
}
MONTHS_ES = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}


def get_shared_fetcher(adaptive: bool = True, **configure_kwargs) -> Fetcher:
    """Return a cached Fetcher instance keyed by configuration (thread-safe)."""
    key = (bool(adaptive), tuple(sorted(configure_kwargs.items())))
    with _fetcher_lock:
        if key not in _shared_fetchers:
            f = Fetcher()
            try:
                cfg = dict(adaptive=adaptive, **configure_kwargs)
                f.configure(**cfg)
            except Exception:
                try:
                    f.configure(adaptive=adaptive)
                except Exception:
                    pass
            _shared_fetchers[key] = f
        return _shared_fetchers[key]


def _format_spanish_date(dt: datetime) -> str:
    day_name = DAYS_ES.get(dt.weekday(), "")
    month_name = MONTHS_ES.get(dt.month, "")
    return f"{day_name}, {dt.day} de {month_name} de {dt.year}"


def _fetch_xbox_dataframe(force_refresh: bool = False) -> pd.DataFrame:
    """Obtiene y cachea el DataFrame de próximos lanzamientos de Xbox Series X|S."""
    now = time.time()
    with _xbox_lock:
        if (
            not force_refresh
            and _xbox_cache["df"] is not None
            and (now - float(_xbox_cache["timestamp"])) < XBOX_CACHE_TTL
        ):
            return _xbox_cache["df"]  # type: ignore[return-value]

    gamesurl = "https://vandal.elespanol.com/lanzamientos/97/xbox-series-x"
    html_text = ""
    try:
        fetcher = get_shared_fetcher(adaptive=False)
        page = fetcher.get(gamesurl)
        if hasattr(page, "text"):
            html_text = page.text
        elif hasattr(page, "content"):
            content = page.content
            html_text = (
                content.decode("utf-8", errors="replace")
                if isinstance(content, (bytes, bytearray))
                else str(content)
            )
        elif hasattr(page, "extract"):
            extracted = page.extract()
            html_text = (
                extracted[0]
                if isinstance(extracted, (list, tuple)) and extracted
                else str(extracted)
            )
        else:
            html_text = str(page)
        df_list = pd.read_html(StringIO(html_text), header=0)
    except Exception:
        try:
            resp = _api_session.get(gamesurl, timeout=10)
            resp.raise_for_status()
            df_list = pd.read_html(
                StringIO(resp.content.decode("utf-8", errors="replace")),
                header=0,
            )
        except Exception as e:
            logger.error("Error reading xbox games tables: %s", e)
            return pd.DataFrame(columns=["Fecha", "Juego"])

    df = df_list[-1][["Fecha", "Juego"]].dropna(how="all").reset_index(drop=True)
    with _xbox_lock:
        _xbox_cache["df"] = df
        _xbox_cache["timestamp"] = now
    return df


def xbox_games_view(
    page: int = 0,
    page_size: int = 12,
    force_refresh: bool = False,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """
    Construye el mensaje HTML y teclado interactivo para los próximos lanzamientos de Xbox.
    """
    df = _fetch_xbox_dataframe(force_refresh=force_refresh)
    if df.empty:
        return (
            "🎮 <b>PRÓXIMOS LANZAMIENTOS — XBOX SERIES X|S</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>No se encontraron lanzamientos disponibles en este momento.</i>",
            None,
        )

    total_items = len(df)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total_items)
    subset = df.iloc[start_idx:end_idx]

    lines = [
        "🎮 <b>PRÓXIMOS LANZAMIENTOS — XBOX SERIES X|S</b>",
        f"<blockquote>📦 <b>Total listados:</b> {total_items} juegos │ 📄 <b>Página:</b> {page + 1}/{total_pages}</blockquote>",
        "",
    ]

    for _, row in subset.iterrows():
        fecha = html.escape(str(row.get("Fecha", "Por confirmar")).strip())
        juego = html.escape(str(row.get("Juego", "Juego")).strip())
        lines.append(f"🗓️ <code>{fecha}</code>\n└ 🕹️ <b>{juego}</b>\n")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🌐 <i>Fuente: Vandal Xbox Series X|S</i>")

    markup = InlineKeyboardMarkup(row_width=3)
    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton("◀️ Anterior", callback_data=f"x|{page - 1}|0")
            )
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="x|noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton("Siguiente ▶️", callback_data=f"x|{page + 1}|0")
            )
        markup.row(*nav_buttons)

    markup.row(
        InlineKeyboardButton("🔄 Actualizar lista", callback_data=f"x|{page}|1")
    )
    return "\n".join(lines), markup


def xbox_games() -> str:
    """
    Retrieves the latest Xbox Series X games and returns them formatted in HTML.
    """
    text, _ = xbox_games_view(page=0, page_size=15)
    return text


def wrap_text(text, width: int = 20) -> str:
    """Wraps the input text to a specified width."""
    try:
        if pd.isna(text):
            return ""
    except Exception:
        pass
    return "\n".join(textwrap.wrap(str(text), width))


# ==============================================================================
# FÚTBOL: PIPELINE HÍBRIDO (365SCORES JSON API + LA PELOTONA CANALES COLOMBIA)
# ==============================================================================

TEAM_SYNONYMS = {
    "holanda": "paises bajos",
    "netherlands": "paises bajos",
    "republica de irlanda": "irlanda",
    "irlanda del norte": "northern ireland",
    "bosnia y herzegovina": "bosnia",
    "estados unidos": "usa",
    "corea del sur": "corea",
    "republica de corea": "corea",
}


def _clean_competition_name(name: str) -> str:
    """Unifica nombres de torneos eliminando sufijos de grupos o fases redundantes."""
    if not name:
        return "Fútbol Internacional"
    cleaned = re.sub(
        r"\s*-\s*(Liga\s+[A-D]\s*-\s*Grupo\s+\w+|Grupo\s+\w+|Jornada\s+\d+|Fecha\s+\d+)\s*$",
        "",
        str(name),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\s*-\s*Liga\s+[A-D]\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip(" -") or str(name).strip()


def _normalize_key(text: str) -> str:
    """Normaliza nombres de equipos/ligas para cruce difuso sin tildes ni ruido."""
    if not text:
        return ""
    norm = unicodedata.normalize("NFKD", str(text))
    norm = "".join(c for c in norm if not unicodedata.combining(c)).lower()
    norm = re.sub(r"[^a-z0-9]+", " ", norm)
    norm = re.sub(r"\s+", " ", norm).strip()
    for syn_k, syn_v in TEAM_SYNONYMS.items():
        if norm == syn_k or f" {syn_k} " in f" {norm} ":
            norm = norm.replace(syn_k, syn_v)
    norm = re.sub(
        r"\b(fc|cf|sc|cd|ca|club|deportivo|atletico|real|united|city|de|del|la|el|republica)\b",
        " ",
        norm,
    )
    return re.sub(r"\s+", " ", norm).strip()


def _teams_match(home_a: str, away_a: str, home_b: str, away_b: str) -> bool:
    """Verifica si dos pares de equipos corresponden al mismo partido."""
    ha, aa = _normalize_key(home_a), _normalize_key(away_a)
    hb, ab = _normalize_key(home_b), _normalize_key(away_b)

    def _sim(x: str, y: str) -> bool:
        if not x or not y:
            return False
        if x == y or x in y or y in x:
            return True
        tokens_x = {t for t in x.split() if len(t) >= 3}
        tokens_y = {t for t in y.split() if len(t) >= 3}
        return bool(tokens_x and tokens_y and (tokens_x & tokens_y))

    return (_sim(ha, hb) and _sim(aa, ab)) or (_sim(ha, ab) and _sim(aa, hb))


def _is_featured_competition(comp_name: str, country_name: str = "") -> bool:
    haystack = f"{comp_name} {country_name}".lower()
    if any(
        excl in haystack
        for excl in ("reserva", "sub-20", "sub-19", "sub-17", "u21", "u20", "u19", "youth")
    ):
        return False
    return any(kw in haystack for kw in FEATURED_LEAGUE_KEYWORDS)


def _fetch_single_game_tv_365(game_id: int) -> list[str]:
    """Consulta los canales de TV específicos de un partido en 365Scores para Colombia."""
    if game_id in _tv_networks_cache:
        return _tv_networks_cache[game_id]

    try:
        params = {
            "appTypeId": 5,
            "langId": 29,
            "timezoneName": "America/Bogota",
            "userCountryId": 109,
            "gameId": game_id,
        }
        resp = _api_session.get(SCORES365_GAME_URL, params=params, timeout=3.5)
        if resp.ok:
            payload = resp.json()
            networks = payload.get("game", {}).get("tvNetworks", []) or []
            channels = []
            for net in networks:
                name = str(net.get("name", "")).strip()
                # Ignorar casas de apuestas si vienen como tipo de stream
                if name and not any(
                    b in name.lower() for b in ("bet365", "1xbet", "caliente", "betplay")
                ):
                    if name not in channels:
                        channels.append(name)
            _tv_networks_cache[game_id] = channels
            return channels
    except Exception as e:
        logger.debug("No se pudo obtener tvNetworks para gameId=%s: %s", game_id, e)

    return []


def _fetch_365scores_matches(target_date: datetime) -> list[dict]:
    """
    Consulta el endpoint JSON oficial de 365Scores para la fecha indicada en hora de Colombia.
    """
    date_str = target_date.strftime("%d/%m/%Y")
    params = {
        "appTypeId": 5,
        "langId": 29,
        "timezoneName": "America/Bogota",
        "userCountryId": 109,
        "sports": 1,
        "startDate": date_str,
        "endDate": date_str,
        "withBroadcasts": "true",
    }
    resp = _api_session.get(SCORES365_ALLSCORES_URL, params=params, timeout=7)
    resp.raise_for_status()
    payload = resp.json()

    competitions_meta: dict[int, dict] = {}
    for idx, comp in enumerate(payload.get("competitions", []) or []):
        cid = comp.get("id")
        if cid is not None:
            competitions_meta[int(cid)] = {
                "name": comp.get("name") or "Fútbol Internacional",
                "order": idx,
            }

    countries_meta: dict[int, str] = {}
    for country in payload.get("countries", []) or []:
        cid = country.get("id")
        if cid is not None:
            countries_meta[int(cid)] = country.get("name") or ""

    raw_games = payload.get("games", []) or []
    now_col = datetime.now(COLOMBIA_TZ)
    parsed_games: list[dict] = []
    tv_candidates: list[dict] = []

    for g in raw_games:
        try:
            start_iso = g.get("startTime", "")
            start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).astimezone(
                COLOMBIA_TZ
            )
        except Exception:
            continue

        # Asegurar que el partido pertenezca al día consultado en hora de Colombia
        if start_dt.date() != target_date.date():
            continue

        comp_id = int(g.get("competitionId", 0))
        comp_info = competitions_meta.get(comp_id, {})
        raw_comp_name = (
            g.get("competitionDisplayName")
            or comp_info.get("name")
            or "Fútbol Internacional"
        )
        comp_name = _clean_competition_name(raw_comp_name)
        comp_order = int(comp_info.get("order", 999))

        home_obj = g.get("homeCompetitor", {}) or {}
        away_obj = g.get("awayCompetitor", {}) or {}
        home_name = str(home_obj.get("name", "Local")).strip()
        away_name = str(away_obj.get("name", "Visitante")).strip()
        home_score = home_obj.get("score", -1)
        away_score = away_obj.get("score", -1)

        status_group = int(g.get("statusGroup", 2))
        status_text = str(g.get("statusText", "")).strip()
        game_time_disp = str(g.get("gameTimeDisplay", "")).strip()

        # Clasificar estado: live, upcoming, finished
        if status_group == 3:
            status_code = "live"
            if game_time_disp:
                status_badge = f"🔴 EN VIVO ({game_time_disp})"
            elif status_text:
                status_badge = f"🔴 EN VIVO ({status_text})"
            else:
                status_badge = "🔴 EN VIVO"
        elif status_group == 4:
            status_code = "finished"
            status_badge = f"✅ {status_text or 'Finalizado'}"
        else:
            status_code = "upcoming"
            if start_dt > now_col:
                delta = start_dt - now_col
                total_sec = int(delta.total_seconds())
                hours, rem = divmod(total_sec, 3600)
                mins = rem // 60
                if hours > 0 and hours < 24:
                    status_badge = f"⏳ En {hours}h {mins}m"
                elif hours == 0:
                    status_badge = f"⏳ En {max(1, mins)}m"
                else:
                    status_badge = "🗓️ Programado"
            else:
                status_badge = f"🗓️ {status_text or 'Programado'}"

        has_tv = bool(g.get("hasTVNetworks"))
        is_featured = _is_featured_competition(comp_name)

        item = {
            "game_id": int(g.get("id", 0)),
            "comp_id": str(comp_id),
            "competition": comp_name,
            "comp_order": comp_order,
            "home": home_name,
            "away": away_name,
            "home_score": int(home_score) if isinstance(home_score, (int, float)) and home_score >= 0 else None,
            "away_score": int(away_score) if isinstance(away_score, (int, float)) and away_score >= 0 else None,
            "start_dt": start_dt,
            "time_str": start_dt.strftime("%I:%M %p").lstrip("0"),
            "status": status_code,
            "status_badge": status_badge,
            "has_tv": False,
            "is_featured": is_featured,
            "channels": [],
        }
        parsed_games.append(item)
        if has_tv and item["game_id"]:
            tv_candidates.append(item)

    # Consultar canales específicos en paralelo para los partidos con TV en 365Scores
    if tv_candidates:
        # Priorizar en vivo, destacados y próximos
        tv_candidates.sort(
            key=lambda x: (
                0 if x["status"] == "live" else 1 if x["status"] == "upcoming" else 2,
                0 if x["is_featured"] else 1,
                x["comp_order"],
            )
        )
        subset_tv = tv_candidates[:16]
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {
                pool.submit(_fetch_single_game_tv_365, item["game_id"]): item
                for item in subset_tv
            }
            for fut, item in futures.items():
                try:
                    ch_list = fut.result(timeout=4.0)
                    if ch_list:
                        item["channels"] = ch_list
                        item["has_tv"] = True
                except Exception:
                    pass

    return parsed_games


def _parse_lapelotona_time(time_str: str, base_date: datetime) -> datetime | None:
    """Convierte horas tipo '7:30 pm' o '11:00 am' de La Pelotona a datetime Colombia."""
    if not time_str:
        return None
    cleaned = time_str.strip().lower().replace(".", "")
    cleaned = re.sub(r"\s+", " ", cleaned)
    m = re.search(r"(\d{1,2}:\d{2})\s*([ap]m)?", cleaned)
    if not m:
        return None
    hhmm = m.group(1)
    ampm = m.group(2)
    date_part = base_date.strftime("%Y-%m-%d")
    try:
        if ampm:
            dt = datetime.strptime(f"{date_part} {hhmm} {ampm.upper()}", "%Y-%m-%d %I:%M %p")
        else:
            dt = datetime.strptime(f"{date_part} {hhmm}", "%Y-%m-%d %H:%M")
        return dt.replace(tzinfo=COLOMBIA_TZ)
    except ValueError:
        return None


def _fetch_lapelotona_matches(position: int, target_date: datetime) -> list[dict]:
    """
    Extrae los partidos televisados en Colombia desde La Pelotona usando sus selectores
    semánticos (.hc-partido-row) y el fallback de tablas.
    """
    fetcher = get_shared_fetcher(adaptive=True)
    html_doc = fetcher.get(LAPELOTONA_URL)

    table_id = "#partidos-hoy" if position == 0 else "#partidos-manana"
    rows_nodes = html_doc.css(f"{table_id} tr.hc-partido-row")

    if not rows_nodes:
        # Fallback por índice de .partidos-tabla
        tables = html_doc.css(".partidos-tabla")
        target_idx = 0 if position == 0 else 1
        if len(tables) > target_idx:
            rows_nodes = tables[target_idx].css("tr.hc-partido-row")

    now_col = datetime.now(COLOMBIA_TZ)
    results: list[dict] = []

    def _txt(nodes) -> str:
        if not nodes:
            return ""
        n = nodes[0]
        if hasattr(n, "text") and n.text:
            return str(n.text).strip()
        raw = n.extract() if hasattr(n, "extract") else str(n)
        if isinstance(raw, list):
            raw = raw[0] if raw else ""
        return re.sub(r"<[^>]+>", "", str(raw)).strip()

    for idx, row in enumerate(rows_nodes):
        home = _txt(row.css(".hc-team-local a")) or _txt(row.css(".hc-team-local"))
        away = _txt(row.css(".hc-team-visitante a")) or _txt(row.css(".hc-team-visitante"))
        hora_raw = _txt(row.css(".hc-time"))
        liga = _txt(row.css(".hc-liga a")) or _txt(row.css(".hc-liga")) or "Fútbol"
        canales_raw = _txt(row.css(".hc-canal"))

        if not home or not away or not hora_raw:
            continue

        start_dt = _parse_lapelotona_time(hora_raw, target_date)
        if start_dt is None:
            continue

        channels = [
            c.strip()
            for c in re.split(r"[,;]", canales_raw)
            if c.strip()
        ]

        # Calcular estado según la hora actual en Colombia
        if position == 0:
            if start_dt <= now_col <= start_dt + timedelta(minutes=115):
                elapsed = int((now_col - start_dt).total_seconds() // 60)
                status_code = "live"
                status_badge = f"🔴 EN JUEGO (~{max(1, min(elapsed, 90))}')"
            elif start_dt > now_col:
                delta = start_dt - now_col
                total_sec = int(delta.total_seconds())
                hours, rem = divmod(total_sec, 3600)
                mins = rem // 60
                status_code = "upcoming"
                status_badge = (
                    f"⏳ En {hours}h {mins}m" if hours > 0 else f"⏳ En {max(1, mins)}m"
                )
            else:
                status_code = "finished"
                status_badge = "✅ Finalizado"
        else:
            status_code = "upcoming"
            status_badge = "📆 Mañana"

        results.append({
            "game_id": 900_000 + idx,
            "comp_id": f"lp_{_normalize_key(liga)[:12] or idx}",
            "competition": liga,
            "comp_order": idx,
            "home": home,
            "away": away,
            "home_score": None,
            "away_score": None,
            "start_dt": start_dt,
            "time_str": start_dt.strftime("%I:%M %p").lstrip("0"),
            "status": status_code,
            "status_badge": status_badge,
            "has_tv": bool(channels),
            "is_featured": True,
            "channels": channels,
        })

    return results


def fetch_matches_data(position: int = 0, force_refresh: bool = False) -> list[dict]:
    """
    Obtiene la lista unificada de partidos para Hoy (position=0) o Mañana (position=1).
    Combina el endpoint JSON de 365Scores (marcadores en vivo, minuto, estado, ligas)
    con la guía de canales de TV en Colombia de La Pelotona.
    """
    pos = 0 if position == 0 else 1
    now_ts = time.time()

    with _matches_lock:
        cached = _matches_cache.get(pos)
        if (
            not force_refresh
            and cached
            and cached["data"] is not None
            and (now_ts - float(cached["timestamp"])) < MATCHES_CACHE_TTL
        ):
            return cached["data"]  # type: ignore[return-value]

    target_date = datetime.now(COLOMBIA_TZ) + timedelta(days=pos)

    games_365: list[dict] = []
    games_lp: list[dict] = []

    with ThreadPoolExecutor(max_workers=2) as executor:
        fut_365 = executor.submit(_fetch_365scores_matches, target_date)
        fut_lp = executor.submit(_fetch_lapelotona_matches, pos, target_date)

        try:
            games_365 = fut_365.result(timeout=10)
        except Exception as e:
            logger.warning("Fallo consultando 365Scores API: %s", e)

        try:
            games_lp = fut_lp.result(timeout=10)
        except Exception as e:
            logger.warning("Fallo consultando La Pelotona: %s", e)

    # Si ambos existen, enriquecer 365Scores con los canales de TV de La Pelotona
    if games_365 and games_lp:
        for lp_game in games_lp:
            matched = False
            for g365 in games_365:
                time_diff_min = abs(
                    (g365["start_dt"] - lp_game["start_dt"]).total_seconds()
                ) / 60.0
                if time_diff_min <= 90 and _teams_match(
                    g365["home"], g365["away"], lp_game["home"], lp_game["away"]
                ):
                    merged_channels = list(lp_game["channels"])
                    for ch in g365["channels"]:
                        if ch.lower() not in {c.lower() for c in merged_channels}:
                            merged_channels.append(ch)
                    g365["channels"] = merged_channels
                    g365["has_tv"] = bool(merged_channels) or g365["has_tv"]
                    g365["is_featured"] = True
                    matched = True
                    break

            if not matched:
                # Agregar partido televisado en Colombia que no haya cruzado
                games_365.append(lp_game)

        unified = games_365
    elif games_365:
        unified = games_365
    else:
        unified = games_lp

    # Ordenar por hora de inicio y relevancia de la liga
    unified.sort(key=lambda g: (g["start_dt"], g.get("comp_order", 999)))

    # Asignar IDs cortos estables por competición (c1, c2, ...) para que callback_data sea compacto
    comp_keys: dict[str, str] = {}
    for g in unified:
        cname = g["competition"]
        if cname not in comp_keys:
            comp_keys[cname] = f"c{len(comp_keys) + 1}"
        g["short_comp_id"] = comp_keys[cname]

    with _matches_lock:
        _matches_cache[pos] = {"data": unified, "timestamp": now_ts}

    return unified


# ==============================================================================
# INTERFAZ INTERACTIVA HTML + INLINE KEYBOARD PARA TELEGRAM
# ==============================================================================

def _filter_matches(
    all_games: list[dict],
    mode: str,
    comp_id: str,
    position: int,
) -> tuple[list[dict], str, str]:
    """
    Aplica los filtros seleccionados y devuelve (lista_filtrada, modo_efectivo, etiqueta_filtro).
    """
    # Primero filtrar por competición si comp_id != "0"
    pool = (
        [g for g in all_games if g.get("short_comp_id") == comp_id]
        if comp_id != "0"
        else list(all_games)
    )

    tv_games = [
        g for g in pool
        if g.get("channels") or g.get("has_tv") or g.get("is_featured")
    ]
    live_games = [g for g in pool if g.get("status") == "live"]
    up_games = [g for g in pool if g.get("status") in ("live", "upcoming")]

    effective_mode = mode
    if effective_mode == "auto":
        if comp_id != "0":
            effective_mode = "all"
        elif position == 0:
            # En hoy: priorizar Destacados/TV que estén en vivo o por jugar; si no, próximos
            tv_active = [g for g in tv_games if g.get("status") in ("live", "upcoming")]
            if tv_active and len(pool) > 8:
                effective_mode = "tv"
            elif up_games:
                effective_mode = "up"
            elif tv_games:
                effective_mode = "tv"
            else:
                effective_mode = "all"
        else:
            effective_mode = "tv" if (tv_games and len(pool) > 8) else "all"

    if effective_mode == "live":
        filtered = live_games
        label = "🔴 En Vivo"
    elif effective_mode == "up":
        filtered = up_games
        label = "⏳ En Juego / Próximos"
    elif effective_mode == "tv":
        filtered = tv_games
        label = "⭐ Con TV / Destacados"
    else:
        effective_mode = "all"
        filtered = pool
        label = "🌐 Todos los partidos"

    # Ordenar poniendo primero los partidos EN VIVO, luego PRÓXIMOS por hora, luego FINALIZADOS
    status_priority = {"live": 0, "upcoming": 1, "finished": 2}
    filtered.sort(
        key=lambda g: (
            status_priority.get(g.get("status", "upcoming"), 1),
            g["start_dt"],
            g.get("comp_order", 999),
        )
    )

    return filtered, effective_mode, label


def build_matches_message(
    position: int = 0,
    mode: str = "auto",
    comp_id: str = "0",
    page: int = 0,
    force_refresh: bool = False,
    page_size: int = 8,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Construye el mensaje HTML enriquecido y el teclado InlineKeyboardMarkup interactivo
    para consultar los partidos de Hoy (position=0) o Mañana (position=1).
    """
    pos = 0 if position == 0 else 1
    target_date = datetime.now(COLOMBIA_TZ) + timedelta(days=pos)
    day_title = "HOY" if pos == 0 else "MAÑANA"
    date_pretty = _format_spanish_date(target_date)

    all_games = fetch_matches_data(position=pos, force_refresh=force_refresh)

    # Contadores globales para los botones
    total_count = len(all_games)
    live_count = sum(1 for g in all_games if g.get("status") == "live")
    up_count = sum(1 for g in all_games if g.get("status") in ("live", "upcoming"))
    tv_count = sum(
        1
        for g in all_games
        if g.get("channels") or g.get("has_tv") or g.get("is_featured")
    )

    # Mapa de ligas disponibles ese día: short_comp_id -> {name, count, tv_count}
    leagues_map: dict[str, dict] = {}
    for g in all_games:
        cid = g.get("short_comp_id", "c0")
        if cid not in leagues_map:
            leagues_map[cid] = {
                "id": cid,
                "name": g["competition"],
                "count": 0,
                "has_tv": False,
                "is_featured": g.get("is_featured", False),
            }
        leagues_map[cid]["count"] += 1
        if g.get("channels") or g.get("has_tv"):
            leagues_map[cid]["has_tv"] = True

    leagues_list = sorted(
        leagues_map.values(),
        key=lambda x: (not x["has_tv"], not x["is_featured"], -x["count"], x["name"]),
    )

    # Si el usuario abrió el selector interactivo de Ligas / Torneos:
    if mode == "leagues":
        leagues_per_page = 10
        total_l_pages = max(1, (len(leagues_list) + leagues_per_page - 1) // leagues_per_page)
        l_page = max(0, min(page, total_l_pages - 1))
        l_slice = leagues_list[l_page * leagues_per_page : (l_page + 1) * leagues_per_page]

        lines = [
            f"🏆 <b>EXPLORADOR DE LIGAS — {day_title}</b>",
            f"📅 <i>{date_pretty}</i>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            (
                f"<blockquote>📊 <b>{ len(leagues_list) } torneos activos</b> con "
                f"<b>{total_count} partidos</b> programados.\n"
                "👇 <i>Toca una liga en los botones para filtrar sus partidos:</i></blockquote>"
            ),
            "",
        ]
        for lg in l_slice:
            tv_icon = "📺" if lg["has_tv"] else "⚽"
            lines.append(
                f"{tv_icon} <b>{html.escape(lg['name'])}</b> — <code>{lg['count']} part.</code>"
            )

        lines.append("\n━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"📄 <i>Página de ligas {l_page + 1} de {total_l_pages}</i>")

        markup = InlineKeyboardMarkup(row_width=2)
        btn_buffer = []
        for lg in l_slice:
            short_name = lg["name"]
            if len(short_name) > 20:
                short_name = short_name[:19].rstrip() + "…"
            icon = "📺" if lg["has_tv"] else "🏆"
            btn_buffer.append(
                InlineKeyboardButton(
                    f"{icon} {short_name} ({lg['count']})",
                    callback_data=f"m|{pos}|all|{lg['id']}|0|0",
                )
            )
            if len(btn_buffer) == 2:
                markup.row(*btn_buffer)
                btn_buffer = []
        if btn_buffer:
            markup.row(*btn_buffer)

        if total_l_pages > 1:
            nav = []
            if l_page > 0:
                nav.append(
                    InlineKeyboardButton("◀️ Ant.", callback_data=f"m|{pos}|leagues|0|{l_page - 1}|0")
                )
            nav.append(
                InlineKeyboardButton(f"📄 {l_page + 1}/{total_l_pages}", callback_data="m|noop")
            )
            if l_page < total_l_pages - 1:
                nav.append(
                    InlineKeyboardButton("Sig. ▶️", callback_data=f"m|{pos}|leagues|0|{l_page + 1}|0")
                )
            markup.row(*nav)

        markup.row(
            InlineKeyboardButton("🔙 Volver a los partidos", callback_data=f"m|{pos}|auto|0|0|0")
        )
        return "\n".join(lines), markup

    # Validar que comp_id exista si fue seleccionado
    if comp_id != "0" and comp_id not in leagues_map:
        comp_id = "0"

    filtered_games, effective_mode, mode_label = _filter_matches(
        all_games, mode, comp_id, pos
    )

    total_filtered = len(filtered_games)
    total_pages = max(1, (total_filtered + page_size - 1) // page_size)
    current_page = max(0, min(page, total_pages - 1))

    start_idx = current_page * page_size
    end_idx = min(start_idx + page_size, total_filtered)
    page_games = filtered_games[start_idx:end_idx]

    selected_league_name = (
        leagues_map[comp_id]["name"] if comp_id != "0" and comp_id in leagues_map else None
    )

    # Encabezado del mensaje HTML
    header_lines = [
        f"⚽ <b>AGENDA DE FÚTBOL — {day_title}</b> 🇨🇴",
        f"📅 <i>{date_pretty}</i>",
        (
            f"<blockquote>"
            f"📊 <b>Total:</b> {total_count} │ "
            f"🔴 <b>Vivo:</b> {live_count} │ "
            f"📺 <b>Destacados:</b> {tv_count} │ "
            f"🏆 <b>Ligas:</b> {len(leagues_list)}\n"
            f"🎯 <b>Vista:</b> {html.escape(selected_league_name or mode_label)} "
            f"({total_filtered})"
            f"</blockquote>"
        ),
    ]

    body_lines: list[str] = []
    if not page_games:
        body_lines.append("")
        if effective_mode == "live":
            body_lines.append("😴 <i>No hay partidos jugándose en vivo en este instante.</i>")
            body_lines.append("💡 <i>Usa los botones de abajo para ver los <b>Próximos</b> o <b>Destacados</b>.</i>")
        elif effective_mode == "up":
            body_lines.append("🏁 <i>Ya finalizaron los partidos programados para este filtro.</i>")
            body_lines.append("💡 <i>Toca <b>🌐 Todos</b> o <b>📆 Mañana</b> en los botones inferiores.</i>")
        else:
            body_lines.append("⚠️ <i>No se encontraron partidos para este filtro.</i>")
    else:
        # Agrupar visualmente por competición manteniendo el orden de la página
        current_comp = None
        for g in page_games:
            comp_title = g["competition"]
            if comp_title != current_comp:
                current_comp = comp_title
                body_lines.append(f"\n🏆 <b>{html.escape(comp_title.upper())}</b>")

            home_esc = html.escape(g["home"])
            away_esc = html.escape(g["away"])
            time_esc = html.escape(g["time_str"])
            badge_esc = html.escape(g["status_badge"])

            # Mostrar marcador si el partido está en vivo o finalizado
            h_score = g.get("home_score")
            a_score = g.get("away_score")
            if g.get("status") in ("live", "finished") and h_score is not None and a_score is not None:
                matchup_str = f"<b>{home_esc}</b>  <code>{h_score} - {a_score}</code>  <b>{away_esc}</b>"
            else:
                matchup_str = f"<b>{home_esc}</b> vs <b>{away_esc}</b>"

            channels = g.get("channels") or []
            if channels:
                ch_formatted = " • ".join(f"<code>{html.escape(c)}</code>" for c in channels[:4])
                body_lines.append(
                    f"┌ 🕒 <b>{time_esc}</b>  <i>({badge_esc})</i>\n"
                    f"├ ⚔️ {matchup_str}\n"
                    f"└ 📺 {ch_formatted}"
                )
            else:
                tv_hint = " <i>(📡 Seguimiento en vivo)</i>" if not g.get("has_tv") else " <i>(📺 TV por confirmar)</i>"
                body_lines.append(
                    f"┌ 🕒 <b>{time_esc}</b>  <i>({badge_esc})</i>\n"
                    f"└ ⚔️ {matchup_str}{tv_hint}"
                )

    now_col_str = datetime.now(COLOMBIA_TZ).strftime("%I:%M %p").lstrip("0")
    footer_lines = [
        "",
        "━━━━━━━━━━━━━━━━━━━━━━",
        (
            f"📖 <b>Pág. {current_page + 1}/{total_pages}</b> "
            f"(Mostrando {start_idx + 1}–{end_idx} de {total_filtered}) │ "
            f"🕒 <i>{now_col_str} COL</i>"
            if total_filtered > 0
            else f"🕒 <i>Actualizado: {now_col_str} (Hora COL)</i>"
        ),
    ]

    full_text = "\n".join(header_lines + body_lines + footer_lines)

    # Construcción del InlineKeyboardMarkup enriquecido
    markup = InlineKeyboardMarkup()

    # Fila 1: Paginación inteligente (cuando hay más de 1 página)
    if total_pages > 1:
        nav_row = []
        if total_pages >= 4 and current_page > 0:
            nav_row.append(
                InlineKeyboardButton("⏮️", callback_data=f"m|{pos}|{effective_mode}|{comp_id}|0|0")
            )
        if current_page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    "◀️ Ant.",
                    callback_data=f"m|{pos}|{effective_mode}|{comp_id}|{current_page - 1}|0",
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                f"📄 {current_page + 1} / {total_pages}",
                callback_data="m|noop",
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    "Sig. ▶️",
                    callback_data=f"m|{pos}|{effective_mode}|{comp_id}|{current_page + 1}|0",
                )
            )
        if total_pages >= 4 and current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    "⏭️",
                    callback_data=f"m|{pos}|{effective_mode}|{comp_id}|{total_pages - 1}|0",
                )
            )
        markup.row(*nav_row)

    # Fila 2: Filtros rápidos de modo (TV/Destacados, Próximos, En Vivo, Todos)
    def _lbl(active: bool, text: str) -> str:
        return f"✅ {text}" if active else text

    is_all_leagues = comp_id == "0"
    markup.row(
        InlineKeyboardButton(
            _lbl(is_all_leagues and effective_mode == "tv", f"⭐ TV/Top ({tv_count})"),
            callback_data=f"m|{pos}|tv|0|0|0",
        ),
        InlineKeyboardButton(
            _lbl(is_all_leagues and effective_mode == "up", f"⏳ Próximos ({up_count})"),
            callback_data=f"m|{pos}|up|0|0|0",
        ),
    )
    markup.row(
        InlineKeyboardButton(
            _lbl(is_all_leagues and effective_mode == "live", f"🔴 Vivo ({live_count})"),
            callback_data=f"m|{pos}|live|0|0|0",
        ),
        InlineKeyboardButton(
            _lbl(is_all_leagues and effective_mode == "all", f"🌐 Todos ({total_count})"),
            callback_data=f"m|{pos}|all|0|0|0",
        ),
    )

    # Fila 3: Selector de Ligas / Torneos
    if comp_id != "0" and selected_league_name:
        short_lg = (
            selected_league_name[:16] + "…"
            if len(selected_league_name) > 17
            else selected_league_name
        )
        markup.row(
            InlineKeyboardButton(
                f"❌ Quitar: {short_lg}",
                callback_data=f"m|{pos}|tv|0|0|0",
            ),
            InlineKeyboardButton(
                f"🏆 Otra Liga ({len(leagues_list)})",
                callback_data=f"m|{pos}|leagues|0|0|0",
            ),
        )
    elif len(leagues_list) > 1:
        markup.row(
            InlineKeyboardButton(
                f"🏆 Filtrar por Liga / Torneo ({len(leagues_list)} disponibles)",
                callback_data=f"m|{pos}|leagues|0|0|0",
            )
        )

    # Fila 4: Cambio rápido Hoy / Mañana + Refrescar
    hoy_label = "📍 📅 Hoy" if pos == 0 else "📅 Hoy"
    man_label = "📍 📆 Mañana" if pos == 1 else "📆 Mañana"
    markup.row(
        InlineKeyboardButton(hoy_label, callback_data="m|0|auto|0|0|0"),
        InlineKeyboardButton(man_label, callback_data="m|1|auto|0|0|0"),
        InlineKeyboardButton(
            "🔄 Actualizar",
            callback_data=f"m|{pos}|{effective_mode}|{comp_id}|{current_page}|1",
        ),
    )

    return full_text, markup


# ==============================================================================
# COMPATIBILIDAD LEGACY (matches -> BytesIO PNG)
# ==============================================================================

def matches(position: int = 0) -> BytesIO:
    """
    Genera imagen PNG con tabla de partidos (mantenido por compatibilidad con notebooks/scripts).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    all_games = fetch_matches_data(position=position)
    filtered, _, _ = _filter_matches(all_games, mode="auto", comp_id="0", position=position)

    if not filtered:
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

    rows = []
    for g in filtered:
        rows.append({
            "Equipos": wrap_text(f"{g['home']} vs {g['away']} ({g['competition']})", width=32),
            "Hora": wrap_text(f"{g['time_str']} {g['status_badge']}", width=22),
            "Canales": wrap_text(", ".join(g.get("channels") or ["Sin TV confirmada"]), width=42),
        })

    matches_table = pd.DataFrame(rows)

    def line_count(s):
        try:
            return str(s).count("\n") + 1
        except Exception:
            return 1

    lines_per_row = matches_table.apply(lambda col: col.map(line_count)).max(axis=1).tolist()
    header_unit = 2
    row_units = [max(2, int(x)) for x in lines_per_row]
    total_units = header_unit + sum(row_units)
    fig_height = max(4, total_units * 0.38)

    fig, ax = plt.subplots(figsize=(15, fig_height))
    ax.axis("tight")
    ax.axis("off")

    mpl_table = ax.table(
        cellText=matches_table.values,
        colLabels=matches_table.columns,
        cellLoc="center",
        loc="center",
        colWidths=[0.38, 0.22, 0.40],
    )
    mpl_table.auto_set_font_size(False)
    mpl_table.set_fontsize(9)
    mpl_table.scale(1.05, 1)

    header_color = "#40466e"
    row_colors = ["#f1f1f2", "w"]
    unit_height = 1.0 / float(total_units)

    for (i, j), cell in mpl_table._cells.items():
        cell.set_edgecolor("black")
        if i == 0:
            cell.set_text_props(weight="bold", color="w")
            cell.set_facecolor(header_color)
            cell.set_height(header_unit * unit_height)
        else:
            cell.set_facecolor(row_colors[i % len(row_colors)])
            unit = row_units[i - 1] if (i - 1) < len(row_units) else 2
            cell.set_height(unit * unit_height)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    img_io = BytesIO()
    plt.savefig(img_io, format="png", bbox_inches="tight", pad_inches=0, dpi=200)
    img_io.seek(0)
    plt.close(fig)
    return img_io