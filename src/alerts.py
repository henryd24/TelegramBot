from datetime import datetime, timedelta, timezone
import html
from threading import Lock, Thread
import time
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from .logger import setup_logging

logger = setup_logging(__name__)

COLOMBIA_TZ = timezone(timedelta(hours=-5))
REMINDER_MINUTES_BEFORE = 10

_alerts: dict[str, dict] = {}
_alerts_lock = Lock()
_worker_started = False


def schedule_match_alert(
    chat_id: int,
    game: dict,
    user_label: str = "Usuario",
) -> tuple[bool, str]:
    """
    Programa un recordatorio 10 minutos antes del inicio del partido para el chat_id indicado.
    Devuelve (creado_nuevo, mensaje_toast).
    """
    now_col = datetime.now(COLOMBIA_TZ)
    start_dt: datetime = game["start_dt"]
    game_id = str(game.get("game_id", ""))
    key = f"{chat_id}:{game_id}"

    if start_dt <= now_col:
        return False, "⚠️ Este partido ya comenzó o finalizó."

    notify_at = start_dt - timedelta(minutes=REMINDER_MINUTES_BEFORE)
    # Si faltan menos de 10 minutos para el partido, avisar en 10 segundos
    if notify_at <= now_col:
        notify_at = now_col + timedelta(seconds=10)

    with _alerts_lock:
        if key in _alerts:
            return False, "🔔 Ya existe un recordatorio activo para este partido."

        _alerts[key] = {
            "key": key,
            "chat_id": chat_id,
            "game_id": game_id,
            "home": game["home"],
            "away": game["away"],
            "competition": game.get("competition", "Fútbol"),
            "time_str": game.get("time_str", ""),
            "start_dt": start_dt,
            "notify_at": notify_at,
            "channels": list(game.get("channels") or []),
            "user_label": user_label,
        }

    mins_left = max(1, int((start_dt - now_col).total_seconds() // 60))
    return (
        True,
        f"🔔 Alerta activada: {game['home']} vs {game['away']} (faltan {mins_left}m)",
    )


def cancel_match_alert(chat_id: int, game_id: str) -> bool:
    """Cancela un recordatorio programado en el chat."""
    key = f"{chat_id}:{game_id}"
    with _alerts_lock:
        if key in _alerts:
            del _alerts[key]
            return True
    return False


def get_chat_alerts(chat_id: int) -> list[dict]:
    """Devuelve las alertas activas para un chat ordenadas por hora."""
    now_col = datetime.now(COLOMBIA_TZ)
    with _alerts_lock:
        items = [
            a for a in _alerts.values()
            if a["chat_id"] == chat_id and a["start_dt"] > now_col
        ]
    items.sort(key=lambda x: x["start_dt"])
    return items


def build_alerts_message(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Construye el mensaje HTML y teclado para gestionar las alertas activas del chat."""
    items = get_chat_alerts(chat_id)
    now_col = datetime.now(COLOMBIA_TZ)

    lines = [
        "🔔 <b>RECORDATORIOS DE PARTIDOS ACTIVOS</b> ⚽",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    markup = InlineKeyboardMarkup()

    if not items:
        lines.extend([
            "🔕 <i>No hay recordatorios programados en este chat.</i>",
            "",
            "💡 <b>¿Cómo programar una alerta?</b>",
            "├ 1. Abre /matches o /tmatches y toca <b>🔔 Recordar partido</b>",
            "└ 2. O busca un equipo con <code>/matches millonarios</code> y toca su campana 🔔",
        ])
        markup.row(
            InlineKeyboardButton("⚽ Ver Partidos de Hoy", callback_data="m|0|auto|0|0|0"),
            InlineKeyboardButton("📆 Ver Mañana", callback_data="m|1|auto|0|0|0"),
        )
        return "\n".join(lines), markup

    lines.append(
        f"<blockquote>📌 Se enviará un aviso automático al chat <b>{REMINDER_MINUTES_BEFORE} minutos antes</b> de cada partido:</blockquote>\n"
    )

    for a in items:
        home_esc = html.escape(a["home"])
        away_esc = html.escape(a["away"])
        comp_esc = html.escape(a["competition"])
        time_esc = html.escape(a["time_str"])
        delta_mins = max(1, int((a["start_dt"] - now_col).total_seconds() // 60))
        hours, mins = divmod(delta_mins, 60)
        wait_str = f"{hours}h {mins}m" if hours > 0 else f"{mins}m"
        channels = a.get("channels") or []
        ch_str = (
            " • ".join(f"<code>{html.escape(c)}</code>" for c in channels[:3])
            if channels
            else "<i>TV por confirmar</i>"
        )

        lines.append(
            f"🏆 <b>{comp_esc}</b>\n"
            f"┌ ⚔️ <b>{home_esc}</b> vs <b>{away_esc}</b>\n"
            f"├ 🕒 <b>{time_esc}</b> <i>(Inicia en {wait_str})</i>\n"
            f"└ 📺 {ch_str}\n"
        )

        short_label = f"❌ Quitar: {a['home'][:11]} vs {a['away'][:11]}"
        markup.row(
            InlineKeyboardButton(
                short_label,
                callback_data=f"al|del|{a['game_id']}",
            )
        )

    markup.row(
        InlineKeyboardButton("⚽ Ir a Partidos", callback_data="m|0|auto|0|0|0"),
        InlineKeyboardButton("🔄 Actualizar", callback_data="al|list"),
    )
    return "\n".join(lines), markup


def format_triggered_alert(alert: dict) -> str:
    """Formatea el mensaje que se envía automáticamente al grupo cuando llega la hora."""
    home_esc = html.escape(alert["home"])
    away_esc = html.escape(alert["away"])
    comp_esc = html.escape(alert["competition"])
    time_esc = html.escape(alert["time_str"])
    user_esc = html.escape(alert.get("user_label", "Usuario"))
    channels = alert.get("channels") or []
    ch_str = (
        " • ".join(f"<code>{html.escape(c)}</code>" for c in channels[:4])
        if channels
        else "<i>Seguimiento en vivo</i>"
    )

    return (
        f"🔔 <b>¡EL PARTIDO COMIENZA EN {REMINDER_MINUTES_BEFORE} MINUTOS!</b> ⚽\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 <b>{comp_esc}</b>\n"
        f"⚔️ <b>{home_esc}</b> vs <b>{away_esc}</b>\n"
        f"🕒 <b>Hora:</b> {time_esc} (Hora COL)\n"
        f"📺 <b>Transmisión:</b> {ch_str}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <i>Recordatorio programado por {user_esc}</i>"
    )


def start_alert_worker(bot) -> None:
    """Inicia el hilo demonio en segundo plano que dispara los recordatorios programados."""
    global _worker_started
    with _alerts_lock:
        if _worker_started:
            return
        _worker_started = True

    def _loop():
        while True:
            try:
                now_col = datetime.now(COLOMBIA_TZ)
                due_alerts: list[dict] = []

                with _alerts_lock:
                    expired_keys = []
                    for k, a in _alerts.items():
                        if now_col >= a["notify_at"]:
                            due_alerts.append(a)
                            expired_keys.append(k)
                    for k in expired_keys:
                        del _alerts[k]

                for alert in due_alerts:
                    try:
                        msg = format_triggered_alert(alert)
                        bot.send_message(alert["chat_id"], msg, parse_mode="HTML")
                        logger.info(
                            "Alerta enviada a chat_id=%s para %s vs %s",
                            alert["chat_id"],
                            alert["home"],
                            alert["away"],
                        )
                    except Exception as e:
                        logger.error("Error enviando alerta de partido: %s", e)

            except Exception as e:
                logger.error("Error en ciclo de alertas: %s", e)

            time.sleep(15)

    worker = Thread(target=_loop, name="MatchAlertWorker", daemon=True)
    worker.start()
    logger.info("Hilo de recordatorios de partidos iniciado")
