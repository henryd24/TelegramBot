from datetime import datetime, timedelta, timezone
import html
import json
import os
import socket
import sqlite3
import ssl
from threading import Lock, Thread
import time
from urllib.parse import unquote, urlparse
# pyrefly: ignore [missing-import]
from telebot.types import InlineKeyboardButton, InlineKeyboardMarkup

from .logger import setup_logging

logger = setup_logging(__name__)

COLOMBIA_TZ = timezone(timedelta(hours=-5))
REMINDER_MINUTES_BEFORE = 10
REDIS_HASH_KEY = "telegrambot:match_alerts"


def _serialize_alert(alert: dict) -> str:
    payload = dict(alert)
    payload["start_dt"] = alert["start_dt"].isoformat()
    payload["notify_at"] = alert["notify_at"].isoformat()
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_alert(raw_json: str | bytes) -> dict:
    if isinstance(raw_json, bytes):
        raw_json = raw_json.decode("utf-8", errors="replace")
    data = json.loads(raw_json)
    data["start_dt"] = datetime.fromisoformat(data["start_dt"]).astimezone(COLOMBIA_TZ)
    data["notify_at"] = datetime.fromisoformat(data["notify_at"]).astimezone(COLOMBIA_TZ)
    data["chat_id"] = int(data["chat_id"])
    data["game_id"] = str(data["game_id"])
    return data


# ==============================================================================
# CLIENTE REDIS NATIVO (RESP2) + STORE EXTERNO (NO LEVANTA DB LOCAL)
# ==============================================================================
class _RedisAlertStore:
    """
    Almacenamiento persistente en un servidor Redis externo (ej. StatefulSet en K8s).
    Implementa protocolo RESP2 sobre socket estándar para no requerir compilación ni
    dependencias adicionales en python:3.12-alpine, con reconexión automática.
    """

    def __init__(self, redis_url: str) -> None:
        self.redis_url = redis_url.strip()
        if "://" not in self.redis_url:
            self.redis_url = f"redis://{self.redis_url}"

        parsed = urlparse(self.redis_url)
        self.use_tls = parsed.scheme == "rediss"
        self.host = parsed.hostname or "localhost"
        self.port = parsed.port or 6379
        self.username = unquote(parsed.username) if parsed.username else None
        self.password = unquote(parsed.password) if parsed.password else os.getenv("REDIS_PASSWORD")
        path_db = (parsed.path or "").lstrip("/")
        self.db = int(path_db) if path_db.isdigit() else int(os.getenv("REDIS_DB", "0"))

        self._lock = Lock()
        self._sock: socket.socket | None = None
        self._file = None
        self.backend_label = "🟢 Redis Externo (Persistente)"

    def _connect(self) -> None:
        self._close()
        raw_sock = socket.create_connection((self.host, self.port), timeout=5.0)
        if self.use_tls:
            ctx = ssl.create_default_context()
            raw_sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)
        self._sock = raw_sock
        self._file = raw_sock.makefile("rb")

        if self.password:
            if self.username:
                self._send_cmd("AUTH", self.username, self.password)
            else:
                self._send_cmd("AUTH", self.password)
        if self.db != 0:
            self._send_cmd("SELECT", str(self.db))

    def _close(self) -> None:
        try:
            if self._file:
                self._file.close()
        except Exception:
            pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._file = None
        self._sock = None

    def _send_cmd(self, *args: str) -> object:
        if self._sock is None or self._file is None:
            self._connect()

        parts = [f"*{len(args)}\r\n".encode("utf-8")]
        for arg in args:
            encoded = str(arg).encode("utf-8")
            parts.append(f"${len(encoded)}\r\n".encode("utf-8"))
            parts.append(encoded + b"\r\n")
        payload = b"".join(parts)

        assert self._sock is not None
        self._sock.sendall(payload)
        return self._read_resp()

    def _read_resp(self) -> object:
        assert self._file is not None
        line = self._file.readline()
        if not line:
            raise ConnectionError("Conexión cerrada por Redis")

        prefix = line[:1]
        body = line[1:-2]

        if prefix == b"+":
            return body.decode("utf-8", errors="replace")
        if prefix == b"-":
            raise RuntimeError(f"Error de Redis: {body.decode('utf-8', errors='replace')}")
        if prefix == b":":
            return int(body)
        if prefix == b"$":
            length = int(body)
            if length == -1:
                return None
            data = self._file.read(length)
            self._file.read(2)  # CRLF
            return data.decode("utf-8", errors="replace")
        if prefix == b"*":
            count = int(body)
            if count == -1:
                return None
            return [self._read_resp() for _ in range(count)]
        raise RuntimeError(f"Respuesta RESP desconocida: {line!r}")

    def execute(self, *args: str) -> object:
        with self._lock:
            for attempt in range(2):
                try:
                    return self._send_cmd(*args)
                except Exception as e:
                    self._close()
                    if attempt == 1:
                        raise e

    def ping(self) -> bool:
        return self.execute("PING") == "PONG"

    def exists(self, key: str) -> bool:
        return bool(self.execute("HEXISTS", REDIS_HASH_KEY, key))

    def put(self, key: str, alert: dict) -> None:
        self.execute("HSET", REDIS_HASH_KEY, key, _serialize_alert(alert))

    def delete(self, key: str) -> bool:
        removed = self.execute("HDEL", REDIS_HASH_KEY, key)
        return bool(removed and int(removed) > 0)

    def list_all(self) -> dict[str, dict]:
        raw_list = self.execute("HGETALL", REDIS_HASH_KEY)
        if not isinstance(raw_list, list):
            return {}
        result: dict[str, dict] = {}
        for i in range(0, len(raw_list), 2):
            k = str(raw_list[i])
            v = raw_list[i + 1]
            try:
                result[k] = _deserialize_alert(v)
            except Exception as e:
                logger.warning("Error deserializando alerta %s desde Redis: %s", k, e)
        return result


# ==============================================================================
# BASE DE DATOS LOCAL SQLITE EN MEMORIA (CUANDO NO SE DEFINE REDIS EXTERNO)
# ==============================================================================
class _LocalSqliteAlertStore:
    """
    Base de datos local ligera basada en SQLite en memoria (:memory:).
    Solo se instancia cuando NO se configura REDIS_URL / REDIS_HOST externo,
    ideal para pruebas locales o ejecución efímera mientras el pod vive.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS match_alerts (
                    alert_key TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )
        self.backend_label = "🟡 DB Local en Memoria (Modo Efímero)"

    def exists(self, key: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM match_alerts WHERE alert_key = ? LIMIT 1",
                (key,),
            )
            return cur.fetchone() is not None

    def put(self, key: str, alert: dict) -> None:
        with self._lock:
            with self._conn:
                self._conn.execute(
                    """
                    INSERT OR REPLACE INTO match_alerts (alert_key, chat_id, payload)
                    VALUES (?, ?, ?)
                    """,
                    (key, int(alert["chat_id"]), _serialize_alert(alert)),
                )

    def delete(self, key: str) -> bool:
        with self._lock:
            with self._conn:
                cur = self._conn.execute(
                    "DELETE FROM match_alerts WHERE alert_key = ?",
                    (key,),
                )
                return cur.rowcount > 0

    def list_all(self) -> dict[str, dict]:
        with self._lock:
            cur = self._conn.execute("SELECT alert_key, payload FROM match_alerts")
            rows = cur.fetchall()
        result: dict[str, dict] = {}
        for k, raw in rows:
            try:
                result[str(k)] = _deserialize_alert(raw)
            except Exception as e:
                logger.warning("Error deserializando alerta local %s: %s", k, e)
        return result


_store: _RedisAlertStore | _LocalSqliteAlertStore | None = None
_store_init_lock = Lock()
_worker_started = False


def init_alert_store(redis_url: str | None = None) -> _RedisAlertStore | _LocalSqliteAlertStore:
    """
    Inicializa el motor de almacenamiento de recordatorios:
      - Si se provee `redis_url` o existen las variables `REDIS_URL` / `REDIS_HOST`,
        se conecta al Redis externo y NO levanta base de datos local.
      - Si no se define variable de Redis externo, levanta automáticamente una DB
        SQLite local en memoria mientras el proceso/pod vive.
    """
    global _store
    with _store_init_lock:
        configured_url = (
            redis_url
            or os.getenv("REDIS_URL", "").strip()
            or os.getenv("REDIS_HOST", "").strip()
        )
        if configured_url:
            if not configured_url.startswith(("redis://", "rediss://")):
                port = os.getenv("REDIS_PORT", "6379").strip()
                db = os.getenv("REDIS_DB", "0").strip()
                configured_url = f"redis://{configured_url}:{port}/{db}"

            logger.info("Configurando almacenamiento de alertas en Redis externo: %s", configured_url)
            redis_store = _RedisAlertStore(configured_url)
            try:
                if redis_store.ping():
                    logger.info("Conectado exitosamente a Redis externo para alertas")
            except Exception as e:
                logger.warning(
                    "Redis externo configurado (%s) aún no responde al PING inicial (se reconectará al usar): %s",
                    configured_url,
                    e,
                )
            _store = redis_store
            return _store

        logger.info(
            "No se detectó REDIS_URL externo; iniciando DB SQLite local en memoria para alertas"
        )
        _store = _LocalSqliteAlertStore()
        return _store


def _get_store() -> _RedisAlertStore | _LocalSqliteAlertStore:
    global _store
    if _store is None:
        return init_alert_store()
    return _store


# ==============================================================================
# API PÚBLICA DE RECORDATORIOS DE PARTIDOS
# ==============================================================================
def schedule_match_alert(
    chat_id: int,
    game: dict,
    user_label: str = "Usuario",
) -> tuple[bool, str]:
    """
    Programa un recordatorio 10 minutos antes del inicio del partido para el chat_id indicado.
    Devuelve (creado_nuevo, mensaje_toast).
    """
    store = _get_store()
    now_col = datetime.now(COLOMBIA_TZ)
    start_dt: datetime = game["start_dt"]
    game_id = str(game.get("game_id", ""))
    key = f"{chat_id}:{game_id}"

    if start_dt <= now_col:
        return False, "⚠️ Este partido ya comenzó o finalizó."

    notify_at = start_dt - timedelta(minutes=REMINDER_MINUTES_BEFORE)
    if notify_at <= now_col:
        notify_at = now_col + timedelta(seconds=10)

    if store.exists(key):
        return False, "🔔 Ya existe un recordatorio activo para este partido."

    alert_obj = {
        "key": key,
        "chat_id": int(chat_id),
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
    store.put(key, alert_obj)

    mins_left = max(1, int((start_dt - now_col).total_seconds() // 60))
    return (
        True,
        f"🔔 Alerta activada: {game['home']} vs {game['away']} (faltan {mins_left}m)",
    )


def cancel_match_alert(chat_id: int, game_id: str) -> bool:
    """Cancela un recordatorio programado en el chat."""
    store = _get_store()
    key = f"{chat_id}:{game_id}"
    return store.delete(key)


def get_chat_alerts(chat_id: int) -> list[dict]:
    """Devuelve las alertas activas para un chat ordenadas por hora."""
    store = _get_store()
    now_col = datetime.now(COLOMBIA_TZ)
    all_alerts = store.list_all()

    items: list[dict] = []
    for key, alert in all_alerts.items():
        if alert["start_dt"] <= now_col:
            # Limpiar silenciosamente partidos viejos
            try:
                store.delete(key)
            except Exception:
                pass
            continue
        if int(alert["chat_id"]) == int(chat_id):
            items.append(alert)

    items.sort(key=lambda x: x["start_dt"])
    return items


def build_alerts_message(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Construye el mensaje HTML y teclado para gestionar las alertas activas del chat."""
    store = _get_store()
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
            "├ 1. Abre /matches o /tmatches y toca <b>🔔 Recordar</b>",
            "└ 2. O busca un equipo con <code>/matches millonarios</code> y toca su campana 🔔",
            "━━━━━━━━━━━━━━━━━━━━━━",
            f"🗄️ <i>Almacenamiento: {store.backend_label}</i>",
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

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━━━",
        f"🗄️ <i>Almacenamiento: {store.backend_label}</i>",
    ])

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


def start_alert_worker(bot, redis_url: str | None = None) -> None:
    """Inicia el hilo demonio en segundo plano que dispara los recordatorios programados."""
    global _worker_started
    store = init_alert_store(redis_url=redis_url)

    with _store_init_lock:
        if _worker_started:
            return
        _worker_started = True

    def _loop():
        while True:
            try:
                now_col = datetime.now(COLOMBIA_TZ)
                all_alerts = store.list_all()
                due_alerts: list[dict] = []

                for k, a in all_alerts.items():
                    if now_col >= a["notify_at"]:
                        due_alerts.append(a)
                        store.delete(k)

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
    logger.info("Hilo de recordatorios iniciado (%s)", store.backend_label)
