from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import html
from threading import Lock
import time
# pyrefly: ignore [missing-import]
from lxml import html as lxml_html
import requests
# pyrefly: ignore [missing-import]
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from .logger import setup_logging

DOLARAPI_TRM_URL = "https://co.dolarapi.com/v1/trm"
DOLARAPI_USD_URL = "https://co.dolarapi.com/v1/cotizaciones/usd"
DOLARAPI_EUR_URL = "https://co.dolarapi.com/v1/cotizaciones/eur"
COINGECKO_URL = (
    "https://api.coingecko.com/api/v3/simple/price"
    "?ids=bitcoin,ethereum,tether&vs_currencies=usd&include_24hr_change=true"
)
ER_API_USD_URL = "https://open.er-api.com/v6/latest/USD"
GOOGLE_FINANCE_URL = "https://www.google.com/finance/quote/USD-COP"

logger = setup_logging(__name__)

_http_session = requests.Session()
_http_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; CaguanTelegramBot/2.0)",
    "Accept": "application/json",
})

_rates_cache: dict[str, object] = {"data": None, "timestamp": 0.0}
_trm_lock = Lock()
TRM_CACHE_TTL = 300  # 5 minutos
COLOMBIA_TZ = timezone(timedelta(hours=-5))


def node_text(nodes) -> str:
    if not nodes:
        return ""
    node = nodes[0]
    if isinstance(node, str):
        return node.strip()
    if hasattr(node, "text"):
        return node.text.strip()
    if hasattr(node, "extract"):
        ex = node.extract()
        if isinstance(ex, (list, tuple)):
            return str(ex[0]).strip() if ex else ""
        return str(ex).strip()
    return str(node).strip()


def _format_cop(value: float | int | None) -> str:
    if value is None:
        return "N/D"
    return f"${float(value):,.2f} COP"


def _format_iso_to_colombia(iso_str: str | None) -> str:
    if not iso_str:
        return datetime.now(COLOMBIA_TZ).strftime("%d/%m/%Y %I:%M %p")
    try:
        cleaned = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            dt = dt.astimezone(COLOMBIA_TZ)
        return dt.strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        return str(iso_str)


def _fetch_all_financial_data(force_refresh: bool = False) -> dict:
    """
    Obtiene y cachea TRM oficial, USD spot, EUR spot y Cripto (BTC, ETH, USDT).
    """
    now = time.time()
    with _trm_lock:
        if (
            not force_refresh
            and _rates_cache["data"] is not None
            and (now - float(_rates_cache["timestamp"])) < TRM_CACHE_TTL
        ):
            return _rates_cache["data"]  # type: ignore[return-value]

    def _get_json(url: str) -> dict:
        try:
            resp = _http_session.get(url, timeout=6)
            if resp.ok:
                return resp.json() or {}
        except Exception as e:
            logger.debug("Error consultando %s: %s", url, e)
        return {}

    with ThreadPoolExecutor(max_workers=4) as pool:
        f_trm = pool.submit(_get_json, DOLARAPI_TRM_URL)
        f_usd = pool.submit(_get_json, DOLARAPI_USD_URL)
        f_eur = pool.submit(_get_json, DOLARAPI_EUR_URL)
        f_cry = pool.submit(_get_json, COINGECKO_URL)

        trm_data = f_trm.result()
        usd_data = f_usd.result()
        eur_data = f_eur.result()
        crypto_data = f_cry.result()

    result = {
        "trm": trm_data,
        "usd": usd_data,
        "eur": eur_data,
        "crypto": crypto_data,
    }

    if trm_data or usd_data or eur_data:
        with _trm_lock:
            _rates_cache["data"] = result
            _rates_cache["timestamp"] = now

    return result


def _fetch_dolarapi() -> dict:
    """Compatibilidad con pruebas unitarias para obtener TRM y USD."""
    data = _fetch_all_financial_data(force_refresh=True)
    if not data.get("trm") and not data.get("usd"):
        raise RuntimeError("No se obtuvo respuesta de DolarAPI Colombia")
    return data


def _fallback_google_or_er() -> str:
    """Fallback si DolarAPI no responde: intenta ExchangeRate-API o Google Finance."""
    try:
        resp = _http_session.get(ER_API_USD_URL, timeout=6)
        if resp.ok:
            payload = resp.json()
            cop_rate = payload.get("rates", {}).get("COP")
            if cop_rate:
                now_str = datetime.now(COLOMBIA_TZ).strftime("%d/%m/%Y %I:%M %p")
                return (
                    "💵 <b>TASA DE CAMBIO USD / COP</b> 🇨🇴\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"💰 <b>Valor Actual:</b> <code>{_format_cop(cop_rate)}</code>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"🕒 <i>Actualizado: {now_str} (Fuente: ExchangeRate)</i>"
                )
    except Exception as e:
        logger.warning("Fallback ExchangeRate-API falló: %s", e)

    resp = _http_session.get(GOOGLE_FINANCE_URL, timeout=6)
    resp.raise_for_status()
    doc = lxml_html.fromstring(resp.content.decode("utf-8", errors="replace"))
    stock_name = html.escape(
        node_text(doc.xpath("//*[contains(@class, 'JV7gl')]/text()")) or "USD / COP"
    )
    current_price = html.escape(
        node_text(doc.xpath("//*[contains(@class, 'Pdsbrc')]/text()")) or "N/D"
    )
    previous_closing = html.escape(
        node_text(doc.xpath("//*[contains(@class, 'u77W5d')]/text()")) or "N/D"
    )

    return (
        f"💵 <b>TASA DE CAMBIO ({stock_name})</b> 🇨🇴\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Valor Actual:</b> <code>{current_price}</code>\n"
        f"📉 <b>Cierre Anterior:</b> <code>{previous_closing}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🕒 <i>Fuente: Google Finance</i>"
    )


def build_trm_markup(active_tab: str = "usd") -> InlineKeyboardMarkup:
    """Construye el teclado interactivo para alternar entre Dólar, Euro y Cripto."""
    def _lbl(tab: str, text: str) -> str:
        return f"✅ {text}" if active_tab == tab else text

    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton(_lbl("usd", "💵 Dólar"), callback_data="trm|tab|usd|0"),
        InlineKeyboardButton(_lbl("eur", "💶 Euro"), callback_data="trm|tab|eur|0"),
        InlineKeyboardButton(_lbl("crypto", "🪙 Cripto"), callback_data="trm|tab|crypto|0"),
    )
    markup.row(
        InlineKeyboardButton(
            "🔄 Actualizar cotización",
            callback_data=f"trm|tab|{active_tab}|1",
        )
    )
    return markup


def _format_usd_tab(data: dict) -> str:
    trm_info = data.get("trm") or {}
    usd_info = data.get("usd") or {}

    if not trm_info and not usd_info:
        return _fallback_google_or_er()

    trm_val = trm_info.get("valor")
    compra = usd_info.get("compra")
    venta = usd_info.get("venta")
    cierre = usd_info.get("ultimoCierre")
    fecha_act = usd_info.get("fechaActualizacion") or trm_info.get("fechaActualizacion")

    spot_actual = None
    if compra is not None and venta is not None:
        spot_actual = (float(compra) + float(venta)) / 2.0
    elif venta is not None:
        spot_actual = float(venta)
    elif compra is not None:
        spot_actual = float(compra)

    variacion_line = ""
    if spot_actual is not None and cierre:
        diff = spot_actual - float(cierre)
        pct = (diff / float(cierre)) * 100.0 if float(cierre) else 0.0
        if diff > 0.01:
            trend_emoji, sign = "📈", "+"
        elif diff < -0.01:
            trend_emoji, sign = "📉", ""
        else:
            trend_emoji, sign = "➖", ""
        variacion_line = (
            f"{trend_emoji} <b>Variación hoy:</b> "
            f"<code>{sign}${diff:,.2f} ({sign}{pct:.2f}%)</code>"
        )

    lines = [
        "💵 <b>PRECIO DEL DÓLAR EN COLOMBIA (USD / COP)</b> 🇨🇴",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if trm_val is not None:
        lines.append(f"🏛️ <b>TRM Oficial:</b> <code>{_format_cop(trm_val)}</code>")
    if spot_actual is not None:
        lines.append(f"💹 <b>Mercado Actual:</b> <code>{_format_cop(spot_actual)}</code>")
    if compra is not None and venta is not None:
        lines.append(
            f"<blockquote>"
            f"🟢 <b>Compra:</b> <code>${float(compra):,.2f}</code>\n"
            f"🔴 <b>Venta:</b> <code>${float(venta):,.2f}</code>"
            f"</blockquote>"
        )
    if cierre is not None:
        lines.append(f"⏮️ <b>Cierre Anterior:</b> <code>{_format_cop(cierre)}</code>")
    if variacion_line:
        lines.append(variacion_line)

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>Tip: Usa <code>/trm 150</code> o <code>/trm 500000 cop</code> para convertir</i>",
        f"🕒 <i>Actualizado: {_format_iso_to_colombia(fecha_act)} (Hora COL)</i>",
    ])
    return "\n".join(lines)


def _format_eur_tab(data: dict) -> str:
    eur_info = data.get("eur") or {}
    usd_info = data.get("usd") or {}
    trm_info = data.get("trm") or {}

    compra = eur_info.get("compra")
    venta = eur_info.get("venta")
    cierre = eur_info.get("ultimoCierre")
    fecha_act = eur_info.get("fechaActualizacion") or usd_info.get("fechaActualizacion")

    if compra is None and venta is None:
        return (
            "💶 <b>PRECIO DEL EURO EN COLOMBIA (EUR / COP)</b> 🇪🇺\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>No se pudo obtener la cotización del Euro en este momento.</i>"
        )

    spot_eur = (
        (float(compra) + float(venta)) / 2.0
        if (compra is not None and venta is not None)
        else float(venta or compra)
    )

    variacion_line = ""
    if cierre:
        diff = spot_eur - float(cierre)
        pct = (diff / float(cierre)) * 100.0 if float(cierre) else 0.0
        trend_emoji = "📈" if diff > 0.01 else "📉" if diff < -0.01 else "➖"
        sign = "+" if diff > 0.01 else ""
        variacion_line = (
            f"{trend_emoji} <b>Variación hoy:</b> "
            f"<code>{sign}${diff:,.2f} ({sign}{pct:.2f}%)</code>"
        )

    usd_ref = float(trm_info.get("valor") or usd_info.get("venta") or 0)
    eur_usd_ratio = (spot_eur / usd_ref) if usd_ref > 0 else None

    lines = [
        "💶 <b>PRECIO DEL EURO EN COLOMBIA (EUR / COP)</b> 🇪🇺",
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"💹 <b>Euro Promedio:</b> <code>{_format_cop(spot_eur)}</code>",
        (
            f"<blockquote>"
            f"🟢 <b>Compra:</b> <code>${float(compra):,.2f}</code>\n"
            f"🔴 <b>Venta:</b> <code>${float(venta):,.2f}</code>"
            f"</blockquote>"
        ),
    ]
    if cierre is not None:
        lines.append(f"⏮️ <b>Cierre Anterior:</b> <code>{_format_cop(cierre)}</code>")
    if variacion_line:
        lines.append(variacion_line)
    if eur_usd_ratio:
        lines.append(f"🌎 <b>Relación EUR/USD:</b> <code>1 EUR ≈ ${eur_usd_ratio:.4f} USD</code>")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>Tip: Usa <code>/trm 100 eur</code> para convertir Euros a COP</i>",
        f"🕒 <i>Actualizado: {_format_iso_to_colombia(fecha_act)} (Hora COL)</i>",
    ])
    return "\n".join(lines)


def _format_crypto_tab(data: dict) -> str:
    crypto = data.get("crypto") or {}
    usd_info = data.get("usd") or {}
    trm_info = data.get("trm") or {}

    cop_rate = float(
        usd_info.get("venta")
        or trm_info.get("valor")
        or 3350.0
    )

    btc = crypto.get("bitcoin") or {}
    eth = crypto.get("ethereum") or {}
    usdt = crypto.get("tether") or {}

    if not btc and not eth:
        return (
            "🪙 <b>MERCADO CRIPTO (USD / COP)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "⚠️ <i>No se pudo consultar CoinGecko en este momento.</i>"
        )

    def _coin_block(icon: str, name: str, symbol: str, info: dict) -> str:
        usd_val = float(info.get("usd", 0.0))
        chg = float(info.get("usd_24h_change", 0.0))
        cop_val = usd_val * cop_rate
        trend = "🟢 +" if chg >= 0 else "🔴 "
        usd_fmt = f"${usd_val:,.2f}" if usd_val >= 10 else f"${usd_val:,.4f}"
        return (
            f"{icon} <b>{name} ({symbol})</b>  <i>({trend}{chg:.2f}% 24h)</i>\n"
            f"├ 🇺🇸 <b>USD:</b> <code>{usd_fmt}</code>\n"
            f"└ 🇨🇴 <b>COP:</b> <code>${cop_val:,.0f} COP</code>"
        )

    now_str = datetime.now(COLOMBIA_TZ).strftime("%d/%m/%Y %I:%M %p")
    lines = [
        "🪙 <b>MERCADO CRIPTO EN TIEMPO REAL</b> 🚀",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if btc:
        lines.append(_coin_block("🟠", "Bitcoin", "BTC", btc))
        lines.append("")
    if eth:
        lines.append(_coin_block("🔷", "Ethereum", "ETH", eth))
        lines.append("")
    if usdt:
        lines.append(_coin_block("💵", "Tether", "USDT", usdt))

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>Tip: Usa <code>/trm 0.05 btc</code> o <code>/trm 200 usdt</code></i>",
        f"🕒 <i>Actualizado: {now_str} (Hora COL)</i>",
    ])
    return "\n".join(lines)


def build_trm_view(
    tab: str = "usd",
    force_refresh: bool = False,
) -> tuple[str, InlineKeyboardMarkup]:
    """
    Construye el mensaje HTML y el teclado interactivo para la pestaña seleccionada
    ('usd', 'eur' o 'crypto').
    """
    data = _fetch_all_financial_data(force_refresh=force_refresh)
    if tab == "eur":
        text = _format_eur_tab(data)
    elif tab == "crypto":
        text = _format_crypto_tab(data)
    else:
        tab = "usd"
        text = _format_usd_tab(data)

    return text, build_trm_markup(active_tab=tab)


def convert_currency_message(args: list[str]) -> tuple[str, InlineKeyboardMarkup]:
    """
    Convierte un monto entre USD, COP, EUR, BTC, ETH y USDT.
    Ejemplos soportados:
      /trm 150          -> 150 USD a COP (o si es >= 10,000 muestra ambos sentidos)
      /trm 500000 cop   -> 500,000 COP a USD, EUR, USDT
      /trm 200 eur      -> 200 EUR a COP y USD
      /trm 0.05 btc     -> 0.05 BTC a USD y COP
    """
    raw_amount = args[0].replace(",", ".").replace("$", "").strip()
    # Permitir separadores de miles tipo 500.000 si tiene 3 dígitos tras el punto y > 1 punto
    if raw_amount.count(".") > 1:
        raw_amount = raw_amount.replace(".", "")
    amount = float(raw_amount)

    currency = args[1].lower().strip() if len(args) > 1 else "auto"
    data = _fetch_all_financial_data(force_refresh=False)

    trm_info = data.get("trm") or {}
    usd_info = data.get("usd") or {}
    eur_info = data.get("eur") or {}
    crypto = data.get("crypto") or {}

    trm_rate = float(trm_info.get("valor") or usd_info.get("venta") or 3300.0)
    usd_compra = float(usd_info.get("compra") or trm_rate)
    usd_venta = float(usd_info.get("venta") or trm_rate)
    usd_spot = (usd_compra + usd_venta) / 2.0

    eur_compra = float(eur_info.get("compra") or (usd_spot * 1.08))
    eur_venta = float(eur_info.get("venta") or (usd_spot * 1.12))
    eur_spot = (eur_compra + eur_venta) / 2.0

    btc_usd = float((crypto.get("bitcoin") or {}).get("usd") or 84000.0)
    eth_usd = float((crypto.get("ethereum") or {}).get("usd") or 2600.0)

    if currency == "auto":
        currency = "cop" if amount >= 10_000 else "usd"

    lines = [
        "🧮 <b>CALCULADORA DE DIVISAS Y CRIPTO</b> 🇨🇴",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if currency in ("usd", "dolar", "dolares", "usdt"):
        cop_trm = amount * trm_rate
        cop_spot = amount * usd_spot
        cop_venta = amount * usd_venta
        eur_eq = (cop_spot / eur_spot) if eur_spot else 0.0
        lines.extend([
            f"💵 <b>Monto base:</b> <code>${amount:,.2f} USD</code>",
            "",
            f"🏛️ <b>A TRM Oficial (${trm_rate:,.2f}):</b>\n└ <code>{_format_cop(cop_trm)}</code>",
            f"💹 <b>A Dólar Mercado (${usd_spot:,.2f}):</b>\n└ <code>{_format_cop(cop_spot)}</code>",
            f"💳 <b>Precio Venta / Casas (${usd_venta:,.2f}):</b>\n└ <code>{_format_cop(cop_venta)}</code>",
            f"💶 <b>Equivalente en Euros:</b> <code>€{eur_eq:,.2f} EUR</code>",
        ])
    elif currency in ("cop", "pesos", "peso", "col"):
        usd_at_trm = amount / trm_rate if trm_rate else 0.0
        usd_at_spot = amount / usd_spot if usd_spot else 0.0
        eur_at_spot = amount / eur_spot if eur_spot else 0.0
        sats = (usd_at_spot / btc_usd) * 100_000_000 if btc_usd else 0.0
        lines.extend([
            f"🇨🇴 <b>Monto base:</b> <code>{_format_cop(amount)}</code>",
            "",
            f"🏛️ <b>En Dólares (TRM Oficial):</b> <code>${usd_at_trm:,.2f} USD</code>",
            f"💹 <b>En Dólares (Mercado):</b> <code>${usd_at_spot:,.2f} USD</code>",
            f"💶 <b>En Euros (Promedio):</b> <code>€{eur_at_spot:,.2f} EUR</code>",
            f"🟠 <b>En Bitcoin:</b> <code>{sats:,.0f} sats ({usd_at_spot / btc_usd:.6f} BTC)</code>",
        ])
    elif currency in ("eur", "euro", "euros"):
        cop_eur = amount * eur_spot
        cop_eur_venta = amount * eur_venta
        usd_eq = cop_eur / usd_spot if usd_spot else 0.0
        lines.extend([
            f"💶 <b>Monto base:</b> <code>€{amount:,.2f} EUR</code>",
            "",
            f"💹 <b>En Pesos (Promedio ${eur_spot:,.2f}):</b>\n└ <code>{_format_cop(cop_eur)}</code>",
            f"🔴 <b>En Pesos (Venta ${eur_venta:,.2f}):</b>\n└ <code>{_format_cop(cop_eur_venta)}</code>",
            f"💵 <b>Equivalente en Dólares:</b> <code>${usd_eq:,.2f} USD</code>",
        ])
    elif currency in ("btc", "bitcoin"):
        usd_val = amount * btc_usd
        cop_val = usd_val * usd_spot
        lines.extend([
            f"🟠 <b>Monto base:</b> <code>{amount:g} BTC</code>",
            "",
            f"🇺🇸 <b>En Dólares:</b> <code>${usd_val:,.2f} USD</code>",
            f"🇨🇴 <b>En Pesos Colombianos:</b>\n└ <code>{_format_cop(cop_val)}</code>",
        ])
    elif currency in ("eth", "ethereum"):
        usd_val = amount * eth_usd
        cop_val = usd_val * usd_spot
        lines.extend([
            f"🔷 <b>Monto base:</b> <code>{amount:g} ETH</code>",
            "",
            f"🇺🇸 <b>En Dólares:</b> <code>${usd_val:,.2f} USD</code>",
            f"🇨🇴 <b>En Pesos Colombianos:</b>\n└ <code>{_format_cop(cop_val)}</code>",
        ])
    else:
        raise ValueError(f"Moneda no soportada: {currency}")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        "💡 <i>Formatos: <code>/trm 100 usd</code> │ <code>/trm 500000 cop</code> │ <code>/trm 50 eur</code> │ <code>/trm 0.1 btc</code></i>",
    ])
    return "\n".join(lines), build_trm_markup(active_tab="usd")


def google_trm(force_refresh: bool = False) -> str:
    """
    Obtiene la TRM Oficial de Colombia y la cotización actual del dólar (USD/COP),
    devolviendo un mensaje enriquecido en formato HTML para Telegram.
    """
    now = time.time()
    with _trm_lock:
        if (
            not force_refresh
            and _rates_cache["data"] is not None
            and (now - float(_rates_cache["timestamp"])) < TRM_CACHE_TTL
        ):
            return _format_usd_tab(_rates_cache["data"])  # type: ignore[arg-type]

    try:
        data = _fetch_dolarapi()
        with _trm_lock:
            _rates_cache["data"] = data
            _rates_cache["timestamp"] = now
        return _format_usd_tab(data)
    except Exception as e:
        logger.warning("Fallo DolarAPI, usando fallback: %s", e)
        return _fallback_google_or_er()
