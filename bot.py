import hashlib
import hmac
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from flask import Flask, jsonify, request
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ORIONTAP_DB", ROOT / "oriontap.sqlite3"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "").strip().lstrip("@")
MINI_APP_URL = os.environ.get("MINI_APP_URL", "").strip()
API_HOST = os.environ.get("API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("PORT", "8080"))
MAX_ENERGY = 500
ENERGY_REFILL_SECONDS = 60
TAP_POINTS = 1
DAILY_BONUS = 25
REFERRAL_BONUS = 50
LAGOS = ZoneInfo("Africa/Lagos")


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            username TEXT NOT NULL DEFAULT '',
            first_name TEXT NOT NULL DEFAULT '',
            points INTEGER NOT NULL DEFAULT 0 CHECK(points >= 0),
            energy INTEGER NOT NULL DEFAULT 500 CHECK(energy BETWEEN 0 AND 500),
            energy_updated_at INTEGER NOT NULL,
            streak INTEGER NOT NULL DEFAULT 0,
            last_daily_date TEXT,
            referred_by INTEGER REFERENCES players(user_id),
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS players_points_idx ON players(points DESC);
        CREATE TABLE IF NOT EXISTS referral_rewards (
            referred_user_id INTEGER PRIMARY KEY REFERENCES players(user_id),
            referrer_user_id INTEGER NOT NULL REFERENCES players(user_id),
            rewarded_at TEXT NOT NULL
        );
        """)


def _player_row(db, user_id):
    return db.execute("SELECT * FROM players WHERE user_id=?", (user_id,)).fetchone()


def _regenerate(row, now):
    elapsed = max(0, now - int(row["energy_updated_at"]))
    gained = elapsed // ENERGY_REFILL_SECONDS
    energy = min(MAX_ENERGY, int(row["energy"]) + gained)
    updated_at = int(row["energy_updated_at"]) + gained * ENERGY_REFILL_SECONDS
    if energy == MAX_ENERGY:
        updated_at = now
    return energy, updated_at


def get_player(user_id, username="", first_name="", referrer_id=None):
    now = int(time.time())
    now_iso = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        row = _player_row(db, user_id)
        if row is None:
            valid_referrer = referrer_id if referrer_id and referrer_id != user_id and _player_row(db, referrer_id) else None
            db.execute("""INSERT INTO players(user_id, username, first_name, energy_updated_at, referred_by, created_at)
                          VALUES(?,?,?,?,?,?)""", (user_id, username or "", first_name or "", now, valid_referrer, now_iso))
            if valid_referrer:
                db.execute("INSERT OR IGNORE INTO referral_rewards VALUES(?,?,?)", (user_id, valid_referrer, now_iso))
                if db.execute("SELECT changes()").fetchone()[0]:
                    db.execute("UPDATE players SET points=points+? WHERE user_id IN (?,?)", (REFERRAL_BONUS, valid_referrer, user_id))
            row = _player_row(db, user_id)
        elif username or first_name:
            db.execute("UPDATE players SET username=?, first_name=? WHERE user_id=?", (username or row["username"], first_name or row["first_name"], user_id))
            row = _player_row(db, user_id)
        energy, updated_at = _regenerate(row, now)
        db.execute("UPDATE players SET energy=?, energy_updated_at=? WHERE user_id=?", (energy, updated_at, user_id))
        row = _player_row(db, user_id)
        return dict(row)


def do_tap(user_id, username="", first_name=""):
    player = get_player(user_id, username, first_name)
    now = int(time.time())
    with connect() as db:
        row = _player_row(db, user_id)
        energy, updated_at = _regenerate(row, now)
        if energy < 1:
            db.execute("UPDATE players SET energy=?, energy_updated_at=? WHERE user_id=?", (energy, updated_at, user_id))
            return {"ok": False, "reason": "energy", "player": dict(_player_row(db, user_id))}
        db.execute("UPDATE players SET points=points+?, energy=?, energy_updated_at=? WHERE user_id=?", (TAP_POINTS, energy-1, now, user_id))
        return {"ok": True, "player": dict(_player_row(db, user_id))}


def claim_daily(user_id, username="", first_name=""):
    get_player(user_id, username, first_name)
    today = datetime.now(LAGOS).date()
    with connect() as db:
        row = _player_row(db, user_id)
        last = date.fromisoformat(row["last_daily_date"]) if row["last_daily_date"] else None
        if last == today:
            return {"claimed": False, "bonus": 0, "player": dict(row)}
        streak = row["streak"] + 1 if last == date.fromordinal(today.toordinal()-1) else 1
        db.execute("UPDATE players SET points=points+?, streak=?, last_daily_date=? WHERE user_id=?", (DAILY_BONUS, streak, today.isoformat(), user_id))
        return {"claimed": True, "bonus": DAILY_BONUS, "player": dict(_player_row(db, user_id))}


def leaderboard(limit=10):
    with connect() as db:
        rows = db.execute("SELECT user_id, username, first_name, points FROM players ORDER BY points DESC, user_id ASC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def validate_init_data(init_data, bot_token, max_age=86400):
    if not init_data or not bot_token:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
        supplied = pairs.pop("hash")
        auth_date = int(pairs["auth_date"])
        if abs(int(time.time()) - auth_date) > max_age:
            return None
        check = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret_key, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, supplied):
            return None
        user = json.loads(pairs["user"])
        return user if isinstance(user.get("id"), int) else None
    except (KeyError, ValueError, TypeError, json.JSONDecodeError):
        return None


api = Flask(__name__)


def authorized_user():
    if not BOT_TOKEN:
        return None
    return validate_init_data(request.headers.get("X-Telegram-Init-Data", ""), BOT_TOKEN)


def api_player(user):
    return get_player(user["id"], user.get("username", ""), user.get("first_name", ""))


@api.get("/api/health")
def health():
    return jsonify({"ok": True, "service": "oriontap", "database": "sqlite"})


@api.get("/api/me")
def me():
    user = authorized_user()
    if not user:
        return jsonify({"error": "Open this app inside Telegram after the bot is configured."}), 401
    row = api_player(user)
    return jsonify({"player": row, "referral_link": f"https://t.me/{BOT_USERNAME}?start=ref_{row['user_id']}" if BOT_USERNAME else None})


@api.post("/api/tap")
def tap_api():
    user = authorized_user()
    if not user:
        return jsonify({"error": "Telegram authentication required."}), 401
    result = do_tap(user["id"], user.get("username", ""), user.get("first_name", ""))
    return jsonify(result), (200 if result["ok"] else 409)


@api.post("/api/daily")
def daily_api():
    user = authorized_user()
    if not user:
        return jsonify({"error": "Telegram authentication required."}), 401
    return jsonify(claim_daily(user["id"], user.get("username", ""), user.get("first_name", "")))


@api.get("/api/leaderboard")
def leaderboard_api():
    return jsonify({"players": leaderboard(20)})


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    referrer = None
    if context.args and context.args[0].startswith("ref_"):
        try:
            referrer = int(context.args[0][4:])
        except ValueError:
            pass
    player = get_player(u.id, u.username or "", u.first_name or "", referrer)
    buttons = [[InlineKeyboardButton("⛏️ mine", callback_data="mine")], [InlineKeyboardButton("open OrionTap", web_app=WebAppInfo(url=MINI_APP_URL))]] if MINI_APP_URL.startswith("https://") else [[InlineKeyboardButton("⛏️ mine", callback_data="mine")]]
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref_{u.id}" if BOT_USERNAME else "set BOT_USERNAME to show your invite link"
    await update.message.reply_text(f"welcome to OrionTap, {u.first_name or 'miner'}!\n\npoints: {player['points']}\nenergy: {player['energy']}/{MAX_ENERGY}\n\nyour invite: {ref_link}\n\npoints only for now. no deposits or wallet connection.", reply_markup=InlineKeyboardMarkup(buttons))


async def mine_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    get_player(u.id, u.username or "", u.first_name or "")
    await update.message.reply_text("tap to mine. each tap uses 1 energy and earns 1 point. energy refills by 1 every 60 seconds, up to 500.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⛏️ tap", callback_data="mine")]]))


async def mine_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = q.from_user
    result = do_tap(u.id, u.username or "", u.first_name or "")
    p = result["player"]
    if result["ok"]:
        text = f"+{TAP_POINTS} point\npoints: {p['points']}\nenergy: {p['energy']}/{MAX_ENERGY}"
    else:
        text = f"no energy left. points: {p['points']}\nenergy refills by 1 each minute."
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⛏️ tap", callback_data="mine")]]))


async def balance_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    p = get_player(u.id, u.username or "", u.first_name or "")
    await update.message.reply_text(f"points: {p['points']}\nenergy: {p['energy']}/{MAX_ENERGY}\ndaily streak: {p['streak']} days")


async def daily_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    result = claim_daily(u.id, u.username or "", u.first_name or "")
    p = result["player"]
    if result["claimed"]:
        msg = f"daily bonus claimed: +{result['bonus']} points 🎉\nstreak: {p['streak']} days\ntotal: {p['points']} points"
    else:
        msg = f"today's bonus already claimed. streak: {p['streak']} days\npoints: {p['points']}"
    await update.message.reply_text(msg)


async def leaderboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = leaderboard(10)
    if not rows:
        await update.message.reply_text("leaderboard is empty so far. start mining to be first.")
        return
    lines = []
    for i, row in enumerate(rows, 1):
        name = ("@" + row["username"]) if row["username"] else (row["first_name"] or f"miner {row['user_id']}")
        lines.append(f"{i}. {name}: {row['points']} pts")
    await update.message.reply_text("🏆 OrionTap leaderboard\n" + "\n".join(lines))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OrionTap commands\n/start: create your profile and invite friends\n/mine: tap to earn points\n/balance: points, energy and streak\n/daily: claim your once-a-day streak bonus\n/leaderboard: top miners\n/help: show this message\n\npoints are not a token and have no guaranteed value. no purchase, deposit or wallet connection is needed.")


def run_api():
    api.run(host=API_HOST, port=API_PORT, threaded=True, use_reloader=False)


def main():
    init_db()
    if not BOT_TOKEN:
        raise SystemExit("BOT_TOKEN is missing. See README.md. The database/API can be tested without a token.")
    threading.Thread(target=run_api, daemon=True).start()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("mine", mine_cmd))
    app.add_handler(CommandHandler("balance", balance_cmd))
    app.add_handler(CommandHandler("daily", daily_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CallbackQueryHandler(mine_callback, pattern="^mine$"))
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
