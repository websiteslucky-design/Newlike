#!/usr/bin/env python3
"""
Pure Telegram Bot + AutoLike Scheduler, Redeem System & Auto Token Refresh (Credit: Lucky)
Removed FastAPI/Uvicorn dependencies completely to run smoothly on Termux & Bot-Hosting.net.
"""

import asyncio
import binascii
import json
import logging
import os
import random
from datetime import datetime, timedelta, timezone

import aiohttp
import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
)
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# Protobuf modules support
import like_pb2
import uid_generator_pb2
import visit_count_pb2

# Logging setup
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# SSL warnings disable
try:
    import requests
    requests.packages.urllib3.disable_warnings()
except ImportError:
    pass

# ── CONFIGURATION & CONSTANTS ──────────────────────────────────────────────
BOT_TOKEN = "8563880931:AAEntIK6rgmSu17LeH1UAu0E7NoEINKsviw"
OWNER_ID = 8894581637
API_URL = "https://jwt-token-api-beta.vercel.app/token"
DATA_FILE = "bot_data.json"
TEMP_LOG_FILE = "autolike_temp_activity.json"
TIMEZONE_NAME = "Asia/Kolkata"  # IST

DEFAULT_AUTOLIKE_DAYS = 35
DEFAULT_DAILY_TIME = "04:10"
DEFAULT_MAX_SLOTS = 50
DEFAULT_ADMIN_QUOTA = 100
ADMIN_USERNAME = "@CODEXLUCKY"
DEFAULT_USER_LIKE_LIMIT = 20
TOKEN_REFRESH_HOURS = 4  # Har 4 ghante me auto token refresh

# Mandatory Group Links
MANDATORY_GROUP_LINK = "https://t.me/+9pESZ-6_ktw1MmE1"
FREE_PAID_GROUP_LINK = "https://t.me/+tRWorVn5_iAwZTA1"

# Updated Professional Plans Configuration (with bonus days included in total days)
DEFAULT_PLANS = {
    "1": {"price": 50, "likes": 2000, "days": 40},    # 35 days + 5 days bonus
    "2": {"price": 100, "likes": 4000, "days": 80},   # 70 days + 10 days bonus
    "3": {"price": 150, "likes": 6200, "days": 120},  # 100 days + 20 days bonus
    "4": {"price": 200, "likes": 9300, "days": 170}   # 140 days + 30 days bonus
}

# ── STORAGE LOAD & SAVE HELPERS ────────────────────────────────────────────
def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                d.setdefault("allowed_groups", [])
                d.setdefault("admins", [])
                d.setdefault("redeem_codes", {})
                d.setdefault("autolikes", {})
                d.setdefault("banned_uids", [])
                d.setdefault("user_last_like", {})
                d.setdefault("settings", {})
                d["settings"].setdefault("daily_time", DEFAULT_DAILY_TIME)
                d["settings"].setdefault("max_slots", DEFAULT_MAX_SLOTS)
                d["settings"].setdefault("notify_default", True)
                d["settings"].setdefault("user_like_limit", DEFAULT_USER_LIKE_LIMIT)
                d["settings"].setdefault("bot_maintenance", False)
                d["settings"].setdefault("autolike_group_id", None)
                d["settings"].setdefault("free_group_id", None)
                d.setdefault("plans", DEFAULT_PLANS)
                return d
        except Exception:
            pass
    return {
        "allowed_groups": [],
        "admins": [],
        "banned_uids": [],
        "user_last_like": {},
        "settings": {
            "daily_time": DEFAULT_DAILY_TIME,
            "max_slots": DEFAULT_MAX_SLOTS,
            "notify_default": True,
            "user_like_limit": DEFAULT_USER_LIKE_LIMIT,
            "bot_maintenance": False,
            "autolike_group_id": None,
            "free_group_id": None
        },
        "plans": DEFAULT_PLANS,
        "redeem_codes": {},
        "autolikes": {}
    }

data = load_data()

def save() -> None:
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("Failed to save data file: %s", e)

scheduler = AsyncIOScheduler()

# ── GAME ENCRYPTION & PROTOBUF LOGIC ───────────────────────────────────────
def generate_tokens_automatically():
    input_file = "accounts_ind.json"
    output_file = "token_ind.json"

    if not os.path.exists(input_file):
        logger.error(f"Error: '{input_file}' file not found!")
        return False

    try:
        with open(input_file, "r", encoding="utf-8") as f:
            accounts = json.load(f)
    except Exception as e:
        logger.error(f"Error: Invalid JSON format: {e}")
        return False

    tokens_list = []
    success_count = 0

    for acc in accounts:
        uid = str(acc.get("uid"))
        password = str(acc.get("password"))
        if not uid or not password:
            continue
        try:
            params = {"uid": uid, "password": password}
            response = requests.get(API_URL, params=params, timeout=10)
            if response.status_code == 200:
                res_data = response.json()
                token = res_data.get("token") or res_data.get("access_token") or res_data.get("data")
                if token:
                    tokens_list.append({"token": token})
                    success_count += 1
        except Exception:
            pass

    if tokens_list:
        with open(output_file, "w", encoding="utf-8") as f_out:
            json.dump(tokens_list, f_out, indent=4, ensure_ascii=False)
    logger.info(f"Auto token refresh completed (Every {TOKEN_REFRESH_HOURS}h). Generated {success_count} tokens.")
    return success_count > 0

def encrypt_message(plaintext):
    try:
        key = b"Yg&tc%DEuh6%Zc^8"
        iv = b"6oyZDr22E3ychjM%"
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded_message = pad(plaintext, AES.block_size)
        encrypted_message = cipher.encrypt(padded_message)
        return binascii.hexlify(encrypted_message).decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        return None

def create_protobuf_message(user_id, region):
    try:
        message = like_pb2.like()
        message.uid = int(user_id)
        message.region = region
        return message.SerializeToString()
    except Exception as e:
        logger.error(f"Protobuf error: {e}")
        return None

def create_uid_protobuf(uid):
    try:
        message = uid_generator_pb2.uid_generator()
        message.saturn_ = int(uid)
        message.garena = 1
        return message.SerializeToString()
    except Exception as e:
        logger.error(f"UID Protobuf error: {e}")
        return None

def get_player_info(uid, region, token):
    try:
        if region == "IND":
            url = "https://client.ind.freefiremobile.com/GetPlayerPersonalShow"
        elif region in {"BR", "US", "SAC", "NA"}:
            url = "https://client.us.freefiremobile.com/GetPlayerPersonalShow"
        else:
            url = "https://clientbp.ggpolarbear.com/GetPlayerPersonalShow"

        protobuf_data = create_uid_protobuf(uid)
        if protobuf_data is None:
            return None
        encrypted_uid = encrypt_message(protobuf_data)
        if encrypted_uid is None:
            return None

        edata = bytes.fromhex(encrypted_uid)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2022.3.47f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55",
        }
        response = requests.post(url, data=edata, headers=headers, verify=False)
        decoded = visit_count_pb2.Info()
        decoded.ParseFromString(response.content)
        return decoded
    except Exception:
        return None

async def send_like_request(encrypted_uid, token, url):
    try:
        edata = bytes.fromhex(encrypted_uid)
        headers = {
            "User-Agent": "Dalvik/2.1.0 (Linux; U; Android 9; ASUS_Z01QD Build/PI)",
            "Connection": "Keep-Alive",
            "Accept-Encoding": "gzip",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "Expect": "100-continue",
            "X-Unity-Version": "2022.3.47f1",
            "X-GA": "v1 1",
            "ReleaseVersion": "OB55",
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=edata, headers=headers) as response:
                return await response.text()
    except Exception:
        return None

# ── MESSAGING & FORMATTING HELPERS ─────────────────────────────────────────
def html_escape(value: str) -> str:
    return (
        str(value).replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )

def code(value) -> str:
    return f"<code>{html_escape(str(value))}</code>"

async def reply(message, text: str, **kwargs):
    kwargs.setdefault("parse_mode", "HTML")
    kwargs.setdefault("disable_web_page_preview", True)
    return await message.reply_text(text, **kwargs)

async def edit(message, text: str, **kwargs):
    kwargs.setdefault("parse_mode", "HTML")
    kwargs.setdefault("disable_web_page_preview", True)
    return await message.edit_text(text, **kwargs)

async def send(bot, chat_id, text: str, **kwargs):
    kwargs.setdefault("parse_mode", "HTML")
    kwargs.setdefault("disable_web_page_preview", True)
    return await bot.send_message(chat_id=chat_id, text=text, **kwargs)

# ── AUTOLIKE LOGIC & SCHEDULER ──────────────────────────────────────────────
def calculate_days_left(expiry_str: str) -> int:
    try:
        ist_tz = pytz.timezone(TIMEZONE_NAME)
        now_ist = datetime.now(ist_tz)
        expiry_dt = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        delta = expiry_dt - now_ist.date()
        return max(0, delta.days)
    except Exception:
        return 0

async def fetch_player_nickname_and_likes(region: str, uid: str):
    token_file = "token_ind.json"
    if not os.path.exists(token_file):
        await asyncio.to_thread(generate_tokens_automatically)
    try:
        with open(token_file, "r", encoding="utf-8") as f:
            tokens = json.load(f)
        if tokens:
            info = get_player_info(uid, region.upper(), tokens[0]["token"])
            if info:
                return info.AccountInfo.PlayerNickname, int(info.AccountInfo.Likes)
    except Exception:
        pass
    return "Unknown", 0

async def add_or_renew_autolike(uid: str, region: str, target: int, added_by: int,
                                 group_id: int, days: int = None,
                                 customer_user_id: int = None) -> dict:
    days = days or DEFAULT_AUTOLIKE_DAYS
    nickname, current_likes = await fetch_player_nickname_and_likes(region, uid)
    
    ist_tz = pytz.timezone(TIMEZONE_NAME)
    expiry = (datetime.now(ist_tz) + timedelta(days=days)).strftime("%Y-%m-%d")

    data.setdefault("autolikes", {})
    entry = data["autolikes"].get(str(uid), {})
    entry.update({
        "uid": str(uid),
        "region": region.upper(),
        "nickname": nickname,
        "target": int(target),
        "given_so_far": entry.get("given_so_far", 0),
        "days": days,
        "expiry": expiry,
        "added_by": added_by,
        "customer_user_id": customer_user_id,
        "group_id": group_id,
        "notify": data["settings"].get("notify_default", True),
        "status": "active",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "current_likes_at_setup": current_likes,
    })
    data["autolikes"][str(uid)] = entry
    save()
    return entry

def list_autolikes(active_only: bool = True) -> list:
    data.setdefault("autolikes", {})
    entries = list(data["autolikes"].values())
    if active_only:
        entries = [e for e in entries if e.get("status") == "active"]
    return entries

def log_temp_activity(uid, nickname, region, likes_added, source_type="auto"):
    try:
        logs = []
        if os.path.exists(TEMP_LOG_FILE):
            with open(TEMP_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
    except Exception:
        logs = []
    
    now_iso = datetime.now(timezone.utc).isoformat()
    logs.append({
        "timestamp": now_iso,
        "uid": str(uid),
        "nickname": str(nickname),
        "region": str(region),
        "likes_added": int(likes_added),
        "source_type": str(source_type)
    })
    
    cutoff = datetime.now(timezone.utc) - timedelta(days=1)
    filtered_logs = []
    for l in logs:
        try:
            if datetime.fromisoformat(l["timestamp"]) > cutoff:
                filtered_logs.append(l)
        except Exception:
            pass

    try:
        with open(TEMP_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(filtered_logs, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

async def run_autolike_after_refresh(bot) -> list:
    """Runs daily at 04:10 AM IST (Credit: Lucky)"""
    if data.get("settings", {}).get("bot_maintenance", False):
        return ["⚠️ Bot is currently turned OFF. AutoLike skipped."]
    
    logger.info("Executing 04:10 AM AutoLike phase (Credit: Lucky)...")
    summary = []
    ist_tz = pytz.timezone(TIMEZONE_NAME)
    today = datetime.now(ist_tz).strftime("%Y-%m-%d")

    token_file = "token_ind.json"
    if not os.path.exists(token_file):
        await asyncio.to_thread(generate_tokens_automatically)

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            tokens = json.load(f)
    except Exception:
        tokens = []

    if not tokens:
        return ["❌ No tokens available for AutoLike execution."]

    sample_token = tokens[0]["token"]
    data.setdefault("autolikes", {})
    data.setdefault("banned_uids", [])

    for uid, entry in list(data["autolikes"].items()):
        if entry.get("status") != "active":
            continue
        if str(uid) in data["banned_uids"]:
            summary.append(f"⚠️ {uid}: Skipped (UID is Banned)")
            continue

        region = entry.get("region", "IND")
        before_info = get_player_info(uid, region, sample_token)
        pre_likes = before_info.AccountInfo.Likes if before_info else 0

        protobuf_message = create_protobuf_message(uid, region)
        encrypted_uid = encrypt_message(protobuf_message)
        url = (
            "https://client.ind.freefiremobile.com/LikeProfile"
            if region == "IND"
            else "https://clientbp.ggpolarbear.com/LikeProfile"
        )

        tasks = [send_like_request(encrypted_uid, t["token"], url) for t in tokens]
        await asyncio.gather(*tasks, return_exceptions=True)

        after_info = get_player_info(uid, region, sample_token)
        after_likes = after_info.AccountInfo.Likes if after_info else pre_likes
        nickname = after_info.AccountInfo.PlayerNickname if after_info else entry.get("nickname", "Unknown")

        given = max(0, after_likes - pre_likes)

        entry["given_so_far"] = int(entry.get("given_so_far", 0)) + given
        entry["nickname"] = nickname
        data["autolikes"][uid] = entry
        save()

        log_temp_activity(uid, nickname, region, given, source_type="auto")

        days_left = calculate_days_left(entry.get('expiry', '9999-99-99'))
        days_notice = f"⏳ Days Left : <b>{days_left} Days</b>"
        if days_left <= 2:
            days_notice += f"\n⚠️ <i>Subscription expiring soon! Renew via Admin: {ADMIN_USERNAME}</i>"

        card = (
            f"🛡️ <b>VIP AUTO LIKE SUMMARY</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👤 Player : {html_escape(nickname)}\n"
            f"🆔 UID : {code(uid)}\n"
            f"🌍 Region : {html_escape(region)}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"❤️ Before : {pre_likes}\n"
            f"💚 After : {after_likes}\n"
            f"➕ Added : +{given}\n"
            f"🎯 Target : {entry['given_so_far']} / {entry.get('target', 0)}\n"
            f"{days_notice}\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"👑 Admin Contact: {ADMIN_USERNAME}"
        )

        target_group_id = data.get("settings", {}).get("autolike_group_id") or entry.get("group_id")
        sent_chat_ids = set()
        
        if target_group_id:
            try:
                await send(bot, target_group_id, card)
                sent_chat_ids.add(int(target_group_id))
            except TelegramError:
                pass

        customer_id = entry.get("customer_user_id")
        if customer_id and entry.get("notify", True) and int(customer_id) not in sent_chat_ids:
            try:
                await send(bot, customer_id, card)
            except TelegramError:
                pass

        summary.append(f"✅ {uid}: +{given} ({entry['given_so_far']}/{entry.get('target', 0)}) | Days Left: {days_left}")

        target_done = entry["given_so_far"] >= entry.get("target", 0) > 0
        expiry_done = today >= entry.get("expiry", "9999-99-99")
        if target_done or expiry_done:
            entry["status"] = "completed" if target_done else "expired"
            data["autolikes"][uid] = entry
            save()

    return summary

async def token_refresh_job():
    logger.info(f"Executing scheduled {TOKEN_REFRESH_HOURS}-hour background token refresh (Credit: Lucky)...")
    try:
        await asyncio.to_thread(generate_tokens_automatically)
        logger.info("Background token refresh completed successfully.")
    except Exception as e:
        logger.error("Error in background token refresh job: %s", e)

async def redeem_cleanup_job():
    logger.info("Running automated cleanup for expired redeem codes (Credit: Lucky)...")
    try:
        data.setdefault("redeem_codes", {})
        codes = data["redeem_codes"]
        now = datetime.now(timezone.utc)
        removed_count = 0

        for code_name, info in list(codes.items()):
            created_at_str = info.get("created_at")
            if created_at_str:
                created_at = datetime.fromisoformat(created_at_str)
                if now - created_at > timedelta(days=2):
                    del codes[code_name]
                    removed_count += 1

        if removed_count > 0:
            save()
            logger.info(f"Cleaned up {removed_count} expired redeem codes successfully.")
    except Exception as e:
        logger.error("Error in redeem code cleanup job: %s", e)

async def autolike_log_cleanup_job():
    logger.info("Running 1-day temporary log cleanup (Credit: Lucky)...")
    try:
        if os.path.exists(TEMP_LOG_FILE):
            with open(TEMP_LOG_FILE, "r", encoding="utf-8") as f:
                logs = json.load(f)
            cutoff = datetime.now(timezone.utc) - timedelta(days=1)
            fresh_logs = [l for l in logs if datetime.fromisoformat(l["timestamp"]) > cutoff]
            with open(TEMP_LOG_FILE, "w", encoding="utf-8") as f:
                json.dump(fresh_logs, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.error("Error in temporary log cleanup: %s", e)

def schedule_jobs(app):
    tz = pytz.timezone(TIMEZONE_NAME)

    if scheduler.get_job("autolike_after"):
        scheduler.remove_job("autolike_after")
    if scheduler.get_job("token_refresh"):
        scheduler.remove_job("token_refresh")
    if scheduler.get_job("redeem_cleanup"):
        scheduler.remove_job("redeem_cleanup")
    if scheduler.get_job("log_cleanup"):
        scheduler.remove_job("log_cleanup")

    # Daily 04:10 AM AutoLike
    scheduler.add_job(
        run_autolike_after_refresh,
        CronTrigger(hour=4, minute=10, timezone=tz),
        args=[app],
        id="autolike_after",
        replace_existing=True,
    )

    # Har 4 ghante me automatic token refresh
    scheduler.add_job(
        token_refresh_job,
        IntervalTrigger(hours=TOKEN_REFRESH_HOURS),
        id="token_refresh",
        replace_existing=True,
    )

    # 24h Redeem cleanup
    scheduler.add_job(
        redeem_cleanup_job,
        IntervalTrigger(hours=24),
        id="redeem_cleanup",
        replace_existing=True,
    )

    # 1h Log cleanup
    scheduler.add_job(
        autolike_log_cleanup_job,
        IntervalTrigger(hours=1),
        id="log_cleanup",
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
    logger.info(f"Schedulers active: AutoLike (04:10 AM), Token Refresh (Every {TOKEN_REFRESH_HOURS}h), & Cleanup (Credit: Lucky)")

# ── HELPER FOR MANDATORY MEMBERSHIP CHECK ──────────────────────────────────
async def verify_mandatory_group_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return True
    
    if user.id == OWNER_ID or user.id in data.get("admins", []):
        return True

    primary_group_id = data.get("settings", {}).get("autolike_group_id")
    if not primary_group_id:
        return True

    try:
        member = await context.bot.get_chat_member(chat_id=primary_group_id, user_id=user.id)
        if member.status in ['left', 'kicked']:
            return False
    except Exception:
        pass
    return True

# ── TELEGRAM COMMAND HANDLERS ──────────────────────────────────────────────
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message:
        return
    user = update.effective_user
    is_admin = user and (user.id == OWNER_ID or user.id in data.get("admins", []))

    current_limit = data.get("settings", {}).get("user_like_limit", DEFAULT_USER_LIKE_LIMIT)
    is_off = data.get("settings", {}).get("bot_maintenance", False)
    status_text = "🔴 <b>OFF (Maintenance)</b>" if is_off else "🟢 <b>ON (Active)</b>"

    text = (
        "✨━━━━━━━━━━━━━━━✨\n"
        f"🛠️ <b>FREE FIRE VIP BOT</b> [Status: {status_text}]\n"
        "✨━━━━━━━━━━━━━━━✨\n\n"
        "👤 <b>User Commands:</b>\n"
        "🔹 /start - Start the bot\n"
        f"🔹 /like &lt;region&gt; &lt;uid&gt; - Send manual likes (Limit: {current_limit}, resets after 04:10 AM daily)\n"
        "🔹 /info &lt;region&gt; &lt;uid&gt; - Fetch account details\n"
        "🔹 /redeem &lt;code&gt; &lt;region&gt; &lt;uid&gt; - Redeem AutoLike code\n"
        "🔹 /myautolike1 - View your AutoLike status & days left\n"
        "🔹 /plans - View VIP AutoLike plans & bonuses\n\n"
        f"👑 <b>Admin Contact:</b> {ADMIN_USERNAME}"
    )

    if is_admin:
        text += (
            "\n\n👑 <b>Owner &amp; Admin Commands:</b>\n"
            "▫️ /bot_off - Turn bot OFF (Maintenance mode)\n"
            "▫️ /bot_on - Turn bot ON\n"
            "▫️ /set_autolike_group - Set current group as AutoLike group\n"
            "▫️ /set_free_group - Set current group as Free & Paid group\n"
            "▫️ /makeredeem &lt;uses&gt; &lt;target_likes&gt; &lt;days&gt; - Create Redeem Code\n"
            "▫️ /set_plan &lt;id&gt; &lt;price&gt; &lt;likes&gt; &lt;days&gt; - Edit AutoLike Plans\n"
            "▫️ /set_user_limit &lt;number&gt; - Set max likes for normal users\n"
            "▫️ /autolike1 &lt;region&gt; &lt;uid&gt; &lt;target_likes&gt; &lt;days&gt; [&lt;user_id&gt;] - Setup AutoLike\n"
            "▫️ /show_autoids - View all active AutoLikes & cancel them easily\n"
            "▫️ /ban &lt;uid&gt; - Ban UID from receiving likes\n"
            "▫️ /unban &lt;uid&gt; - Unban UID\n"
            "▫️ /like_list1 - View active AutoLikes list\n"
            "▫️ /viewac - View today's likes activity\n"
            "▫️ /runnow (or /force_like1) - Run AutoLike immediately\n"
            "▫️ /getfile1 - Get database backup file"
        )

    await reply(update.message, text)

async def set_autolike_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        await reply(update.message, "❌ You don't have permission.")
        return
    chat_id = update.effective_chat.id
    data.setdefault("settings", {})
    data["settings"]["autolike_group_id"] = chat_id
    save()
    await reply(update.message, f"✅ This chat (ID: <code>{chat_id}</code>) has been successfully set as the **AutoLike Notification Group**!\n\n🔗 Group Link: {MANDATORY_GROUP_LINK}")

async def set_free_group_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        await reply(update.message, "❌ You don't have permission.")
        return
    chat_id = update.effective_chat.id
    data.setdefault("settings", {})
    data["settings"]["free_group_id"] = chat_id
    save()
    await reply(update.message, f"✅ This chat (ID: <code>{chat_id}</code>) has been successfully set as the **Free & Paid Group**!\n\n🔗 Group Link: {FREE_PAID_GROUP_LINK}")

async def bot_off_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        await reply(update.message, "❌ You don't have permission.")
        return
    data.setdefault("settings", {})
    data["settings"]["bot_maintenance"] = True
    save()
    await reply(update.message, "🔴 **Bot is now TURNED OFF (Maintenance Mode)**.")

async def bot_on_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        await reply(update.message, "❌ You don't have permission.")
        return
    data.setdefault("settings", {})
    data["settings"]["bot_maintenance"] = False
    save()
    await reply(update.message, "🟢 **Bot is now TURNED ON & Active**.")

async def set_plan_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        await reply(update.message, "❌ You don't have permission.")
        return

    args = context.args or []
    if len(args) < 4:
        await reply(update.message, "⚠️ Usage: <code>/set_plan &lt;plan_id&gt; &lt;price&gt; &lt;likes&gt; &lt;days&gt;</code>\nExample: <code>/set_plan 1 50 2000 40</code>")
        return

    plan_id, price_str, likes_str, days_str = args[0], args[1], args[2], args[3]
    if plan_id not in ["1", "2", "3", "4"]:
        await reply(update.message, "❌ Invalid Plan ID! Use 1, 2, 3 or 4.")
        return

    data.setdefault("plans", DEFAULT_PLANS)
    data["plans"][plan_id] = {
        "price": int(price_str),
        "likes": int(likes_str),
        "days": int(days_str)
    }
    save()
    await reply(update.message, f"✅ Plan <b>{plan_id}</b> successfully updated!")

async def makeredeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        await reply(update.message, "❌ You don't have permission.")
        return

    args = context.args or []
    if len(args) < 3:
        await reply(update.message, "⚠️ Usage: <code>/makeredeem &lt;uses&gt; &lt;target_likes&gt; &lt;days&gt;</code>\nExample: <code>/makeredeem 5 2000 40</code>")
        return

    max_uses, target_likes, days = int(args[0]), int(args[1]), int(args[2])
    rand_suffix = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=5))
    code_name = f"LUCKY_LIKE_{rand_suffix}"

    data.setdefault("redeem_codes", {})
    data["redeem_codes"][code_name] = {
        "max_uses": max_uses,
        "uses_left": max_uses,
        "target": target_likes,
        "days": days,
        "created_by": user.id,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    save()

    card = (
        "┌──────────────────────────┐\n"
        "   🎁 <b>VIP REDEEM VOUCHER</b>\n"
        "└──────────────────────────┘\n\n"
        f"🔑 <b>Code:</b> <code>{code_name}</code>\n"
        f"👥 <b>Uses:</b> <code>{max_uses}</code>\n"
        f"🎯 <b>Likes:</b> <code>{target_likes}</code>\n"
        f"⛩️ <b>Days:</b> <code>{days}</code>\n\n"
        f"📌 Use: <code>/redeem {code_name} &lt;region&gt; &lt;uid&gt;</code>\n"
        f"👑 Admin: {ADMIN_USERNAME}"
    )
    await reply(update.message, card)

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return

    if data.get("settings", {}).get("bot_maintenance", False):
        await reply(update.message, "⚠️ Bot is under maintenance.")
        return

    if not await verify_mandatory_group_membership(update, context):
        await reply(update.message, f"❌ AutoLike redeem karne ke liye aapko pehle hamara main group join karna hoga!\n\n🔗 Group Link: {MANDATORY_GROUP_LINK}\n\nJoin karne ke baad dubara try karein.")
        return

    args = context.args or []
    if len(args) < 3:
        await reply(update.message, "⚠️ Usage: <code>/redeem &lt;code&gt; &lt;region&gt; &lt;uid&gt;</code>\nExample: <code>/redeem LUCKY_LIKE_ABCDE IND 4145036005</code>")
        return

    code_name, region, uid = args[0].strip(), args[1].upper(), args[2].strip()
    
    data.setdefault("banned_uids", [])
    if uid in data["banned_uids"]:
        await reply(update.message, f"❌ This UID ({code(uid)}) is banned!")
        return

    data.setdefault("redeem_codes", {})
    codes = data["redeem_codes"]

    if code_name not in codes or codes[code_name]["uses_left"] <= 0:
        await reply(update.message, "❌ Invalid or exhausted redeem code!")
        return

    msg = await reply(update.message, "⏳ Processing voucher...")
    rc = codes[code_name]
    rc["uses_left"] -= 1
    if rc["uses_left"] <= 0:
        del codes[code_name]
    save()

    chat_id = update.effective_chat.id
    entry = await add_or_renew_autolike(
        uid=uid, region=region, target=rc["target"],
        added_by=rc["created_by"], group_id=chat_id,
        days=rc["days"], customer_user_id=user.id,
    )

    days_left = calculate_days_left(entry['expiry'])
    card = (
        "┌──────────────────────────┐\n"
        "   🎉 <b>REDEEM SUCCESSFUL! (VIP)</b>\n"
        "└──────────────────────────┘\n\n"
        f"👤 <b>Player Name:</b> {html_escape(entry['nickname'])}\n"
        f"🆔 <b>Target UID:</b> {code(uid)}\n"
        f"🌍 <b>Region:</b> {html_escape(region)}\n"
        f"⛩️ <b>Duration:</b> {entry['days']} Days\n"
        f"⏳ <b>Days Left:</b> <b>{days_left} Days</b>\n"
        f"🎯 <b>Target Likes:</b> {rc['target']} Likes\n"
        f"📅 <b>Expiry Date:</b> {entry['expiry']}\n\n"
        "✅ <i>AutoLike service activated successfully!</i>\n\n"
        f"👑 <b>Admin Contact:</b> {ADMIN_USERNAME}"
    )
    await edit(msg, card)

    free_group_id = data.get("settings", {}).get("free_group_id")
    if free_group_id and int(free_group_id) != chat_id:
        try:
            await send(context.bot, free_group_id, card)
        except TelegramError:
            pass

async def set_user_limit_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    args = context.args or []
    if not args or not args[0].isdigit():
        await reply(update.message, "⚠️ Usage: <code>/set_user_limit &lt;number&gt;</code>\nExample: <code>/set_user_limit 20</code>")
        return
    data.setdefault("settings", {})
    data["settings"]["user_like_limit"] = int(args[0])
    save()
    await reply(update.message, f"✅ Limit updated to {args[0]}")

async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    args = context.args or []
    if not args:
        await reply(update.message, "⚠️ Usage: <code>/ban &lt;uid&gt;</code>\nExample: <code>/ban 4145036005</code>")
        return
    uid = args[0].strip()
    data.setdefault("banned_uids", [])
    if uid not in data["banned_uids"]:
        data["banned_uids"].append(uid)
        save()
        await reply(update.message, f"🚫 UID {code(uid)} banned.")

async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    args = context.args or []
    if not args:
        await reply(update.message, "⚠️ Usage: <code>/unban &lt;uid&gt;</code>\nExample: <code>/unban 4145036005</code>")
        return
    uid = args[0].strip()
    data.setdefault("banned_uids", [])
    if uid in data["banned_uids"]:
        data["banned_uids"].remove(uid)
        save()
        await reply(update.message, f"✅ UID {code(uid)} unbanned.")

async def info_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    args = context.args or []
    if len(args) < 2:
        await reply(update.message, "⚠️ Usage: <code>/info &lt;region&gt; &lt;uid&gt;</code>\nExample: <code>/info IND 4145036005</code>")
        return
    region, uid = args[0].upper(), args[1]
    msg = await reply(update.message, "⏳ Fetching info...")

    token_file = "token_ind.json"
    if not os.path.exists(token_file):
        await asyncio.to_thread(generate_tokens_automatically)

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            tokens = json.load(f)
        if not tokens:
            await edit(msg, "❌ No tokens.")
            return
        info = get_player_info(uid, region, tokens[0]["token"])
        if not info:
            await edit(msg, "❌ Failed.")
            return
        acc = info.AccountInfo
        card = (
            f"🎮 <b>PLAYER INFO</b>\n"
            f"👤 Name: {html_escape(acc.PlayerNickname)}\n"
            f"🆔 UID: {code(uid)}\n"
            f"❤️ Likes: {getattr(acc, 'Likes', 0)}\n"
            f"⭐ Level: {getattr(acc, 'Level', 'N/A')}"
        )
        await edit(msg, card)
    except Exception:
        await edit(msg, "❌ Error fetching info.")

async def like_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if data.get("settings", {}).get("bot_maintenance", False):
        await reply(update.message, "⚠️ Bot is under maintenance.")
        return

    user = update.effective_user
    
    if not await verify_mandatory_group_membership(update, context):
        await reply(update.message, f"❌ Free like use karne ke liye aapko pehle hamara main group join karna hoga!\n\n🔗 Group Link: {MANDATORY_GROUP_LINK}\n\nJoin karne ke baad dubara `/like` command try karein.")
        return

    args = context.args or []
    if len(args) < 2:
        await reply(update.message, "⚠️ Usage: <code>/like &lt;region&gt; &lt;uid&gt;</code>\nExample: <code>/like IND 4145036005</code>")
        return

    region, uid = args[0].upper(), args[1]
    
    data.setdefault("banned_uids", [])
    if uid in data["banned_uids"]:
        await reply(update.message, f"❌ UID ({code(uid)}) is banned!")
        return

    is_admin = user and (user.id == OWNER_ID or user.id in data.get("admins", []))
    if not is_admin:
        data.setdefault("user_last_like", {})
        ist_tz = pytz.timezone(TIMEZONE_NAME)
        now_ist = datetime.now(ist_tz)
        last_time_str = data["user_last_like"].get(str(user.id))
        
        if last_time_str:
            last_time_utc = datetime.fromisoformat(last_time_str)
            last_time_ist = last_time_utc.astimezone(ist_tz)
            today_410 = now_ist.replace(hour=4, minute=10, second=0, microsecond=0)
            cutoff_410 = today_410 - timedelta(days=1) if now_ist < today_410 else today_410
            
            if last_time_ist >= cutoff_410:
                next_available = cutoff_410 + timedelta(days=1)
                rem = next_available - now_ist
                await reply(update.message, f"⏳ Aap subah 04:10 AM ke baad apna free like le chuke hain! (Baqi: {int(rem.total_seconds()//3600)}h)")
                return

    msg = await reply(update.message, "⏳ Sending free likes...")

    token_file = "token_ind.json"
    if not os.path.exists(token_file):
        await asyncio.to_thread(generate_tokens_automatically)

    try:
        with open(token_file, "r", encoding="utf-8") as f:
            tokens = json.load(f)
    except Exception:
        await edit(msg, "❌ Tokens error.")
        return

    if not tokens:
        await edit(msg, "❌ No tokens.")
        return

    user_limit = int(data.get("settings", {}).get("user_like_limit", DEFAULT_USER_LIKE_LIMIT))
    selected_tokens = tokens if is_admin else tokens[:user_limit]

    sample_token = tokens[0]["token"]
    before_info = get_player_info(uid, region, sample_token)
    if not before_info:
        await edit(msg, "❌ Invalid UID or Region.")
        return

    before_likes = before_info.AccountInfo.Likes
    nickname = before_info.AccountInfo.PlayerNickname

    protobuf_message = create_protobuf_message(uid, region)
    encrypted_uid = encrypt_message(protobuf_message)
    url = "https://client.ind.freefiremobile.com/LikeProfile" if region == "IND" else "https://clientbp.ggpolarbear.com/LikeProfile"

    tasks = [send_like_request(encrypted_uid, t["token"], url) for t in selected_tokens]
    await asyncio.gather(*tasks, return_exceptions=True)

    after_info = get_player_info(uid, region, sample_token)
    after_likes = after_info.AccountInfo.Likes if after_info else before_likes
    likes_given = max(0, after_likes - before_likes)

    if not is_admin:
        data["user_last_like"][str(user.id)] = datetime.now(timezone.utc).isoformat()
        save()

    log_temp_activity(uid, nickname, region, likes_given, source_type="free/manual")

    card = (
        "✅ <b>FREE LIKES SENT SUCCESSFULLY</b>\n"
        "──────────────────────\n"
        f"👤 Player : {html_escape(nickname)}\n"
        f"🆔 UID : {code(uid)}\n"
        f"🌍 Region : {html_escape(region)}\n"
        "──────────────────────\n"
        f"❤️ Before : {before_likes}\n"
        f"💚 After : {after_likes}\n"
        f"➕ Given : +{likes_given}\n"
        "──────────────────────\n"
        f"👑 Admin: {ADMIN_USERNAME}"
    )
    await edit(msg, card)

    free_group_id = data.get("settings", {}).get("free_group_id")
    current_chat_id = update.effective_chat.id
    if free_group_id and int(free_group_id) != current_chat_id:
        try:
            await send(context.bot, free_group_id, card)
        except TelegramError:
            pass

async def autolike1_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return

    args = context.args or []
    if len(args) < 4:
        await reply(update.message, "⚠️ Usage: <code>/autolike1 &lt;region&gt; &lt;uid&gt; &lt;target_likes&gt; &lt;days&gt; [&lt;user_id&gt;]</code>\nExample: <code>/autolike1 IND 4145036005 2000 40</code>")
        return

    region, uid = args[0].upper(), args[1]
    
    data.setdefault("banned_uids", [])
    if uid in data["banned_uids"]:
        await reply(update.message, f"❌ This UID ({code(uid)}) is banned!")
        return

    likes_str, days_str = args[2], args[3]
    if not likes_str.isdigit() or not days_str.isdigit():
        await reply(update.message, "⚠️ Target likes and days must be valid numbers.")
        return

    target = int(likes_str)
    days = int(days_str)
    customer_user_id = int(args[4]) if len(args) >= 5 and args[4].isdigit() else None

    msg = await reply(update.message, "⏳ Setting up AutoLike...")
    entry = await add_or_renew_autolike(
        uid=uid, region=region, target=target,
        added_by=user.id, group_id=update.effective_chat.id,
        days=days, customer_user_id=customer_user_id,
    )

    days_left = calculate_days_left(entry['expiry'])
    card = (
        "<blockquote>"
        "🛡️ <b>VIP AUTOLIKE ACTIVATED</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👤 Player: {html_escape(entry['nickname'])}\n"
        f"🆔 UID: {code(uid)}\n"
        f"🌍 Region: {html_escape(region)}\n"
        f"⛩️ Total Days: {entry['days']} Days\n"
        f"⏳ Days Left: <b>{days_left} Days</b>\n"
        f"🎯 Target Likes: {target}\n"
        f"♥️ Current Likes: {entry.get('current_likes_at_setup', 0)}\n"
        f"📅 Expiry: {entry['expiry']}\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "🤖 Likes will run automatically at 04:10 AM daily!\n"
        f"👑 Admin Contact: <b>{ADMIN_USERNAME}</b>"
        "</blockquote>"
    )
    await edit(msg, card)

async def like_list1_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    entries = list_autolikes(active_only=True)
    if not entries:
        await reply(update.message, "ℹ️ No active AutoLikes.")
        return
    lines = [f"📋 <b>Active AutoLikes ({len(entries)})</b>\n"]
    for e in entries:
        lines.append(f"🔹 {html_escape(e.get('nickname'))} ({code(e.get('uid'))}) — 🎯 {e.get('given_so_far', 0)}/{e.get('target', 0)}")
    await reply(update.message, "\n".join(lines))

async def show_autoids_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    entries = list_autolikes(active_only=True)
    if not entries:
        await reply(update.message, "ℹ️ No active AutoLikes.")
        return
    keyboard = [[InlineKeyboardButton(f"❌ {e.get('nickname')} ({e.get('uid')})", callback_data=f"cancel_autolike_{e.get('uid')}")] for e in entries]
    await update.message.reply_text("Select to cancel:", reply_markup=InlineKeyboardMarkup(keyboard))

async def cancel_autolike_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        await query.answer("❌ Unauthorized!", show_alert=True)
        return
    if query.data.startswith("cancel_autolike_"):
        uid = query.data.replace("cancel_autolike_", "").strip()
        if uid in data.get("autolikes", {}):
            data["autolikes"][uid]["status"] = "cancelled"
            save()
            await query.answer("✅ Cancelled successfully!", show_alert=True)
            await query.edit_message_text(f"✅ AutoLike cancelled for UID: {code(uid)}")

async def viewac_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    try:
        logs = json.load(open(TEMP_LOG_FILE, "r", encoding="utf-8")) if os.path.exists(TEMP_LOG_FILE) else []
    except Exception:
        logs = []
    await reply(update.message, f"📊 Total 24h transactions recorded: <code>{len(logs)}</code>")

async def force_like1_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    msg = await reply(update.message, "⏳ Running AutoLike now...")
    summary = await run_autolike_after_refresh(context.bot)
    await edit(msg, "✅ Done:\n" + "\n".join(summary[:10]))

async def getfile1_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or (user.id != OWNER_ID and user.id not in data.get("admins", [])):
        return
    try:
        with open(DATA_FILE, "rb") as f:
            await context.bot.send_document(chat_id=user.id, document=f)
    except Exception as e:
        await reply(update.message, f"❌ Error: {e}")

async def myautolike_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user or not update.message:
        return
    data.setdefault("autolikes", {})
    mine = [e for e in data["autolikes"].values() if e.get("customer_user_id") == user.id]
    if not mine:
        await reply(update.message, f"ℹ️ You don't have any AutoLike subscription linked to your account yet.\n\n👑 Contact admin to purchase: <b>{ADMIN_USERNAME}</b>")
        return
    
    lines = ["💎 <b>Your AutoLike Status & Days Left</b>\n"]
    for e in mine:
        d_left = calculate_days_left(e.get('expiry', '9999-99-99'))
        warning_text = ""
        if d_left <= 2:
            warning_text = f"\n⚠️ <b>Aapka subscription khatam hone wala hai! Turant renew krane ke liye admin se milein: {ADMIN_USERNAME}</b>"
            
        lines.append(
            f"👤 {html_escape(e.get('nickname', 'Unknown'))} (UID: {code(e.get('uid'))})\n"
            f"🌍 Region: {html_escape(e.get('region'))}\n"
            f"🎯 Progress: {e.get('given_so_far', 0)}/{e.get('target', 0)}\n"
            f"⏳ Days Left: <b>{d_left} Days</b>\n"
            f"📅 Expiry: {html_escape(e.get('expiry'))}\n"
            f"📌 Status: {html_escape(e.get('status'))}{warning_text}\n"
        )
    await reply(update.message, "\n".join(lines))

async def plans_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    plans = data.get("plans", DEFAULT_PLANS)
    text = (
        "💎 <b>VIP AUTO-LIKE PLANS &amp; PRICING</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    # Mapping bonus representation cleanly
    bonuses = {"1": "35 Days + 5 Days Bonus", "2": "70 Days + 10 Days Bonus", "3": "100 Days + 20 Days Bonus", "4": "140 Days + 30 Days Bonus"}
    for k, p in plans.items():
        b_text = bonuses.get(k, f"{p['days']} Days")
        text += f"🔹 <b>Plan {k}</b>: ₹{p['price']} ➔ <code>{p['likes']} Likes</code> ({b_text})\n"
    
    text += (
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔗 <b>AutoLike Group:</b> {MANDATORY_GROUP_LINK}\n"
        f"🔗 <b>Free &amp; Paid Group:</b> {FREE_PAID_GROUP_LINK}\n\n"
        f"👑 <b>To Buy Plans, Contact Admin:</b> {ADMIN_USERNAME}"
    )
    await reply(update.message, text)

# ── POST INIT & COMMAND SCOPING ────────────────────────────────────────────
async def post_init(application: Application) -> None:
    schedule_jobs(application)

    user_cmds = [
        BotCommand("start", "Start the bot"),
        BotCommand("like", "Send free likes <region> <uid>"),
        BotCommand("info", "Check player info <region> <uid>"),
        BotCommand("redeem", "Redeem AutoLike voucher"),
        BotCommand("myautolike1", "Check your AutoLike status"),
        BotCommand("plans", "View VIP AutoLike plans"),
    ]

    admin_cmds = user_cmds + [
        BotCommand("bot_on", "Turn bot ON"),
        BotCommand("bot_off", "Turn bot OFF (Maintenance)"),
        BotCommand("set_autolike_group", "Set AutoLike notification group"),
        BotCommand("set_free_group", "Set Free & Paid group"),
        BotCommand("makeredeem", "Generate redeem code"),
        BotCommand("set_plan", "Edit AutoLike plans"),
        BotCommand("set_user_limit", "Set free like limit"),
        BotCommand("autolike1", "Add/Renew AutoLike"),
        BotCommand("show_autoids", "Manage/Cancel active AutoLikes"),
        BotCommand("like_list1", "List all active AutoLikes"),
        BotCommand("ban", "Ban a UID"),
        BotCommand("unban", "Unban a UID"),
        BotCommand("viewac", "View 24h like activity"),
        BotCommand("runnow", "Run AutoLike immediately"),
        BotCommand("getfile1", "Get database backup"),
    ]

    try:
        await application.bot.set_my_commands(user_cmds, scope=BotCommandScopeDefault())
        admin_ids = set(data.get("admins", []))
        admin_ids.add(OWNER_ID)
        for admin_id in admin_ids:
            try:
                await application.bot.set_my_commands(admin_cmds, scope=BotCommandScopeChat(chat_id=admin_id))
            except Exception:
                pass
    except Exception as e:
        logger.error("Failed setting commands: %s", e)

    logger.info(f"Bot initialized! Auto token refresh scheduled every {TOKEN_REFRESH_HOURS} hours.")

def main():
    tg_app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    tg_app.add_handler(CommandHandler("start", start_command))
    tg_app.add_handler(CommandHandler("bot_off", bot_off_command))
    tg_app.add_handler(CommandHandler("bot_on", bot_on_command))
    tg_app.add_handler(CommandHandler("set_autolike_group", set_autolike_group_command))
    tg_app.add_handler(CommandHandler("set_free_group", set_free_group_command))
    tg_app.add_handler(CommandHandler("makeredeem", makeredeem_command))
    tg_app.add_handler(CommandHandler("redeem", redeem_command))
    tg_app.add_handler(CommandHandler("set_user_limit", set_user_limit_command))
    tg_app.add_handler(CommandHandler("set_plan", set_plan_command))
    tg_app.add_handler(CommandHandler("ban", ban_command))
    tg_app.add_handler(CommandHandler("unban", unban_command))
    tg_app.add_handler(CommandHandler("like", like_command))
    tg_app.add_handler(CommandHandler("info", info_command))
    tg_app.add_handler(CommandHandler("autolike1", autolike1_command))
    tg_app.add_handler(CommandHandler("like_list1", like_list1_command))
    tg_app.add_handler(CommandHandler("show_autoids", show_autoids_command))
    tg_app.add_handler(CallbackQueryHandler(cancel_autolike_callback, pattern="^cancel_autolike_"))
    tg_app.add_handler(CommandHandler("viewac", viewac_command))
    tg_app.add_handler(CommandHandler("force_like1", force_like1_command))
    tg_app.add_handler(CommandHandler("runnow", force_like1_command))
    tg_app.add_handler(CommandHandler("getfile1", getfile1_command))
    tg_app.add_handler(CommandHandler("myautolike1", myautolike_command))
    tg_app.add_handler(CommandHandler("plans", plans_command))

    logger.info("Bot starting...")
    tg_app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
