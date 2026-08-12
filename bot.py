import sqlite3
import logging
import os
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# ==================== НАСТРОЙКИ ====================
BOT_TOKEN = "8957788716:AAGQZw8y_KpFPztBFiUFSewNkX-JJlc-GxQ"
ADMIN_ID = 5544640837
DB_PATH = "/home/AzzaPrivetKaka/people.db"
PROMO = "azzagod"
PROMO_BONUS = 5
CHANNEL = "https://t.me/fidonetazza"
WELCOME_IMG = "https://i.postimg.cc/xXKNYSMf/IMG-0652.jpg"
STICKER = "CAACAgIAAxkBAAFRmw1qe7DGoWOwMrZM8jjcS1FPatnHEQACu6sAAtCf4UuhSml8VfSo_D0E"

SEARCH_SITES = [
    ("Telegram", "https://t.me/{}"),
    ("GitHub", "https://github.com/{}"),
    ("GitLab", "https://gitlab.com/{}"),
    ("Reddit", "https://reddit.com/user/{}"),
    ("Steam", "https://steamcommunity.com/id/{}"),
    ("Twitch", "https://twitch.tv/{}"),
    ("YouTube", "https://youtube.com/@{}"),
    ("Pinterest", "https://pinterest.com/{}"),
    ("SoundCloud", "https://soundcloud.com/{}"),
    ("Vimeo", "https://vimeo.com/{}"),
    ("Dribbble", "https://dribbble.com/{}"),
    ("Behance", "https://behance.net/{}"),
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ==================== БАЗА ДАННЫХ ====================
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def setup_database():
    db = get_db()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, nick TEXT, platform TEXT,
            phone TEXT, email TEXT, city TEXT,
            info TEXT, added_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            uid TEXT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            registered TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            balance INTEGER DEFAULT 1,
            blocked INTEGER DEFAULT 0,
            promo_used INTEGER DEFAULT 0,
            total_spent INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS search_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT, username TEXT, first_name TEXT,
            query TEXT, found INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS start_events (
            uid TEXT PRIMARY KEY,
            username TEXT, first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    db.commit()
    return db

db = setup_database()

# ==================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ====================
def is_admin(user):
    return user.id == ADMIN_ID

def log_event(table, **kwargs):
    try:
        cur = db.cursor()
        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join(["?"] * len(kwargs))
        cur.execute(f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})", list(kwargs.values()))
        db.commit()
    except Exception as e:
        logging.error(f"log_event: {e}")

def get_user(uid):
    try:
        cur = db.cursor()
        cur.execute("SELECT * FROM users WHERE uid = ?", (str(uid),))
        return cur.fetchone()
    except Exception as e:
        logging.error(f"get_user: {e}")
        return None

def is_blocked(uid):
    user = get_user(uid)
    return user is not None and len(user) > 5 and user[5] == 1

def register(uid, username, first_name):
    try:
        cur = db.cursor()
        cur.execute("INSERT OR IGNORE INTO users (uid, username, first_name) VALUES (?, ?, ?)", (str(uid), username or "", first_name or ""))
        db.commit()
    except Exception as e:
        logging.error(f"register: {e}")

def spend_credit(uid):
    try:
        cur = db.cursor()
        cur.execute("UPDATE users SET balance = balance - 1, total_spent = total_spent + 1 WHERE uid = ? AND balance > 0", (str(uid),))
        db.commit()
        return cur.rowcount > 0
    except Exception as e:
        logging.error(f"spend_credit: {e}")
        return False

def add_credits(uid, amount):
    try:
        cur = db.cursor()
        cur.execute("INSERT OR IGNORE INTO users (uid, username, first_name, balance) VALUES (?, '', '', 0)", (str(uid),))
        cur.execute("UPDATE users SET balance = balance + ? WHERE uid = ?", (amount, str(uid)))
        db.commit()
    except Exception as e:
        logging.error(f"add_credits: {e}")

def block(uid):
    try:
        cur = db.cursor()
        cur.execute("INSERT OR REPLACE INTO users (uid, username, first_name, balance, blocked) VALUES (?, '', '', 1, 1)", (str(uid),))
        db.commit()
    except Exception as e:
        logging.error(f"block: {e}")

def unblock(uid):
    try:
        cur = db.cursor()
        cur.execute("UPDATE users SET blocked = 0 WHERE uid = ?", (str(uid),))
        db.commit()
    except Exception as e:
        logging.error(f"unblock: {e}")

def used_promo(uid):
    user = get_user(uid)
    return user is not None and len(user) > 6 and user[6] == 1

def activate_promo(uid):
    try:
        cur = db.cursor()
        cur.execute("UPDATE users SET promo_used = 1, balance = balance + ? WHERE uid = ?", (PROMO_BONUS, str(uid)))
        db.commit()
    except Exception as e:
        logging.error(f"activate_promo: {e}")

def search_people(query):
    try:
        q = query.strip().lower()
        cur = db.cursor()
        
        if "@" in q:
            cur.execute("SELECT * FROM people WHERE LOWER(email) = ?", (q,))
            return cur.fetchall()
        
        if q.startswith("+") or q[0].isdigit():
            digits = "".join(c for c in q if c.isdigit())
            if digits:
                cur.execute("SELECT * FROM people WHERE REPLACE(REPLACE(REPLACE(phone, '+', ''), '-', ''), ' ', '') = ?", (digits,))
                r = cur.fetchall()
                if r:
                    return r
                cur.execute("SELECT * FROM people WHERE phone LIKE ?", ("%" + digits + "%",))
                return cur.fetchall()
        
        words = [w for w in q.split() if len(w) >= 2]
        if not words:
            return []
        
        conditions = " AND ".join(["LOWER(name) LIKE ?" for _ in words])
        params = ["%" + w + "%" for w in words]
        cur.execute("SELECT * FROM people WHERE " + conditions, params)
        
        return [r for r in cur.fetchall() if all(w in (r[1] or "").lower() for w in words)]
    except Exception as e:
        logging.error(f"search_people: {e}")
        return []

def check_nick(username):
    results = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for site, url in SEARCH_SITES:
        try:
            resp = requests.head(url.format(username), headers=headers, timeout=5, allow_redirects=True)
            if resp.status_code == 200:
                results.append((site, url.format(username)))
        except:
            pass
    return results

def check_phone(phone):
    try:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits or len(digits) < 7:
            return None, "Неверный формат"
        cur = db.cursor()
        cur.execute("SELECT * FROM people WHERE REPLACE(REPLACE(REPLACE(phone, '+', ''), '-', ''), ' ', '') = ?", (digits,))
        return (True, "В базе") if cur.fetchone() else (False, "Не найден")
    except Exception as e:
        logging.error(f"check_phone: {e}")
        return None, "Ошибка"

def lookup_ip(ip):
    try:
        resp = requests.get("http://ip-api.com/json/" + ip + "?lang=ru", timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if data.get("status") != "success":
            return None
        
        result = "🌍 *IP: " + data["query"] + "*\n"
        result += "📍 Страна: " + data["country"] + "\n"
        result += "🏙 Город: " + data["city"] + "\n"
        result += "🏢 Провайдер: " + data["isp"] + "\n"
        result += "📡 AS: " + data["as"] + "\n"
        result += "🕐 Часовой пояс: " + data["timezone"] + "\n"
        result += "🗺 [Карта](https://maps.google.com/?q=" + str(data["lat"]) + "," + str(data["lon"]) + ")"
        return result
    except:
        return None

def get_photo_metadata(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif:
            return "❌ Метаданные отсутствуют"
        
        result = []
        gps = {}
        for tag_id, value in exif.items():
            tag = TAGS.get(tag_id, tag_id)
            if tag == "GPSInfo":
                for gid, gval in value.items():
                    gps[GPSTAGS.get(gid, gid)] = gval
            elif tag in ("Make", "Model", "DateTime", "Software"):
                emoji = "📷" if tag == "Make" else "📱" if tag == "Model" else "📅" if tag == "DateTime" else "💻"
                result.append(emoji + " " + tag + ": " + str(value))
        
        if gps:
            result.append("\n📍 GPS:")
            lat = gps.get("GPSLatitude")
            lon = gps.get("GPSLongitude")
            if lat and lon:
                try:
                    la = float(lat[0]) + float(lat[1])/60 + float(lat[2])/3600
                    lo = float(lon[0]) + float(lon[1])/60 + float(lon[2])/3600
                    result.append("🗺 [Карта](https://maps.google.com/?q=" + str(round(la,6)) + "," + str(round(lo,6)) + ")")
                except:
                    pass
        
        return "\n".join(result) if result else "❌ Нет полезных метаданных"
    except:
        return "❌ Ошибка чтения"

def format_person(row):
    name = row[1] or ""
    nick = row[2] or ""
    platform = row[3] or ""
    phone = row[4] or ""
    email = row[5] or ""
    city = row[6] or ""
    info = row[7] or ""
    
    lines = ["🔎 *ФИО:* `" + name + "`"]
    
    birth = ""
    passport = ""
    address = ""
    other = []
    if info:
        for part in info.split("|"):
            part = part.strip()
            if not part:
                continue
            low = part.lower()
            if "дата" in low or "рожд" in low:
                birth = part
            elif "паспорт" in low:
                passport = part
            elif "адрес" in low:
                address = part
            else:
                other.append(part)
    
    if birth:
        lines.append("🎂 *ДР:* `" + birth + "`")
    if phone:
        lines.append("📞 *Тел:* `" + phone + "`")
    if passport:
        lines.append("📄 *Паспорт:* `" + passport + "`")
    if address:
        lines.append("🏠 *Адрес:* `" + address + "`")
    
    extra = []
    if nick:
        extra.append("👤 @" + nick)
    if platform:
        extra.append("📱 " + platform)
    if email:
        extra.append("📧 " + email)
    if city:
        extra.append("📍 " + city)
    extra.extend(other)
    
    out = "\n".join(lines)
    if extra:
        out += "\n\n📋 *Прочее:*\n" + "\n".join(["• " + e for e in extra])
    
    return out, row[0]

# ==================== КЛАВИАТУРЫ ====================
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Поиск", callback_data="search")],
        [InlineKeyboardButton("📸 Фото", callback_data="photo")],
        [InlineKeyboardButton("📱 Номер", callback_data="phone")],
        [InlineKeyboardButton("🌍 IP", callback_data="ip")],
        [InlineKeyboardButton("🔎 Ник", callback_data="sherlock")],
        [InlineKeyboardButton("🎁 sn0s", callback_data="snos")],
        [InlineKeyboardButton("🎟️ Промокод", callback_data="promo")],
        [InlineKeyboardButton("👤 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🛒 Купить", callback_data="buy")],
        [InlineKeyboardButton("🆘 Поддержка", url="https://t.me/kmosinter")]
    ])

def back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back")]])

def export_button(pid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("📥 Скачать .txt", callback_data="export_" + str(pid))]])

def photo_buttons():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔍 Google Lens", url="https://lens.google.com/")],
        [InlineKeyboardButton("🔍 Яндекс", url="https://yandex.ru/images/search?rpt=imageview")],
        [InlineKeyboardButton("🔍 Google Images", url="https://images.google.com/")]
    ])

# ==================== КОНСТАНТЫ ====================
WELCOME = "👋 *Добрый день!*\n\n*Поиск Азза*\n@kmosinter\n\n🎟️ Промокоды: " + CHANNEL
BLOCKED_MSG = "🚫 *Вы заблокированы.*\n\nРазблокировка: @kmosinter"

# ==================== ОБРАБОТЧИКИ КОМАНД ====================
async def check_block(update, context):
    user = update.effective_user
    if is_admin(user):
        return False
    if is_blocked(user.id):
        await update.message.reply_text(BLOCKED_MSG, parse_mode="Markdown")
        return True
    return False

async def cmd_start(update, context):
    user = update.effective_user
    context.user_data.clear()
    register(user.id, user.username, user.first_name)
    log_event("start_events", uid=str(user.id), username=user.username or "", first_name=user.first_name or "")
    if await check_block(update, context):
        return
    await update.message.reply_sticker(sticker=STICKER)
    await update.message.reply_photo(photo=WELCOME_IMG, caption=WELCOME, parse_mode="Markdown", reply_markup=main_menu())

async def cmd_help(update, context):
    if await check_block(update, context):
        return
    await update.message.reply_sticker(sticker=STICKER)
    await update.message.reply_photo(photo=WELCOME_IMG, caption="Поиск по ФИО, телефону, IP, нику.\n@kmosinter", reply_markup=main_menu())

async def cmd_support(update, context):
    if await check_block(update, context):
        return
    await update.message.reply_text("🆘 @kmosinter", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Поддержка", url="https://t.me/kmosinter")]]))

async def cmd_add(update, context):
    if not is_admin(update.effective_user):
        return
    if not context.args:
        await update.message.reply_photo(photo=WELCOME_IMG, caption="/add ФИО | nick | phone | city | info", reply_markup=main_menu())
        return
    parts = [p.strip() for p in " ".join(context.args).split("|")]
    while len(parts) < 7:
        parts.append("")
    if not parts[0]:
        return
    try:
        cur = db.cursor()
        cur.execute("INSERT INTO people (name, nick, platform, phone, email, city, info, added_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6], update.effective_user.username or str(update.effective_user.id)))
        db.commit()
        await update.message.reply_photo(photo=WELCOME_IMG, caption="✅ " + parts[0], reply_markup=main_menu())
    except Exception as e:
        logging.error(f"cmd_add: {e}")

async def cmd_approve(update, context):
    if not is_admin(update.effective_user):
        return
    if len(context.args) < 2:
        await update.message.reply_text("/approve ID количество")
        return
    try:
        count = int(context.args[1])
        add_credits(context.args[0], count)
        await update.message.reply_text("✅ +" + str(count) + " запросов для " + context.args[0])
    except Exception as e:
        logging.error(f"cmd_approve: {e}")
        await update.message.reply_text("Ошибка")

async def cmd_block(update, context):
    if not is_admin(update.effective_user):
        return
    if len(context.args) < 1:
        await update.message.reply_text("/block ID\n/unblock ID")
        return
    uid = context.args[0]
    if "unblock" in update.message.text:
        unblock(uid)
        await update.message.reply_text("✅ " + uid + " разблокирован")
    else:
        block(uid)
        await update.message.reply_text("🚫 " + uid + " заблокирован")

async def cmd_logi(update, context):
    if not is_admin(update.effective_user):
        return
    try:
        cur = db.cursor()
        cur.execute("SELECT * FROM search_history ORDER BY created_at DESC LIMIT 20")
        rows = cur.fetchall()
        if not rows:
            await update.message.reply_text("Пусто")
            return
        resp = "📋 *Поиски:*\n\n"
        for r in rows:
            resp += ("✅" if r[5] else "❌") + " @" + str(r[2] or r[1]) + " | " + r[4] + " | " + r[6] + "\n"
        await update.message.reply_text(resp[:4000], parse_mode="Markdown")
    except Exception as e:
        logging.error(f"cmd_logi: {e}")

async def cmd_starts(update, context):
    if not is_admin(update.effective_user):
        return
    try:
        cur = db.cursor()
        cur.execute("SELECT * FROM start_events ORDER BY created_at DESC LIMIT 50")
        rows = cur.fetchall()
        if not rows:
            await update.message.reply_text("Пусто")
            return
        resp = "📋 *Запуски:*\n\n"
        for r in rows:
            resp += "👤 @" + str(r[1] or "нет") + " | " + str(r[0]) + " | " + r[3] + "\n"
        await update.message.reply_text(resp[:4000], parse_mode="Markdown")
    except Exception as e:
        logging.error(f"cmd_starts: {e}")

async def cmd_stats(update, context):
    if await check_block(update, context):
        return
    try:
        cur = db.cursor()
        cur.execute("SELECT COUNT(*) FROM people")
        people = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM users")
        users = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM start_events")
        starts = cur.fetchone()[0]
        await update.message.reply_photo(photo=WELCOME_IMG, caption="📊 " + str(people) + " записей\n👥 " + str(users) + " пользователей\n🚀 " + str(starts) + " запусков\n\n@kmosinter", reply_markup=main_menu())
    except Exception as e:
        logging.error(f"cmd_stats: {e}")

# ==================== ОСНОВНЫЕ ФУНКЦИИ ====================
async def handle_search(update, context):
    if await check_block(update, context):
        return
    user = update.effective_user
    register(user.id, user.username, user.first_name)
    info = get_user(user.id)
    if info and len(info) > 4 and info[4] <= 0 and not is_admin(user):
        await update.message.reply_photo(photo=WELCOME_IMG, caption="❌ Нет запросов!\n🛒 @kmosinter", reply_markup=main_menu())
        return
    
    query = update.message.text.strip()
    
    if "|" in query and len(query.split("|")) >= 2 and is_admin(user):
        parts = [p.strip() for p in query.split("|")]
        while len(parts) < 7:
            parts.append("")
        if parts[0]:
            try:
                cur = db.cursor()
                cur.execute("INSERT INTO people (name, nick, platform, phone, email, city, info, added_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (parts[0], parts[1], parts[2], parts[3], parts[4], parts[5], parts[6], user.username or str(user.id)))
                db.commit()
                await update.message.reply_photo(photo=WELCOME_IMG, caption="✅ " + parts[0], reply_markup=main_menu())
            except:
                pass
            return
    
    results = search_people(query)
    log_event("search_history", uid=str(user.id), username=user.username or "", first_name=user.first_name or "", query=query, found=1 if results else 0)
    
    if not results:
        await update.message.reply_photo(photo=WELCOME_IMG, caption="❌ Ничего не найдено", reply_markup=main_menu())
        return
    
    if not is_admin(user):
        spend_credit(user.id)
    user = get_user(user.id)
    balance = user[4] if user and len(user) > 4 else 0
    
    resp, pid = format_person(results[0])
    resp += "\n\n💰 Запросов: " + str(balance)
    await update.message.reply_text(resp, parse_mode="Markdown", reply_markup=export_button(pid))

async def handle_photo(update, context):
    if await check_block(update, context):
        return
    user = update.effective_user
    register(user.id, user.username, user.first_name)
    info = get_user(user.id)
    if info and len(info) > 4 and info[4] <= 0 and not is_admin(user):
        await update.message.reply_photo(photo=WELCOME_IMG, caption="❌ Нет запросов!", reply_markup=main_menu())
        return
    
    await update.message.reply_text("🔍 Обрабатываю...")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    path = "/home/AzzaPrivetKaka/photo_" + str(user.id) + ".jpg"
    await file.download_to_drive(path)
    resp = get_photo_metadata(path)
    resp += "\n\n🔍 *Поиск места:*"
    if not is_admin(user):
        spend_credit(user.id)
    log_event("search_history", uid=str(user.id), username=user.username or "", first_name=user.first_name or "", query="📸 Фото", found=1)
    user = get_user(user.id)
    resp += "\n\n💰 Запросов: " + str(user[4] if user and len(user) > 4 else 0)
    await update.message.reply_text(resp, parse_mode="Markdown", reply_markup=photo_buttons())
    if os.path.exists(path):
        os.remove(path)

# ==================== ТЕКСТОВЫЙ РОУТЕР ====================
async def text_router(update, context):
    user = update.effective_user
    if await check_block(update, context):
        return
    
    for key in ["snos", "sherlock", "phone", "ip", "promo"]:
        if context.user_data.get("wait_" + key):
            context.user_data["wait_" + key] = False
            value = update.message.text.strip()
            
            if key == "snos":
                target = value.replace("@", "")
                if not target:
                    await update.message.reply_text("Введите username!", reply_markup=main_menu())
                    return
                info = get_user(user.id)
                if info and len(info) > 4 and info[4] <= 0 and not is_admin(user):
                    await update.message.reply_text("❌ Нет запросов!", reply_markup=main_menu())
                    return
                if not is_admin(user):
                    spend_credit(user.id)
                await update.message.reply_text("⏳ *Подождите 1-3 минуты...*\n\nПодарок для @" + target + " обрабатывается.", parse_mode="Markdown")
                asyncio.create_task(snos_delayed(context, user.id, target))
                return
            
            elif key == "sherlock":
                nick = value.replace("@", "")
                if not nick:
                    await update.message.reply_text("Введите username!", reply_markup=main_menu())
                    return
                info = get_user(user.id)
                if info and len(info) > 4 and info[4] <= 0 and not is_admin(user):
                    await update.message.reply_text("❌ Нет запросов!", reply_markup=main_menu())
                    return
                msg = await update.message.reply_text("🔎 Ищу профили...")
                sites = check_nick(nick)
                if not sites:
                    log_event("search_history", uid=str(user.id), username=user.username or "", first_name=user.first_name or "", query="🔎 " + nick, found=0)
                    await msg.edit_text("❌ Не найдено")
                    return
                if not is_admin(user):
                    spend_credit(user.id)
                log_event("search_history", uid=str(user.id), username=user.username or "", first_name=user.first_name or "", query="🔎 " + nick, found=len(sites))
                user = get_user(user.id)
                resp = "🔎 *Профили @" + nick + ":*\n\n"
                for site, url in sites:
                    resp += "• [" + site + "](" + url + ")\n"
                resp += "\n💰 Запросов: " + str(user[4] if user and len(user) > 4 else 0)
                await msg.edit_text(resp, parse_mode="Markdown", reply_markup=main_menu())
                return
            
            elif key == "phone":
                if not value:
                    await update.message.reply_text("Введите номер!", reply_markup=main_menu())
                    return
                info = get_user(user.id)
                if info and len(info) > 4 and info[4] <= 0 and not is_admin(user):
                    await update.message.reply_text("❌ Нет запросов!", reply_markup=main_menu())
                    return
                await update.message.reply_text("📱 Проверяю " + value + "...")
                ok, status = check_phone(value)
                if not is_admin(user):
                    spend_credit(user.id)
                log_event("search_history", uid=str(user.id), username=user.username or "", first_name=user.first_name or "", query="📱 " + value, found=1 if ok else 0)
                user = get_user(user.id)
                icon = "✅" if ok else "❌" if ok is False else "⚠️"
                await update.message.reply_text(icon + " *" + status + "*\n📱 " + value + "\n\n💰 Запросов: " + str(user[4] if user and len(user) > 4 else 0), parse_mode="Markdown", reply_markup=main_menu())
                return
            
            elif key == "ip":
                if not value:
                    await update.message.reply_text("Введите IP!", reply_markup=main_menu())
                    return
                info = get_user(user.id)
                if info and len(info) > 4 and info[4] <= 0 and not is_admin(user):
                    await update.message.reply_text("❌ Нет запросов!", reply_markup=main_menu())
                    return
                await update.message.reply_text("🌍 Ищу " + value + "...")
                result = lookup_ip(value)
                if not is_admin(user):
                    spend_credit(user.id)
                log_event("search_history", uid=str(user.id), username=user.username or "", first_name=user.first_name or "", query="🌍 " + value, found=1 if result else 0)
                user = get_user(user.id)
                if result:
                    await update.message.reply_text(result + "\n\n💰 Запросов: " + str(user[4] if user and len(user) > 4 else 0), parse_mode="Markdown", reply_markup=main_menu())
                else:
                    await update.message.reply_text("❌ Не удалось найти\n💰 Запросов: " + str(user[4] if user and len(user) > 4 else 0), reply_markup=main_menu())
                return
            
            elif key == "promo":
                if used_promo(user.id):
                    await update.message.reply_text("❌ Промокод уже использован!", reply_markup=main_menu())
                    return
                if value == PROMO:
                    activate_promo(user.id)
                    user = get_user(user.id)
                    await update.message.reply_text("✅ *Промокод активирован!*\n🎟️ +" + str(PROMO_BONUS) + " запросов\n💰 Баланс: " + str(user[4] if user and len(user) > 4 else 0), parse_mode="Markdown", reply_markup=main_menu())
                else:
                    await update.message.reply_text("❌ Неверный промокод!", reply_markup=main_menu())
                return
    
    await handle_search(update, context)

async def snos_delayed(context, user_id, target):
    await asyncio.sleep(90)
    try:
        await context.bot.send_message(user_id, "✅ *Подарок доставлен!*\n🎁 @" + target + "\n⏳ Активируется в течение суток.", parse_mode="Markdown", reply_markup=main_menu())
    except:
        pass

# ==================== КНОПКИ ====================
async def button_router(update, context):
    q = update.callback_query
    await q.answer()
    if await check_block(update, context):
        return
    
    data = q.data
    user = q.from_user
    
    if data == "back":
        context.user_data.clear()
        await q.message.delete()
        await q.message.reply_sticker(sticker=STICKER)
        await q.message.reply_photo(photo=WELCOME_IMG, caption=WELCOME, parse_mode="Markdown", reply_markup=main_menu())
    
    elif data == "search":
        context.user_data.clear()
        await q.edit_message_caption(caption="🔍 Введите ФИО, телефон или email.", reply_markup=back_button())
    
    elif data == "photo":
        context.user_data.clear()
        await q.edit_message_caption(caption="📸 Отправьте фото — метаданные.", reply_markup=back_button())
    
    elif data == "phone":
        context.user_data["wait_phone"] = True
        await q.edit_message_caption(caption="📱 *Проверка номера*\n\nВведите номер.\n💰 1 запрос.", parse_mode="Markdown", reply_markup=back_button())
    
    elif data == "ip":
        context.user_data["wait_ip"] = True
        await q.edit_message_caption(caption="🌍 *Поиск по IP*\n\nВведите IP-адрес.\n💰 1 запрос.", parse_mode="Markdown", reply_markup=back_button())
    
    elif data == "sherlock":
        context.user_data["wait_sherlock"] = True
        await q.edit_message_caption(caption="🔎 Введите username (без @).\n💰 1 запрос.", reply_markup=back_button())
    
    elif data == "snos":
        info = get_user(user.id)
        balance = info[4] if info and len(info) > 4 else 0
        context.user_data["wait_snos"] = True
        await q.edit_message_caption(caption="🎁 *sn0s*\n\nВведите username.\n💰 1 запрос\n💰 У вас: " + str(balance), parse_mode="Markdown", reply_markup=back_button())
    
    elif data == "promo":
        if used_promo(user.id):
            await q.answer("❌ Промокод уже использован!", show_alert=True)
            return
        context.user_data["wait_promo"] = True
        await q.edit_message_caption(caption="🎟️ *Промокод*\n\nВведите секретный код.\n+5 запросов.\n⚠️ Только 1 раз.", parse_mode="Markdown", reply_markup=back_button())
    
    elif data == "profile":
        info = get_user(user.id)
        if info:
            t = "👤 *Мой профиль*\n\n🆔 `" + str(info[0]) + "`\n👤 @" + str(info[1] or "нет") + "\n📅 " + str(info[3]) + "\n💰 Мои запросы: " + str(info[4]) + "\n📊 Потрачено: " + str(info[7] if len(info) > 7 else 0)
        else:
            t = "Не найден."
        await q.edit_message_caption(caption=t, parse_mode="Markdown", reply_markup=back_button())
    
    elif data == "buy":
        await q.edit_message_caption(caption="🛒 @kmosinter", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Купить", url="https://t.me/kmosinter")]]))
    
    elif data.startswith("export_"):
        try:
            pid = int(data.split("_")[1])
            cur = db.cursor()
            cur.execute("SELECT * FROM people WHERE id = ?", (pid,))
            row = cur.fetchone()
            if row:
                txt = "FIO: " + str(row[1]) + "\n@" + str(row[2]) + "\n" + str(row[3]) + "\n" + str(row[4]) + "\n" + str(row[5]) + "\n" + str(row[6]) + "\n\n" + str(row[7])
                fname = "/home/AzzaPrivetKaka/person_" + str(pid) + ".txt"
                with open(fname, "w", encoding="utf-8") as f:
                    f.write(txt)
                with open(fname, "rb") as f:
                    await q.message.reply_document(document=f, filename=str(row[1]).replace(" ", "_") + ".txt")
                if os.path.exists(fname):
                    os.remove(fname)
        except Exception as e:
            logging.error(f"export: {e}")

# ==================== ЗАПУСК ====================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("support", cmd_support))
    app.add_handler(CommandHandler("add", cmd_add))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("approve", cmd_approve))
    app.add_handler(CommandHandler("block", cmd_block))
    app.add_handler(CommandHandler("unblock", cmd_block))
    app.add_handler(CommandHandler("logi", cmd_logi))
    app.add_handler(CommandHandler("starts", cmd_starts))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(CallbackQueryHandler(button_router))
    
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()