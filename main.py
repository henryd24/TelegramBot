import argparse
from datetime import datetime
import os
import telebot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.alerts import (
    build_alerts_message,
    cancel_match_alert,
    schedule_match_alert,
    start_alert_worker,
)
from src.logger import setup_logging
from src.money import (
    build_trm_view,
    convert_currency_message,
)
from src.nrandom import most_common_number
from src.tables import (
    build_matches_message,
    build_standings_message,
    find_game_by_id,
    search_matches_message,
    xbox_games_view,
)

parser = argparse.ArgumentParser(description="Telegram Bot for Caguan Group")
parser.add_argument("-t", "--token", help="Token to connect in telegram", required=False)
parser.add_argument(
    "-r",
    "--redis-url",
    help="External Redis URL for alerts persistence (falls back to local DB if omitted)",
    required=False,
)
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

REDIS_URL = (args.get("redis_url") or os.getenv("REDIS_URL") or "").strip() or None

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

LEAGUE_ALIASES = {
    "betplay": "col.1",
    "colombia": "col.1",
    "dimayor": "col.1",
    "premier": "eng.1",
    "inglaterra": "eng.1",
    "laliga": "esp.1",
    "españa": "esp.1",
    "espana": "esp.1",
    "seriea": "ita.1",
    "italia": "ita.1",
    "bundesliga": "ger.1",
    "alemania": "ger.1",
    "ligue1": "fra.1",
    "francia": "fra.1",
    "champions": "uefa.champions",
    "libertadores": "conmebol.libertadores",
    "sudamericana": "conmebol.sudamericana",
    "argentina": "arg.1",
    "brasil": "bra.1",
}


def _build_welcome_markup() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("⚽ Partidos de Hoy", callback_data="nav|matches|0"),
        InlineKeyboardButton("📆 Partidos Mañana", callback_data="nav|matches|1"),
        InlineKeyboardButton("📊 Tabla Posiciones", callback_data="nav|standings"),
        InlineKeyboardButton("🔔 Mis Alertas", callback_data="nav|alerts"),
        InlineKeyboardButton("💵 Dólar / Euro / BTC", callback_data="nav|trm"),
        InlineKeyboardButton("🟢 Xbox & Game Pass", callback_data="nav|gamepass"),
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


def _user_display_name(user) -> str:
    if not user:
        return "Usuario"
    if getattr(user, "username", None):
        return f"@{user.username}"
    first = getattr(user, "first_name", "") or ""
    last = getattr(user, "last_name", "") or ""
    return f"{first} {last}".strip() or "Usuario"


# =================================== Telegram Handlers ================================================
@bot.message_handler(commands=["start", "help"])
def send_welcome(message) -> None:
    welcome_text = (
        "👋 <b>¡Qué se dice, Caguaneros!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Aquí tienes todos los comandos y herramientas del bot:\n\n"
        "⚽ <b>Fútbol en Vivo, TV y Posiciones</b>\n"
        "├ /matches — Agenda interactiva de <b>hoy</b>\n"
        "├ /tmatches — Agenda interactiva de <b>mañana</b>\n"
        "├ <code>/matches fc barcelona</code> — Buscar equipo o torneo\n"
        "├ /tabla — Tabla de posiciones (BetPlay, Premier, Champions…)\n"
        "├ /alertas — Recordatorios 10 min antes del partido 🔔\n\n"
        "💵 <b>Divisas, Conversor y Cripto</b>\n"
        "├ /trm — Dólar TRM, Mercado, Euro y Cripto\n"
        "├ <code>/trm 150</code> — Convertir USD/COP/EUR/BTC\n"
        "└ /euro │ /crypto — Acceso directo a Euro y Bitcoin\n\n"
        "🎮 <b>Gaming Xbox Series X|S</b>\n"
        "├ /upgames — Próximos lanzamientos de Xbox\n"
        "└ /gamepass — Juegos recién agregados a <b>Game Pass CO</b>\n\n"
        "🎲 <b>Utilidades</b>\n"
        "└ <code>/random 1 100</code> — Sorteo aleatorio estadístico\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 <i>Usa los botones rápidos para abrir cualquier sección:</i>"
    )
    bot.reply_to(message, welcome_text, reply_markup=_build_welcome_markup())


@bot.message_handler(commands=["trm", "euro", "crypto"])
def trm(message) -> None:
    try:
        parts = (message.text or "").split()
        cmd = parts[0].lower() if parts else "/trm"
        cmd_args = parts[1:]

        if "euro" in cmd and not cmd_args:
            text, markup = build_trm_view(tab="eur")
            bot.reply_to(message, text, reply_markup=markup)
            return

        if "crypto" in cmd and not cmd_args:
            text, markup = build_trm_view(tab="crypto")
            bot.reply_to(message, text, reply_markup=markup)
            return

        if cmd_args:
            logger.info("Convirtiendo divisas: %s", cmd_args)
            try:
                text, markup = convert_currency_message(cmd_args)
                bot.reply_to(message, text, reply_markup=markup)
                return
            except Exception:
                bot.reply_to(
                    message,
                    "⚠️ <b>Formato de conversión no válido.</b>\n"
                    "Ejemplos:\n"
                    "• <code>/trm 150</code> (150 USD a COP)\n"
                    "• <code>/trm 500000 cop</code> (COP a USD/EUR)\n"
                    "• <code>/trm 100 eur</code> (EUR a COP)\n"
                    "• <code>/trm 0.05 btc</code> (BTC a USD/COP)",
                )
                return

        logger.info("Consultando TRM / USD-COP")
        text, markup = build_trm_view(tab="usd")
        bot.reply_to(message, text, reply_markup=markup)
        logger.info("TRM enviada con éxito")
    except Exception:
        bot.reply_to(
            message,
            "⚠️ <b>No se pudo consultar la información cambiaria en este momento.</b>\n"
            "<i>Inténtalo nuevamente en unos segundos.</i>",
        )
        logger.error("Error obteniendo TRM", exc_info=True)


@bot.message_handler(commands=["upgames", "gamepass"])
def upcoming_releases(message) -> None:
    try:
        cmd = ((message.text or "").split()[0] or "").lower()
        mode = "gamepass" if "gamepass" in cmd else "releases"
        logger.info("Consultando sección Xbox (mode=%s)", mode)
        text, markup = xbox_games_view(page=0, mode=mode)
        bot.reply_to(message, text, reply_markup=markup)
        logger.info("Sección Xbox enviada")
    except Exception:
        bot.reply_to(
            message,
            "⚠️ <b>No se pudo cargar la información de Xbox.</b>\n"
            "<i>Inténtalo de nuevo más tarde.</i>",
        )
        logger.error("Error obteniendo juegos de Xbox", exc_info=True)


@bot.message_handler(commands=["matches", "tmatches"])
def sending_matches(message) -> None:
    try:
        parts = (message.text or "").split(maxsplit=1)
        cmd_text = parts[0].lower() if parts else "/matches"
        query = parts[1].strip() if len(parts) > 1 else ""

        if query:
            logger.info("Buscando partidos por criterio: %r", query)
            text, markup = search_matches_message(query)
            bot.reply_to(message, text, reply_markup=markup)
            return

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


@bot.message_handler(commands=["tabla", "posiciones"])
def standings_handler(message) -> None:
    try:
        parts = (message.text or "").split(maxsplit=1)
        arg = parts[1].strip().lower() if len(parts) > 1 else ""
        league_code = LEAGUE_ALIASES.get(arg, "col.1")
        logger.info("Consultando tabla de posiciones (%s)", league_code)
        text, markup = build_standings_message(league_code=league_code, page=0)
        bot.reply_to(message, text, reply_markup=markup)
    except Exception:
        bot.reply_to(
            message,
            "⚠️ <b>No se pudo obtener la tabla de posiciones.</b>",
        )
        logger.error("Error en /tabla", exc_info=True)


@bot.message_handler(commands=["alertas", "alerta"])
def alerts_handler(message) -> None:
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) > 1 and parts[1].strip():
            # Si escribe /alerta <equipo>, buscar el partido para que toque la campana
            text, markup = search_matches_message(parts[1].strip())
            bot.reply_to(message, text, reply_markup=markup)
            return

        text, markup = build_alerts_message(message.chat.id)
        bot.reply_to(message, text, reply_markup=markup)
    except Exception:
        bot.reply_to(message, "⚠️ <b>No se pudieron cargar las alertas.</b>")
        logger.error("Error en /alertas", exc_info=True)


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

        # 2. Botones de Tabla de Posiciones: st|{league_code}|{page}|{action}
        if data.startswith("st|"):
            if data == "st|noop":
                bot.answer_callback_query(call.id, "📄 Página actual")
                return

            parts = data.split("|")
            lcode = parts[1] if len(parts) > 1 else "col.1"
            page = int(parts[2]) if len(parts) > 2 else 0
            action = parts[3] if len(parts) > 3 else "0"
            picker = action == "pick"
            force_refresh = action == "1"

            text, markup = build_standings_message(
                league_code=lcode,
                page=page,
                picker=picker,
                force_refresh=force_refresh,
            )
            _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
            bot.answer_callback_query(
                call.id,
                "✅ Tabla actualizada" if force_refresh else None,
            )
            return

        # 3. Botones de Recordatorios / Alertas: al|{action}|...
        if data.startswith("al|"):
            parts = data.split("|")
            action = parts[1] if len(parts) > 1 else "list"

            if action == "set" and len(parts) >= 4:
                pos = int(parts[2])
                game_id = parts[3]
                game = find_game_by_id(pos, game_id)
                if not game:
                    bot.answer_callback_query(
                        call.id,
                        "⚠️ No se encontró el partido seleccionado.",
                        show_alert=True,
                    )
                    return

                user_lbl = _user_display_name(call.from_user)
                created, toast_msg = schedule_match_alert(chat_id, game, user_label=user_lbl)
                bot.answer_callback_query(call.id, toast_msg, show_alert=not created)
                text, markup = build_alerts_message(chat_id)
                _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
                return

            if action == "del" and len(parts) >= 3:
                game_id = parts[2]
                removed = cancel_match_alert(chat_id, game_id)
                bot.answer_callback_query(
                    call.id,
                    "🗑️ Recordatorio eliminado" if removed else "Ya no estaba activo",
                )
                text, markup = build_alerts_message(chat_id)
                _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
                return

            text, markup = build_alerts_message(chat_id)
            _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
            bot.answer_callback_query(call.id)
            return

        # 4. Botones de Xbox & Game Pass: x|{mode}|{page}|{refresh}
        if data.startswith("x|"):
            if data == "x|noop":
                bot.answer_callback_query(call.id, "📄 Página actual")
                return

            parts = data.split("|")
            if len(parts) == 3:
                mode = "releases"
                page = int(parts[1])
                force_refresh = parts[2] == "1"
            else:
                mode = parts[1] if len(parts) > 1 else "releases"
                page = int(parts[2]) if len(parts) > 2 else 0
                force_refresh = (parts[3] == "1") if len(parts) > 3 else False

            text, markup = xbox_games_view(
                page=page,
                force_refresh=force_refresh,
                mode=mode,
            )
            _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
            bot.answer_callback_query(
                call.id,
                "✅ Catálogo Xbox actualizado" if force_refresh else None,
            )
            return

        # 5. Botones de TRM / Euro / Cripto: trm|tab|{tab}|{refresh}
        if data.startswith("trm|"):
            parts = data.split("|")
            if len(parts) >= 3 and parts[1] == "tab":
                tab = parts[2]
                force_refresh = (parts[3] == "1") if len(parts) > 3 else False
            else:
                tab = "usd"
                force_refresh = True

            text, markup = build_trm_view(tab=tab, force_refresh=force_refresh)
            _safe_edit_message(chat_id, message_id, text, reply_markup=markup)
            bot.answer_callback_query(
                call.id,
                "✅ Cotización actualizada" if force_refresh else None,
            )
            return

        # 6. Botón de volver a lanzar /random: rnd|{low}|{high}|{reps}
        if data.startswith("rnd|"):
            parts = data.split("|")
            low = int(parts[1])
            high = int(parts[2])
            reps = int(parts[3]) if len(parts) > 3 else 100
            msg, markup = _format_random_response(low, high, repetitions=reps)
            _safe_edit_message(chat_id, message_id, msg, reply_markup=markup)
            bot.answer_callback_query(call.id, "🎲 ¡Nuevo lanzamiento!")
            return

        # 7. Botones de acceso rápido desde /start o /help
        if data.startswith("nav|"):
            parts = data.split("|")
            target = parts[1] if len(parts) > 1 else ""
            bot.answer_callback_query(call.id)
            if target == "matches":
                pos = int(parts[2]) if len(parts) > 2 else 0
                text, markup = build_matches_message(position=pos, mode="auto")
                bot.send_message(chat_id, text, reply_markup=markup)
            elif target == "standings":
                text, markup = build_standings_message(league_code="col.1", page=0)
                bot.send_message(chat_id, text, reply_markup=markup)
            elif target == "alerts":
                text, markup = build_alerts_message(chat_id)
                bot.send_message(chat_id, text, reply_markup=markup)
            elif target == "trm":
                text, markup = build_trm_view(tab="usd")
                bot.send_message(chat_id, text, reply_markup=markup)
            elif target in ("upgames", "gamepass"):
                mode = "gamepass" if target == "gamepass" else "releases"
                text, markup = xbox_games_view(page=0, mode=mode)
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
        start_alert_worker(bot, redis_url=REDIS_URL)
        bot.infinity_polling(skip_pending=True)
    except Exception:
        logger.error("Excepción crítica en el bot", exc_info=True)
    finally:
        logger.info("Finalizando Bot")
        logger.info("--------------------------------")


if __name__ == "__main__":
    logger.info(f'Fecha actual: {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    main()
