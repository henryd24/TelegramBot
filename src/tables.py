from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html
import re
from threading import Lock
import textwrap
import time
import unicodedata

# pyrefly: ignore [missing-import]
from lxml import html as lxml_html
import requests
# pyrefly: ignore [missing-import]
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from .logger import setup_logging

logger = setup_logging(__name__)

COLOMBIA_TZ = timezone(timedelta(hours=-5))

# HTTP session for JSON APIs and HTML tables
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
_xbox_cache: dict[str, dict[str, object]] = {
    "releases": {"items": None, "timestamp": 0.0},
    "gamepass": {"items": None, "timestamp": 0.0},
}
_xbox_lock = Lock()
XBOX_CACHE_TTL = 3600  # 1 hora

_matches_cache: dict[int, dict[str, object]] = {
    0: {"data": None, "timestamp": 0.0},
    1: {"data": None, "timestamp": 0.0},
}
_tv_networks_cache: dict[int, list[str]] = {}
_matches_lock = Lock()
MATCHES_CACHE_TTL = 180  # 3 minutos para refrescar marcadores en vivo

_standings_cache: dict[str, dict[str, object]] = {}
_standings_lock = Lock()
STANDINGS_CACHE_TTL = 600  # 10 minutos

SCORES365_ALLSCORES_URL = "https://webws.365scores.com/web/games/allscores/"
SCORES365_GAME_URL = "https://webws.365scores.com/web/game/"
LAPELOTONA_URL = "https://www.lapelotona.com/partidos-de-futbol-para-hoy-en-vivo/"

GAMEPASS_SIGL_RECENT_URL = (
    "https://catalog.gamepass.com/sigls/v2"
    "?id=f13cf6b4-57e6-4459-89df-6aec18cf0538&language=es-co&market=CO"
)
MS_DISPLAYCATALOG_URL = "https://displaycatalog.mp.microsoft.com/v7.0/products"

ESPN_STANDINGS_URL = (
    "https://site.api.espn.com/apis/v2/sports/soccer/{league}/standings?lang=es&region=co"
)

STANDINGS_LEAGUES: dict[str, dict[str, str]] = {
    "col.1": {"name": "Liga BetPlay Dimayor", "short": "🇨🇴 Liga BetPlay"},
    "eng.1": {"name": "Premier League", "short": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League"},
    "esp.1": {"name": "LaLiga EA Sports", "short": "🇪🇸 LaLiga"},
    "ita.1": {"name": "Serie A de Italia", "short": "🇮🇹 Serie A"},
    "ger.1": {"name": "Bundesliga", "short": "🇩🇪 Bundesliga"},
    "fra.1": {"name": "Ligue 1", "short": "🇫🇷 Ligue 1"},
    "uefa.champions": {"name": "UEFA Champions League", "short": "🇪🇺 Champions"},
    "conmebol.libertadores": {"name": "CONMEBOL Libertadores", "short": "🏆 Libertadores"},
    "conmebol.sudamericana": {"name": "CONMEBOL Sudamericana", "short": "🏆 Sudamericana"},
    "arg.1": {"name": "Liga Profesional Argentina", "short": "🇦🇷 Liga Argentina"},
    "bra.1": {"name": "Brasileirão Série A", "short": "🇧🇷 Brasileirão"},
}

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


def _format_spanish_date(dt: datetime) -> str:
    day_name = DAYS_ES.get(dt.weekday(), "")
    month_name = MONTHS_ES.get(dt.month, "")
    return f"{day_name}, {dt.day} de {month_name} de {dt.year}"


# ==============================================================================
# XBOX SERIES X|S: PRÓXIMOS LANZAMIENTOS + CATÁLOGO XBOX GAME PASS COLOMBIA
# ==============================================================================

def _parse_xbox_html_tables(html_text: str) -> list[dict[str, str]]:
    """Extrae la lista de {'Fecha': ..., 'Juego': ...} de la última tabla de Vandal."""
    if not html_text:
        return []
    doc = lxml_html.fromstring(html_text)
    tables = doc.xpath("//table")
    if not tables:
        return []

    target_table = tables[-1]
    items: list[dict[str, str]] = []
    for tr in target_table.xpath(".//tr"):
        cells = [
            re.sub(r"\s+", " ", "".join(td.itertext())).strip()
            for td in tr.xpath("./td")
        ]
        if len(cells) >= 2 and cells[0] and cells[1]:
            if cells[0].lower() == "fecha" and cells[1].lower() == "juego":
                continue
            items.append({"Fecha": cells[0], "Juego": cells[1]})
    return items


def _fetch_xbox_items(force_refresh: bool = False) -> list[dict[str, str]]:
    """Obtiene y cachea la lista de próximos lanzamientos de Xbox Series X|S."""
    now = time.time()
    with _xbox_lock:
        cached = _xbox_cache["releases"]
        if (
            not force_refresh
            and cached["items"] is not None
            and (now - float(cached["timestamp"])) < XBOX_CACHE_TTL
        ):
            return cached["items"]  # type: ignore[return-value]

    gamesurl = "https://vandal.elespanol.com/lanzamientos/97/xbox-series-x"
    try:
        resp = _api_session.get(gamesurl, timeout=10)
        resp.raise_for_status()
        items = _parse_xbox_html_tables(
            resp.content.decode("utf-8", errors="replace")
        )
    except Exception as e:
        logger.error("Error reading xbox games tables: %s", e)
        return []

    with _xbox_lock:
        _xbox_cache["releases"] = {"items": items, "timestamp": now}
    return items


def _fetch_gamepass_items(force_refresh: bool = False) -> list[dict[str, str]]:
    """
    Consulta la API oficial de Microsoft Xbox Game Pass Colombia (Agregados recientemente)
    e hidrata los títulos, géneros y precios en COP desde DisplayCatalog.
    """
    now = time.time()
    with _xbox_lock:
        cached = _xbox_cache["gamepass"]
        if (
            not force_refresh
            and cached["items"] is not None
            and (now - float(cached["timestamp"])) < XBOX_CACHE_TTL
        ):
            return cached["items"]  # type: ignore[return-value]

    try:
        sigl_resp = _api_session.get(GAMEPASS_SIGL_RECENT_URL, timeout=8)
        sigl_resp.raise_for_status()
        sigl_list = sigl_resp.json() or []
        product_ids = [
            str(entry["id"]).strip()
            for entry in sigl_list
            if isinstance(entry, dict) and entry.get("id")
        ][:24]

        if not product_ids:
            return []

        params = {
            "bigIds": ",".join(product_ids),
            "market": "CO",
            "languages": "es-co",
            "MS-CV": "DGU1mcuYo0WMMp+F.1",
        }
        cat_resp = _api_session.get(MS_DISPLAYCATALOG_URL, params=params, timeout=10)
        cat_resp.raise_for_status()
        products = (cat_resp.json() or {}).get("Products", []) or []

        by_id: dict[str, dict[str, str]] = {}
        for prod in products:
            pid = str(prod.get("ProductId", ""))
            loc_list = prod.get("LocalizedProperties") or [{}]
            loc = loc_list[0] if loc_list else {}
            title = str(loc.get("ProductTitle") or "Juego Xbox").strip()
            dev = str(loc.get("DeveloperName") or loc.get("PublisherName") or "").strip()

            props = prod.get("Properties") or {}
            category = str(props.get("Category") or "").strip()
            search_titles = loc.get("SearchTitles") or []
            if search_titles and isinstance(search_titles[0], dict):
                category = str(search_titles[0].get("SearchTitleString") or category).strip()

            # Buscar precio normal en tienda Colombia (COP)
            cop_price_str = ""
            availabilities = (
                (prod.get("DisplaySkuAvailabilities") or [{}])[0].get("Availabilities")
                or []
            )
            for av in availabilities:
                price_obj = (av.get("OrderManagementData") or {}).get("Price") or {}
                msrp = price_obj.get("MSRP") or price_obj.get("ListPrice")
                curr = price_obj.get("CurrencyCode")
                if curr == "COP" and msrp and float(msrp) > 0:
                    cop_price_str = f"${float(msrp):,.0f} COP"
                    break

            by_id[pid] = {
                "title": title,
                "developer": dev,
                "category": category or "Xbox / PC",
                "store_price": cop_price_str,
            }

        ordered_items = [by_id[pid] for pid in product_ids if pid in by_id]
        with _xbox_lock:
            _xbox_cache["gamepass"] = {"items": ordered_items, "timestamp": now}
        return ordered_items
    except Exception as e:
        logger.error("Error consultando Xbox Game Pass API: %s", e)
        return []


def xbox_games_view(
    page: int = 0,
    page_size: int = 10,
    force_refresh: bool = False,
    mode: str = "releases",
) -> tuple[str, InlineKeyboardMarkup | None]:
    """
    Construye el mensaje HTML y teclado interactivo para la sección de Xbox:
      - mode='releases': Próximos lanzamientos de Xbox Series X|S (Vandal)
      - mode='gamepass': Recién agregados a Xbox Game Pass Colombia (API Oficial Microsoft)
    """
    effective_mode = "gamepass" if mode == "gamepass" else "releases"

    if effective_mode == "gamepass":
        items = _fetch_gamepass_items(force_refresh=force_refresh)
        header_title = "🟢 <b>XBOX GAME PASS COLOMBIA — RECIÉN AGREGADOS</b>"
        source_footer = "🌐 <i>Fuente: Catálogo Oficial Xbox Game Pass (CO)</i>"
    else:
        items = _fetch_xbox_items(force_refresh=force_refresh)
        header_title = "🎮 <b>PRÓXIMOS LANZAMIENTOS — XBOX SERIES X|S</b>"
        source_footer = "🌐 <i>Fuente: Vandal Xbox Series X|S</i>"

    markup = InlineKeyboardMarkup()
    rel_lbl = "✅ 🚀 Lanzamientos" if effective_mode == "releases" else "🚀 Lanzamientos"
    gp_lbl = "✅ 🟢 Game Pass" if effective_mode == "gamepass" else "🟢 Game Pass"

    if not items:
        markup.row(
            InlineKeyboardButton(rel_lbl, callback_data="x|releases|0|0"),
            InlineKeyboardButton(gp_lbl, callback_data="x|gamepass|0|0"),
        )
        markup.row(
            InlineKeyboardButton(
                "🔄 Reintentar",
                callback_data=f"x|{effective_mode}|0|1",
            )
        )
        return (
            f"{header_title}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>No se encontraron títulos disponibles en este momento.</i>",
            markup,
        )

    total_items = len(items)
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = max(0, min(page, total_pages - 1))

    start_idx = page * page_size
    end_idx = min(start_idx + page_size, total_items)
    subset = items[start_idx:end_idx]

    lines = [
        header_title,
        f"<blockquote>📦 <b>Total listados:</b> {total_items} juegos │ 📄 <b>Página:</b> {page + 1}/{total_pages}</blockquote>",
        "",
    ]

    if effective_mode == "gamepass":
        for row in subset:
            title_esc = html.escape(row.get("title", "Juego"))
            cat_esc = html.escape(row.get("category", "Acción"))
            price_str = row.get("store_price", "")
            price_badge = (
                f" │ 🏷️ <s>{html.escape(price_str)}</s> <b>¡Gratis en GP!</b>"
                if price_str
                else " │ 🟢 <b>Incluido en GP</b>"
            )
            lines.append(
                f"🕹️ <b>{title_esc}</b>\n"
                f"└ 🎯 <i>{cat_esc}</i>{price_badge}\n"
            )
    else:
        for row in subset:
            fecha = html.escape(str(row.get("Fecha", "Por confirmar")).strip())
            juego = html.escape(str(row.get("Juego", "Juego")).strip())
            lines.append(f"🗓️ <code>{fecha}</code>\n└ 🕹️ <b>{juego}</b>\n")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(source_footer)

    if total_pages > 1:
        nav_buttons = []
        if page > 0:
            nav_buttons.append(
                InlineKeyboardButton(
                    "◀️ Anterior",
                    callback_data=f"x|{effective_mode}|{page - 1}|0",
                )
            )
        nav_buttons.append(
            InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="x|noop")
        )
        if page < total_pages - 1:
            nav_buttons.append(
                InlineKeyboardButton(
                    "Siguiente ▶️",
                    callback_data=f"x|{effective_mode}|{page + 1}|0",
                )
            )
        markup.row(*nav_buttons)

    markup.row(
        InlineKeyboardButton(rel_lbl, callback_data="x|releases|0|0"),
        InlineKeyboardButton(gp_lbl, callback_data="x|gamepass|0|0"),
    )
    markup.row(
        InlineKeyboardButton(
            "🔄 Actualizar lista",
            callback_data=f"x|{effective_mode}|{page}|1",
        )
    )
    return "\n".join(lines), markup


def xbox_games() -> str:
    """
    Retrieves the latest Xbox Series X games and returns them formatted in HTML.
    """
    text, _ = xbox_games_view(page=0, page_size=15, mode="releases")
    return text


def wrap_text(text, width: int = 20) -> str:
    """Wraps the input text to a specified width."""
    if text is None:
        return ""
    return "\n".join(textwrap.wrap(str(text), width))


# ==============================================================================
# TABLA DE POSICIONES (ESPN JSON API LOCALIZADA PARA COLOMBIA)
# ==============================================================================

def _fetch_espn_standings(league_code: str = "col.1", force_refresh: bool = False) -> dict:
    """Consulta y cachea la tabla de posiciones desde el endpoint JSON de ESPN."""
    code = league_code if league_code in STANDINGS_LEAGUES else "col.1"
    now = time.time()

    with _standings_lock:
        cached = _standings_cache.get(code)
        if (
            not force_refresh
            and cached
            and cached.get("data") is not None
            and (now - float(cached.get("timestamp", 0.0))) < STANDINGS_CACHE_TTL
        ):
            return cached["data"]  # type: ignore[return-value]

    url = ESPN_STANDINGS_URL.format(league=code)
    resp = _api_session.get(url, timeout=8)
    resp.raise_for_status()
    payload = resp.json() or {}

    league_title = (
        payload.get("name")
        or STANDINGS_LEAGUES[code]["name"]
    )
    groups_parsed: list[dict] = []

    children = payload.get("children") or []
    if not children and payload.get("standings"):
        children = [payload]

    for child in children:
        group_name = str(child.get("name") or child.get("abbreviation") or "").strip()
        standings_obj = child.get("standings") or {}
        entries = standings_obj.get("entries") or []
        if not entries:
            continue

        rows: list[dict] = []
        for idx, entry in enumerate(entries, start=1):
            team_obj = entry.get("team") or {}
            team_name = str(
                team_obj.get("shortDisplayName")
                or team_obj.get("displayName")
                or team_obj.get("name")
                or "Equipo"
            ).strip()

            stats_map: dict[str, str] = {}
            stats_val: dict[str, float] = {}
            for st in entry.get("stats") or []:
                sname = st.get("name")
                if sname:
                    stats_map[sname] = str(st.get("displayValue") or st.get("value") or "0")
                    try:
                        stats_val[sname] = float(st.get("value", 0.0))
                    except Exception:
                        pass

            rank = int(stats_val.get("rank", idx))
            pj = stats_map.get("gamesPlayed", "0")
            wins = stats_map.get("wins", "0")
            ties = stats_map.get("ties", "0")
            losses = stats_map.get("losses", "0")
            dif = stats_map.get("pointDifferential", "0")
            pts = stats_map.get("points", "0")

            rows.append({
                "rank": rank,
                "team": team_name,
                "pj": pj,
                "gep": f"{wins}-{ties}-{losses}",
                "dif": dif,
                "pts": pts,
            })

        rows.sort(key=lambda r: r["rank"])
        groups_parsed.append({
            "group_name": group_name,
            "rows": rows,
        })

    result = {
        "code": code,
        "title": league_title,
        "groups": groups_parsed,
    }
    with _standings_lock:
        _standings_cache[code] = {"data": result, "timestamp": now}
    return result


def build_standings_message(
    league_code: str = "col.1",
    page: int = 0,
    picker: bool = False,
    force_refresh: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Construye el mensaje HTML de la Tabla de Posiciones y el teclado interactivo
    para cambiar de liga o paginar.
    """
    code = league_code if league_code in STANDINGS_LEAGUES else "col.1"

    if picker:
        lines = [
            "📊 <b>TABLAS DE POSICIONES — SELECCIONA UNA LIGA</b>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "👇 <i>Elige el torneo que deseas consultar en tiempo real:</i>",
        ]
        markup = InlineKeyboardMarkup(row_width=2)
        btns = [
            InlineKeyboardButton(
                info["short"],
                callback_data=f"st|{lcode}|0|0",
            )
            for lcode, info in STANDINGS_LEAGUES.items()
        ]
        for i in range(0, len(btns), 2):
            markup.row(*btns[i : i + 2])
        markup.row(
            InlineKeyboardButton("🔙 Volver a tabla actual", callback_data=f"st|{code}|0|0")
        )
        return "\n".join(lines), markup

    try:
        data = _fetch_espn_standings(code, force_refresh=force_refresh)
    except Exception as e:
        logger.error("Error obteniendo tabla de posiciones (%s): %s", code, e)
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🏆 Elegir otra Liga", callback_data=f"st|{code}|0|pick")
        )
        return (
            "📊 <b>TABLA DE POSICIONES</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>No se pudo cargar la tabla de posiciones en este momento.</i>",
            markup,
        )

    groups = data.get("groups") or []
    short_title = STANDINGS_LEAGUES[code]["short"]

    if not groups:
        markup = InlineKeyboardMarkup()
        markup.row(
            InlineKeyboardButton("🏆 Elegir otra Liga", callback_data=f"st|{code}|0|pick")
        )
        return (
            f"📊 <b>{html.escape(short_title.upper())}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "ℹ️ <i>No hay tabla de posiciones activa disponible para este torneo.</i>",
            markup,
        )

    # Aplanar filas para paginar cómodamente (12 equipos por página)
    flat_rows: list[tuple[str, dict]] = []
    for grp in groups:
        gname = grp.get("group_name") or ""
        for r in grp.get("rows") or []:
            flat_rows.append((gname, r))

    page_size = 12
    total_rows = len(flat_rows)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    current_page = max(0, min(page, total_pages - 1))
    subset = flat_rows[current_page * page_size : (current_page + 1) * page_size]

    lines = [
        f"📊 <b>TABLA DE POSICIONES — {html.escape(short_title.upper())}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    current_grp = None
    table_lines: list[str] = []
    for gname, r in subset:
        if gname and gname != current_grp:
            if table_lines:
                lines.append("<pre>" + "\n".join(table_lines) + "</pre>")
                table_lines = []
            current_grp = gname
            lines.append(f"🏆 <b>{html.escape(gname)}</b>")
            table_lines.append(f"{'#':>2} {'Equipo':<15} {'PJ':>2} {'DIF':>4} {'PTS':>3}")
            table_lines.append("─" * 30)
        elif not table_lines:
            table_lines.append(f"{'#':>2} {'Equipo':<15} {'PJ':>2} {'DIF':>4} {'PTS':>3}")
            table_lines.append("─" * 30)

        t_name = r["team"][:15]
        table_lines.append(
            f"{r['rank']:>2} {t_name:<15} {r['pj']:>2} {r['dif']:>4} {r['pts']:>3}"
        )

    if table_lines:
        lines.append("<pre>" + "\n".join(table_lines) + "</pre>")

    now_str = datetime.now(COLOMBIA_TZ).strftime("%I:%M %p").lstrip("0")
    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"📖 <b>Pág. {current_page + 1}/{total_pages}</b> │ 🕒 <i>{now_str} COL</i>",
    ])

    markup = InlineKeyboardMarkup()
    if total_pages > 1:
        nav = []
        if current_page > 0:
            nav.append(
                InlineKeyboardButton("◀️ Ant.", callback_data=f"st|{code}|{current_page - 1}|0")
            )
        nav.append(
            InlineKeyboardButton(f"📄 {current_page + 1}/{total_pages}", callback_data="st|noop")
        )
        if current_page < total_pages - 1:
            nav.append(
                InlineKeyboardButton("Sig. ▶️", callback_data=f"st|{code}|{current_page + 1}|0")
            )
        markup.row(*nav)

    # Botones rápidos de ligas favoritas + selector completo
    markup.row(
        InlineKeyboardButton("🇨🇴 BetPlay", callback_data="st|col.1|0|0"),
        InlineKeyboardButton("🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier", callback_data="st|eng.1|0|0"),
        InlineKeyboardButton("🇪🇸 LaLiga", callback_data="st|esp.1|0|0"),
    )
    markup.row(
        InlineKeyboardButton("🏆 Más Ligas (11)", callback_data=f"st|{code}|0|pick"),
        InlineKeyboardButton("⚽ Ver Partidos", callback_data="m|0|auto|0|0|0"),
        InlineKeyboardButton("🔄 Actualizar", callback_data=f"st|{code}|{current_page}|1"),
    )
    return "\n".join(lines), markup


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

    if tv_candidates:
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
    semánticos (.hc-partido-row) y el fallback de tablas con lxml.html.
    """
    resp = _api_session.get(LAPELOTONA_URL, timeout=8)
    resp.raise_for_status()
    doc = lxml_html.fromstring(resp.content.decode("utf-8", errors="replace"))

    table_id = "partidos-hoy" if position == 0 else "partidos-manana"
    rows_nodes = doc.xpath(
        f"//*[@id='{table_id}']//tr[contains(@class, 'hc-partido-row')]"
    )

    if not rows_nodes:
        tables = doc.xpath("//*[contains(@class, 'partidos-tabla')]")
        target_idx = 0 if position == 0 else 1
        if len(tables) > target_idx:
            rows_nodes = tables[target_idx].xpath(
                ".//tr[contains(@class, 'hc-partido-row')]"
            )

    now_col = datetime.now(COLOMBIA_TZ)
    results: list[dict] = []

    def _xtxt(elem, xpath_expr: str) -> str:
        found = elem.xpath(xpath_expr)
        if not found:
            return ""
        text = re.sub(r"\s+", " ", "".join(found[0].itertext())).strip()
        return re.sub(
            r"^(canales?|hora|torneo|liga|partido)\s*:\s*",
            "",
            text,
            flags=re.IGNORECASE,
        ).strip()

    for idx, row in enumerate(rows_nodes):
        home = _xtxt(row, ".//*[contains(@class, 'hc-team-local')]//a") or _xtxt(
            row, ".//*[contains(@class, 'hc-team-local')]"
        )
        away = _xtxt(row, ".//*[contains(@class, 'hc-team-visitante')]//a") or _xtxt(
            row, ".//*[contains(@class, 'hc-team-visitante')]"
        )
        hora_raw = _xtxt(row, ".//*[contains(@class, 'hc-time')]")
        liga = (
            _xtxt(row, ".//*[contains(@class, 'hc-liga')]//a")
            or _xtxt(row, ".//*[contains(@class, 'hc-liga')]")
            or "Fútbol"
        )
        canales_raw = _xtxt(row, ".//*[contains(@class, 'hc-canal')]")

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
            "competition": _clean_competition_name(liga),
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
                games_365.append(lp_game)

        unified = games_365
    elif games_365:
        unified = games_365
    else:
        unified = games_lp

    unified.sort(key=lambda g: (g["start_dt"], g.get("comp_order", 999)))

    comp_keys: dict[str, str] = {}
    for g in unified:
        cname = g["competition"]
        if cname not in comp_keys:
            comp_keys[cname] = f"c{len(comp_keys) + 1}"
        g["short_comp_id"] = comp_keys[cname]

    with _matches_lock:
        _matches_cache[pos] = {"data": unified, "timestamp": now_ts}

    return unified


def find_game_by_id(position: int, game_id: str) -> dict | None:
    """Busca un partido por su game_id en la fecha indicada."""
    games = fetch_matches_data(position=position, force_refresh=False)
    for g in games:
        if str(g.get("game_id")) == str(game_id):
            return g
    return None


def search_matches_message(query: str) -> tuple[str, InlineKeyboardMarkup]:
    """
    Busca partidos por nombre de equipo o torneo tanto en Hoy como en Mañana,
    devolviendo tarjetas HTML y botones de recordatorio (🔔 10m antes).
    """
    q_norm = _normalize_key(query)
    q_raw_lower = query.strip().lower()

    results: list[tuple[int, dict]] = []
    for pos in (0, 1):
        day_games = fetch_matches_data(position=pos)
        for g in day_games:
            haystack_norm = _normalize_key(f"{g['home']} {g['away']} {g['competition']}")
            haystack_raw = f"{g['home']} {g['away']} {g['competition']}".lower()
            if (q_norm and q_norm in haystack_norm) or (q_raw_lower in haystack_raw):
                results.append((pos, g))

    markup = InlineKeyboardMarkup()
    if not results:
        markup.row(
            InlineKeyboardButton("⚽ Ver Partidos de Hoy", callback_data="m|0|auto|0|0|0"),
            InlineKeyboardButton("📆 Ver Mañana", callback_data="m|1|auto|0|0|0"),
        )
        return (
            f"🔍 <b>BÚSQUEDA DE PARTIDOS:</b> <code>{html.escape(query)}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "😕 <i>No se encontraron partidos para hoy ni mañana con ese criterio.</i>\n"
            "💡 <i>Prueba con otro equipo o torneo (ej. <code>/matches millonarios</code>, <code>/matches champions</code>).</i>",
            markup,
        )

    lines = [
        f"🔍 <b>RESULTADOS PARA:</b> <code>{html.escape(query.upper())}</code>",
        f"<blockquote>🎯 Se encontraron <b>{len(results)}</b> partidos entre Hoy y Mañana:</blockquote>",
    ]

    shown = results[:10]
    for pos, g in shown:
        day_tag = "📅 HOY" if pos == 0 else "📆 MAÑANA"
        comp_esc = html.escape(g["competition"])
        home_esc = html.escape(g["home"])
        away_esc = html.escape(g["away"])
        time_esc = html.escape(g["time_str"])
        badge_esc = html.escape(g["status_badge"])

        h_score = g.get("home_score")
        a_score = g.get("away_score")
        if g.get("status") in ("live", "finished") and h_score is not None and a_score is not None:
            matchup_str = f"<b>{home_esc}</b>  <code>{h_score} - {a_score}</code>  <b>{away_esc}</b>"
        else:
            matchup_str = f"<b>{home_esc}</b> vs <b>{away_esc}</b>"

        channels = g.get("channels") or []
        ch_line = (
            " • ".join(f"<code>{html.escape(c)}</code>" for c in channels[:4])
            if channels
            else "<i>Sin TV confirmada en CO</i>"
        )

        lines.append(
            f"\n🏆 <b>{comp_esc}</b> ({day_tag})\n"
            f"┌ 🕒 <b>{time_esc}</b>  <i>({badge_esc})</i>\n"
            f"├ ⚔️ {matchup_str}\n"
            f"└ 📺 {ch_line}"
        )

        if g.get("status") == "upcoming":
            btn_lbl = f"🔔 Recordar: {g['home'][:12]} vs {g['away'][:12]} ({g['time_str']})"
            markup.row(
                InlineKeyboardButton(
                    btn_lbl,
                    callback_data=f"al|set|{pos}|{g['game_id']}",
                )
            )

    markup.row(
        InlineKeyboardButton("⚽ Agenda de Hoy", callback_data="m|0|auto|0|0|0"),
        InlineKeyboardButton("🔔 Mis Alertas", callback_data="al|list"),
    )
    return "\n".join(lines), markup


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

    total_count = len(all_games)
    live_count = sum(1 for g in all_games if g.get("status") == "live")
    up_count = sum(1 for g in all_games if g.get("status") in ("live", "upcoming"))
    tv_count = sum(
        1
        for g in all_games
        if g.get("channels") or g.get("has_tv") or g.get("is_featured")
    )

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

    # 1. Vista Explorador de Ligas / Torneos
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
                f"<blockquote>📊 <b>{len(leagues_list)} torneos activos</b> con "
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

    # 2. Vista Selector de Recordatorios (🔔 Avisar 10m antes)
    if mode == "alerts":
        now_col = datetime.now(COLOMBIA_TZ)
        upcoming_pool = [
            g for g in all_games
            if g.get("status") == "upcoming"
            and g["start_dt"] > now_col
            and (comp_id == "0" or g.get("short_comp_id") == comp_id)
        ]
        upcoming_pool.sort(
            key=lambda g: (not g.get("has_tv"), not g.get("is_featured"), g["start_dt"])
        )
        a_per_page = 8
        total_a_pages = max(1, (len(upcoming_pool) + a_per_page - 1) // a_per_page)
        a_page = max(0, min(page, total_a_pages - 1))
        a_slice = upcoming_pool[a_page * a_per_page : (a_page + 1) * a_per_page]

        lines = [
            f"🔔 <b>PROGRAMAR RECORDATORIO — {day_title}</b>",
            f"📅 <i>{date_pretty}</i>",
            "━━━━━━━━━━━━━━━━━━━━━━",
            "<blockquote>👇 <b>Toca el partido</b> que deseas recordar y el bot avisará en este chat <b>10 minutos antes</b> del pitazo inicial:</blockquote>",
        ]
        markup = InlineKeyboardMarkup()
        if not a_slice:
            lines.append("\n⚠️ <i>No hay partidos pendientes por iniciar en este filtro.</i>")
        else:
            for g in a_slice:
                lbl = f"🔔 {g['time_str']} │ {g['home'][:12]} vs {g['away'][:12]}"
                markup.row(
                    InlineKeyboardButton(
                        lbl,
                        callback_data=f"al|set|{pos}|{g['game_id']}",
                    )
                )

        if total_a_pages > 1:
            nav = []
            if a_page > 0:
                nav.append(
                    InlineKeyboardButton("◀️ Ant.", callback_data=f"m|{pos}|alerts|{comp_id}|{a_page - 1}|0")
                )
            nav.append(
                InlineKeyboardButton(f"📄 {a_page + 1}/{total_a_pages}", callback_data="m|noop")
            )
            if a_page < total_a_pages - 1:
                nav.append(
                    InlineKeyboardButton("Sig. ▶️", callback_data=f"m|{pos}|alerts|{comp_id}|{a_page + 1}|0")
                )
            markup.row(*nav)

        markup.row(
            InlineKeyboardButton("📋 Mis Alertas Activas", callback_data="al|list"),
            InlineKeyboardButton("🔙 Volver a Partidos", callback_data=f"m|{pos}|auto|{comp_id}|0|0"),
        )
        return "\n".join(lines), markup

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

    markup = InlineKeyboardMarkup()

    # Fila 1: Paginación inteligente
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

    # Fila 2 y 3: Filtros rápidos de modo
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

    # Fila 4: Selector de Ligas + Tabla de Posiciones + Recordatorios
    if comp_id != "0" and selected_league_name:
        short_lg = (
            selected_league_name[:14] + "…"
            if len(selected_league_name) > 15
            else selected_league_name
        )
        markup.row(
            InlineKeyboardButton(
                f"❌ {short_lg}",
                callback_data=f"m|{pos}|tv|0|0|0",
            ),
            InlineKeyboardButton(
                f"🏆 Ligas ({len(leagues_list)})",
                callback_data=f"m|{pos}|leagues|0|0|0",
            ),
        )
    else:
        markup.row(
            InlineKeyboardButton(
                f"🏆 Ligas ({len(leagues_list)})",
                callback_data=f"m|{pos}|leagues|0|0|0",
            ),
            InlineKeyboardButton(
                "📊 Posiciones",
                callback_data="st|col.1|0|0",
            ),
            InlineKeyboardButton(
                "🔔 Recordar",
                callback_data=f"m|{pos}|alerts|{comp_id}|0|0",
            ),
        )

    # Fila 5: Cambio rápido Hoy / Mañana + Refrescar
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
# COMPATIBILIDAD LEGACY
# ==============================================================================

def matches(position: int = 0) -> str:
    """
    Devuelve la agenda de partidos formateada en HTML (compatibilidad directa).
    """
    text, _ = build_matches_message(position=position, mode="auto")
    return text