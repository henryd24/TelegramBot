import argparse
from datetime import datetime
import os
import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.logger import setup_logging
from src.money import google_trm
from src.nrandom import most_common_number
from src.tables import build_matches_message, xbox_games_view

parser = argparse.ArgumentParser(description="Telegram Bot for Caguan Group")
parser.add_argument("-t", "--token", help="Token to connect in telegram", required=False)
args = vars(parser.parse_args())

logger = setup_logging("TelegramBot")

# =================================== Init Config =====================================================
if args["token"] is not None:
    TOKEN = args["token"]
else:
    TOKEN = os.getenv("TOKEN")
    if TOKEN is None:
        print("Please set TOKEN parameter or TOKEN environment variable")
        raise SystemError("TOKEN environment variable not set")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")


def _build_welcome_markup() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚽ Partidos de Hoy", callback_data="nav|matches|0"),
        InlineKeyboardButton("📆 Partidos Mañana", callback_data="nav|matches|1"),
        InlineKeyboardButton("💵 Consultar TRM", callback_data="nav|trm"),
        InlineKeyboardButton("🎮 Lanzamientos Xbox", callback_data="nav|upgames"),
    )
    return markup


def _build_trm_markup() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("🔄 Actualizar TRM / Dólar", callback_data="trm|refresh")
    )
    return markup


def _safe_edit_message(
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> bool:
    """Edita un mensaje evitando excepciones si el contenido no cambió."""
    try:
        bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
        return True
    except ApiTelegramException as e:
        if "message is not modified" in str(e).lower():
            return False
        raise


# =================================== Telegram Handlers ================================================
@bot.message_handler(commands=["start", "help"])
def send_welcome(message) -> None:
    welcome_text = (
        "👋 <b>¡Qué se dice, Caguaneros!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Bienvenido al bot del grupo. Aquí tienes los comandos disponibles:\n\n"
        "⚽ <b>Fútbol en Vivo y TV (Colombia)</b>\n"
        "├ /matches — Agenda interactiva de partidos de <b>hoy</b>\n"
        "└ /tmatches — Agenda interactiva de partidos de <b>mañana</b>\n\n"
        "💵 <b>Economía y Divisas</b>\n"
        "└ /trm — TRM oficial y dólar spot en tiempo real\n\n"
        "🎮 <b>Videojuegos</b>\n"
        "└ /upgames — Próximos lanzamientos de <b>Xbox Series X|S</b>\n\n"
        "🎲 <b>Utilidades</b>\n"
        "└ <code>/random 1 100</code> — Número aleatorio más frecuente\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>También puedes usar los accesos rápidos de abajo:</i>"
    )
    bot.reply_to(message, welcome_text, reply_markup=_build_welcome_markup())


@bot.message_handler(commands=["trm"])
def trm(message) -> None:
    try:
        logger.info("Consultando TRM / USD-COP")
        msg = google_trm()
        bot.reply_to(message, msg, reply_markup=_build_trm_markup())
        logger.info("TRM enviada con éxito")
    except Exception:
        bot.reply_to(
            message,
            "⚠️ <b>No se pudo consultar la TRM en este momento.</b>\n"
            "<i>Inténtalo nuevamente en unos segundos.</i>",
        )
        logger.error("Error obteniendo TRM", exc_info=True)


@bot.message_handler(commands=["upgames"])
def upcoming_releases(message) -> None:
    try:
        logger.info("Consultando próximos lanzamientos de Xbox")
        text, markup = xbox_games_view(page=0)
        bot.reply_to(message, text, reply_markup=markup)
        logger.info("Lanzamientos de Xbox enviados")
    except Exception:
        bot.reply_to(
            message,
            "⚠️ <b>No se pudo cargar la lista de juegos de Xbox.</b>\n"
            "<i>Inténtalo de nuevo más tarde.</i>",
        )
        logger.error("Error obteniendo juegos de Xbox", exc_info=True)


@bot.message_handler(commands=["matches", "tmatches"])
def sending_matches(message) -> None:
    try:
        cmd_text = (message.text or "").split()[0].lower()
        position = 1 if "tmatches" in cmd_text else 0
        logger.info("Consultando partidos (position=%s)", position)

        text, markup = build_matches_message(
            position=position,
            mode="auto",
            comp_id="0",
            page=0,
        )
        bot.reply_to(message, text, reply_markup=markup)
        logger.info("Partidos enviados con éxito (position=%s)", position)
    except Exception:
        bot.reply_to(
            message,
            "⚠️ <b>No se pudieron obtener los partidos en este momento.</b>\n"
            "<i>Por favor intenta de nuevo en unos segundos.</i>",
        )
        logger.error("Error enviando partidos", exc_info=True)


def _format_random_response(
    start: int,
    end: int,
    repetitions: int = 100,
) -> tuple[str, InlineKeyboardMarkup]:
    low, high = (start, end) if start <= end else (end, start)
    reps = max(1, min(int(repetitions), 100_000))
    number, count = most_common_number(low, high, repetitions=reps)
    pct = (count / reps) * 100.0

    text = (
        "🎲 <b>SORTEO ALEATORIO</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Número ganador:</b> <code>{number}</code>\n"
        f"🔁 <b>Frecuencia:</b> <code>{count}</code> apariciones <i>({pct:.1f}%)</i>\n"
        f"<blockquote>📏 <b>Rango:</b> [{low:,} – {high:,}] │ 🧪 <b>Tiradas:</b> {reps:,}</blockquote>"
    )
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton(
            "🎲 Volver a lanzar",
            callback_data=f"rnd|{low}|{high}|{reps}",
        )
    )
    return text, markup


@bot.message_handler(commands=["random"])
def random_number(message) -> None:
    try:
        logger.info("Se solicitó un número aleatorio")
        parts = (message.text or "").split()[1:]
        if len(parts) < 2 or len(parts) > 3:
            bot.reply_to(
                message,
                "⚠️ <b>Formato incorrecto</b>\n"
                "Usa: <code>/random &lt;inicio&gt; &lt;fin&gt; [repeticiones]</code>\n"
                "Ejemplo: <code>/random 1 50</code>",
            )
            return

        try:
            start = int(parts[0])
            end = int(parts[1])
            repetitions = int(parts[2]) if len(parts) == 3 else 100
        except ValueError:
            bot.reply_to(
                message,
                "⚠️ <b>Los valores deben ser números enteros.</b>\n"
                "Ejemplo: <code>/random 1 100</code>",
            )
            return

        msg, markup = _format_random_response(start, end, repetitions=repetitions)
        bot.reply_to(message, msg, reply_markup=markup)
        logger.info("Número aleatorio enviado con éxito")
    except Exception:
        bot.reply_to(
            message,
            "⚠️ <b>Ocurrió un error al generar el número.</b> Inténtalo de nuevo.",
        )
        logger.error("Ocurrió una excepción en /random", exc_info=True)


@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call) -> None:
    data = call.data or ""
    chat_id = call.message.chat.id
    message_id = call.message.message_id

    try:
        # 1. Botones de partidos: m|{pos}|{mode}|{comp_id}|{page}|{refresh}
        if data.startswith("m|"):
            if data == "m|noop":
                bot.answer_callback_query(call.id, "📄 Indicador de página actual")
                return

            parts = data.split("|")
            pos = int(parts[1]) if len(parts) > 1 else 0
            mode = parts[2] if len(parts) > 2 else "auto"
            comp_id = parts[3] if len(parts) > 3 else "0"
            page = int(parts[4]) if len(parts) > 4 else 0
            force_refresh = (parts[5] == "1") if len(parts) > 5 else False

            text, markup = build_matches_message(
                position=pos,
                mode=mode,
                comp_id=comp_id,
                page=page,
                force_refresh=force_refresh,
            )
            changed = _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
            if force_refresh:
                bot.answer_callback_query(call.id, "✅ Agenda actualizada")
            elif not changed:
                bot.answer_callback_query(call.id, "Ya estás en esta vista")
            else:
                bot.answer_callback_query(call.id)
            return

        # 2. Botones de Xbox: x|{page}|{refresh}
        if data.startswith("x|"):
            if data == "x|noop":
                bot.answer_callback_query(call.id, "📄 Página actual")
                return

            parts = data.split("|")
            page = int(parts[1]) if len(parts) > 1 else 0
            force_refresh = (parts[2] == "1") if len(parts) > 2 else False

            text, markup = xbox_games_view(page=page, force_refresh=force_refresh)
            _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
            bot.answer_callback_query(
                call.id,
                "✅ Lista de Xbox actualizada" if force_refresh else None,
            )
            return

        # 3. Botón de actualizar TRM
        if data == "trm|refresh":
            msg = google_trm(force_refresh=True)
            _safe_edit_message(chat_id, message_id, msg, reply_markup=_build_trm_markup())
            bot.answer_callback_query(call.id, "✅ TRM actualizada")
            return

        # 4. Botón de volver a lanzar /random: rnd|{low}|{high}|{reps}
        if data.startswith("rnd|"):
            parts = data.split("|")
            low = int(parts[1])
            high = int(parts[2])
            reps = int(parts[3]) if len(parts) > 3 else 100
            msg, markup = _format_random_response(low, high, repetitions=reps)
            _safe_edit_message(chat_id, message_id, msg, reply_markup=markup)
            bot.answer_callback_query(call.id, "🎲 ¡Nuevo lanzamiento!")
            return

        # 5. Botones de acceso rápido desde /start o /help
        if data.startswith("nav|"):
            parts = data.split("|")
            target = parts[1] if len(parts) > 1 else ""
            bot.answer_callback_query(call.id)
            if target == "matches":
                pos = int(parts[2]) if len(parts) > 2 else 0
                text, markup = build_matches_message(position=pos, mode="auto")
                bot.send_message(chat_id, text, reply_markup=markup)
            elif target == "trm":
                bot.send_message(chat_id, google_trm(), reply_markup=_build_trm_markup())
            elif target == "upgames":
                text, markup = xbox_games_view(page=0)
                bot.send_message(chat_id, text, reply_markup=markup)
            return

        bot.answer_callback_query(call.id)
    except Exception:
        logger.error("Error procesando callback %r", data, exc_info=True)
        try:
            bot.answer_callback_query(
                call.id,
                "⚠️ Ocurrió un error al actualizar. Intenta de nuevo.",
                show_alert=False,
            )
        except Exception:
            pass


def main() -> None:
    try:
        logger.info("Iniciando Bot")
        logger.info("--------------------------------")
        bot.infinity_polling(skip_pending=True)
    except Exception:
        logger.error("Excepción crítica en el bot", exc_info=True)
    finally:
        logger.info("Finalizando Bot")
        logger.info("--------------------------------")


if __name__ == "__main__":
    logger.info(f'Fecha actual: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    main()
