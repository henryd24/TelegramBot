from datetime import datetime, timezone, timedelta
import html
import time
from threading import Lock
import requests

from .tables import get_shared_fetcher
from .logger import setup_logging

DOLARAPI_TRM_URL = "https://co.dolarapi.com/v1/trm"
DOLARAPI_USD_URL = "https://co.dolarapi.com/v1/cotizaciones/usd"
ER_API_USD_URL = "https://open.er-api.com/v6/latest/USD"
GOOGLE_FINANCE_URL = "https://www.google.com/finance/quote/USD-COP"

logger = setup_logging(__name__)

_http_session = requests.Session()
_http_session.headers.update({
    "User-Agent": "Mozilla/5.0 (compatible; CaguanTelegramBot/2.0)",
    "Accept": "application/json",
})

_trm_cache: dict[str, object] = {"data": None, "timestamp": 0.0}
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


def _fetch_dolarapi() -> dict:
    """Consulta DolarAPI Colombia (TRM oficial + cotización de mercado USD/COP)."""
    trm_data = {}
    usd_data = {}

    try:
        resp_trm = _http_session.get(DOLARAPI_TRM_URL, timeout=6)
        if resp_trm.ok:
            trm_data = resp_trm.json()
    except Exception as e:
        logger.warning("Error consultando TRM en DolarAPI: %s", e)

    try:
        resp_usd = _http_session.get(DOLARAPI_USD_URL, timeout=6)
        if resp_usd.ok:
            usd_data = resp_usd.json()
    except Exception as e:
        logger.warning("Error consultando USD spot en DolarAPI: %s", e)

    if not trm_data and not usd_data:
        raise RuntimeError("No se obtuvo respuesta de DolarAPI Colombia")

    return {"trm": trm_data, "usd": usd_data}


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

    fetcher = get_shared_fetcher(adaptive=False)
    page = fetcher.get(GOOGLE_FINANCE_URL)
    stock_name = html.escape(node_text(page.css(".JV7gl")) or "USD / COP")
    current_price = html.escape(node_text(page.css(".Pdsbrc")) or "N/D")
    previous_closing = html.escape(node_text(page.css(".u77W5d")) or "N/D")

    return (
        f"💵 <b>TASA DE CAMBIO ({stock_name})</b> 🇨🇴\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Valor Actual:</b> <code>{current_price}</code>\n"
        f"📉 <b>Cierre Anterior:</b> <code>{previous_closing}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🕒 <i>Fuente: Google Finance</i>"
    )


def google_trm(force_refresh: bool = False) -> str:
    """
    Obtiene la TRM Oficial de Colombia y la cotización actual del dólar (USD/COP),
    devolviendo un mensaje enriquecido en formato HTML para Telegram.

    Returns:
        str: Mensaje HTML con TRM oficial, dólar de mercado, cierre anterior y variación.
    """
    now = time.time()
    with _trm_lock:
        if (
            not force_refresh
            and _trm_cache["data"] is not None
            and (now - float(_trm_cache["timestamp"])) < TRM_CACHE_TTL
        ):
            return str(_trm_cache["data"])

    try:
        data = _fetch_dolarapi()
        trm_info = data.get("trm") or {}
        usd_info = data.get("usd") or {}

        trm_val = trm_info.get("valor")
        compra = usd_info.get("compra")
        venta = usd_info.get("venta")
        cierre = usd_info.get("ultimoCierre")
        fecha_act = usd_info.get("fechaActualizacion") or trm_info.get("fechaActualizacion")

        # Calcular promedio spot si hay compra y venta
        spot_actual = None
        if compra is not None and venta is not None:
            spot_actual = (float(compra) + float(venta)) / 2.0
        elif venta is not None:
            spot_actual = float(venta)
        elif compra is not None:
            spot_actual = float(compra)

        # Calcular variación respecto al cierre anterior
        variacion_line = ""
        if spot_actual is not None and cierre:
            diff = spot_actual - float(cierre)
            pct = (diff / float(cierre)) * 100.0 if float(cierre) else 0.0
            if diff > 0.01:
                trend_emoji = "📈"
                sign = "+"
            elif diff < -0.01:
                trend_emoji = "📉"
                sign = ""
            else:
                trend_emoji = "➖"
                sign = ""
            variacion_line = (
                f"{trend_emoji} <b>Variación hoy:</b> "
                f"<code>{sign}${diff:,.2f} ({sign}{pct:.2f}%)</code>\n"
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
            lines.append(variacion_line.rstrip())

        lines.extend([
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🕒 <i>Actualizado: {_format_iso_to_colombia(fecha_act)} (Hora COL)</i>",
        ])

        msg = "\n".join(lines)

    except Exception as e:
        logger.warning("Fallo DolarAPI, usando fallback: %s", e)
        msg = _fallback_google_or_er()

    with _trm_lock:
        _trm_cache["data"] = msg
        _trm_cache["timestamp"] = now

    return msg

