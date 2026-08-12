import sqlite3
import logging
import os
import asyncio
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# Настройки
BOT_TOKEN = "8957788716:AAGQZw8y_KpFPztBFiUFSewNkX-JJlc-GxQ"
ADMIN_ID = 5544640837
DB_PATH = "/home/AzzaPrivetKaka/people.db"
CHANNEL = "https://t.me/fidonetazza"
WELCOME_IMG = "https://i.postimg.cc/xXKNYSMf/IMG-0652.jpg"
STICKER = "CAACAgIAAxkBAAFRmw1qe7DGoWOwMrZM8jjcS1FPatnHEQACu6sAAtCf4UuhSml8VfSo_D0E"

logging.basicConfig(level=logging.INFO)

# База данных
def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("CREATE TABLE IF NOT EXISTS people (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, nick TEXT, platform TEXT, phone TEXT, email TEXT, city TEXT, info TEXT, added_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS users (uid TEXT PRIMARY KEY, username TEXT, first_name TEXT, registered TIMESTAMP DEFAULT CURRENT_TIMESTAMP, balance INTEGER DEFAULT 1, blocked INTEGER DEFAULT 0)")
    conn.execute("CREATE TABLE IF NOT EXISTS search_log (id INTEGER PRIMARY KEY AUTOINCREMENT, uid TEXT, username TEXT, first_name TEXT, query TEXT, found INTEGER, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
    conn.commit()
    return conn

db = init_db()

# Функции
def is_admin(user):
    return user.id == ADMIN_ID

def get_user(uid):
    return db.execute("SELECT * FROM users WHERE uid = ?", (str(uid),)).fetchone()

def is_blocked(uid):
    u = get_user(uid)
    return u is not None and u[5] == 1

def register(uid, username, first_name):
    db.execute("INSERT OR IGNORE INTO users (uid, username, first_name) VALUES (?, ?, ?)", (str(uid), username or "", first_name or ""))
    db.commit()

def spend_credit(uid):
    db.execute("UPDATE users SET balance = balance - 1 WHERE uid = ? AND balance > 0", (str(uid),))
    db.commit()

def add_credits(uid, amount):
    db.execute("INSERT OR IGNORE INTO users (uid, username, first_name, balance) VALUES (?, '', '', 0)", (str(uid),))
    db.execute("UPDATE users SET balance = balance + ? WHERE uid = ?", (amount, str(uid)))
    db.commit()

def block_user(uid):
    db.execute("INSERT OR REPLACE INTO users (uid, username, first_name, balance, blocked) VALUES (?, '', '', 1, 1)", (str(uid),))
    db.commit()

def unblock_user(uid):
    db.execute("UPDATE users SET blocked = 0 WHERE uid = ?", (str(uid),))
    db.commit()

# Поиск
def search_db(query):
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
            if r: return r
            cur.execute("SELECT * FROM people WHERE phone LIKE ?", ("%" + digits + "%",))
            return cur.fetchall()
    words = [w for w in q.split() if len(w) >= 2]
    if not words: return []
    conds = " AND ".join(["LOWER(name) LIKE ?" for _ in words])
    params = ["%" + w + "%" for w in words]
    cur.execute("SELECT * FROM people WHERE " + conds, params)
    return [r for r in cur.fetchall() if all(w in (r[1] or "").lower() for w in words)]

def search_nick(username):
    sites = [("Telegram", "https://t.me/{}"), ("GitHub", "https://github.com/{}"), ("GitLab", "https://gitlab.com/{}"), ("Reddit", "https://reddit.com/user/{}"), ("Steam", "https://steamcommunity.com/id/{}"), ("Twitch", "https://twitch.tv/{}"), ("YouTube", "https://youtube.com/@{}")]
    res = []
    for name, url in sites:
        try:
            if requests.head(url.format(username), headers={"User-Agent": "Mozilla/5.0"}, timeout=5, allow_redirects=True).status_code == 200:
                res.append((name, url.format(username)))
        except: pass
    return res

def check_phone_db(phone):
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 7: return False, "Неверный формат"
    cur = db.cursor()
    cur.execute("SELECT * FROM people WHERE REPLACE(REPLACE(REPLACE(phone, '+', ''), '-', ''), ' ', '') = ?", (digits,))
    return (True, "В базе") if cur.fetchone() else (False, "Не найден")

def ip_lookup(ip):
    try:
        r = requests.get("http://ip-api.com/json/" + ip + "?lang=ru", timeout=5)
        if r.status_code != 200: return None
        d = r.json()
        if d.get("status") != "success": return None
        return "🌍 *IP: " + d["query"] + "*\n📍 Страна: " + d["country"] + "\n🏙 Город: " + d["city"] + "\n🏢 Провайдер: " + d["isp"] + "\n🗺 [Карта](https://maps.google.com/?q=" + str(d["lat"]) + "," + str(d["lon"]) + ")"
    except: return None

def photo_meta(path):
    try:
        img = Image.open(path)
        exif = img._getexif()
        if not exif: return "❌ Нет метаданных"
        res, gps = [], {}
        for tid, val in exif.items():
            tag = TAGS.get(tid, tid)
            if tag == "GPSInfo":
                for gid, gval in val.items(): gps[GPSTAGS.get(gid, gid)] = gval
            elif tag in ("Make", "Model", "DateTime", "Software"):
                res.append(("📷" if tag == "Make" else "📱" if tag == "Model" else "📅" if tag == "DateTime" else "💻") + " " + tag + ": " + str(val))
        if gps:
            res.append("\n📍 GPS:")
            lat, lon = gps.get("GPSLatitude"), gps.get("GPSLongitude")
            if lat and lon:
                la = float(lat[0]) + float(lat[1])/60 + float(lat[2])/3600
                lo = float(lon[0]) + float(lon[1])/60 + float(lon[2])/3600
                res.append("🗺 [Карта](https://maps.google.com/?q=" + str(round(la,6)) + "," + str(round(lo,6)) + ")")
        return "\n".join(res) if res else "❌ Нет метаданных"
    except: return "❌ Ошибка"

def format_person(row):
    name, nick, platform, phone, email, city, info = row[1] or "", row[2] or "", row[3] or "", row[4] or "", row[5] or "", row[6] or "", row[7] or ""
    lines = ["🔎 *ФИО:* `" + name + "`"]
    birth = passport = address = ""
    other = []
    if info:
        for p in info.split("|"):
            p = p.strip()
            if not p: continue
            low = p.lower()
            if "дата" in low or "рожд" in low: birth = p
            elif "паспорт" in low: passport = p
            elif "адрес" in low: address = p
            else: other.append(p)
    if birth: lines.append("🎂 *ДР:* `" + birth + "`")
    if phone: lines.append("📞 *Тел:* `" + phone + "`")
    if passport: lines.append("📄 *Паспорт:* `" + passport + "`")
    if address: lines.append("🏠 *Адрес:* `" + address + "`")
    extra = []
    if nick: extra.append("👤 @" + nick)
    if platform: extra.append("📱 " + platform)
    if email: extra.append("📧 " + email)
    if city: extra.append("📍 " + city)
    extra.extend(other)
    out = "\n".join(lines)
    if extra: out += "\n\n📋 *Прочее:*\n" + "\n".join("• " + e for e in extra)
    return out, row[0]

# Клавиатуры
def menu(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Поиск", callback_data="search")], [InlineKeyboardButton("📸 Фото", callback_data="photo")], [InlineKeyboardButton("📱 Номер", callback_data="phone")], [InlineKeyboardButton("🌍 IP", callback_data="ip")], [InlineKeyboardButton("🔎 Ник", callback_data="sherlock")], [InlineKeyboardButton("🎁 sn0s", callback_data="snos")], [InlineKeyboardButton("👤 Профиль", callback_data="profile")], [InlineKeyboardButton("🛒 Купить", callback_data="buy")], [InlineKeyboardButton("🆘 Поддержка", url="https://t.me/kmosinter")]])
def back(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back")]])
def export_btn(pid): return InlineKeyboardMarkup([[InlineKeyboardButton("📥 Скачать .txt", callback_data="export_" + str(pid))]])
def photo_btns(): return InlineKeyboardMarkup([[InlineKeyboardButton("🔍 Google Lens", url="https://lens.google.com/")], [InlineKeyboardButton("🔍 Яндекс", url="https://yandex.ru/images/search?rpt=imageview")], [InlineKeyboardButton("🔍 Google Images", url="https://images.google.com/")]])

WELCOME = "👋 *Поиск Азза*\n@kmosinter\nКанал: " + CHANNEL
BLOCKED = "🚫 *Вы заблокированы.*\n@kmosinter"

# Команды
async def chk_block(update, context):
    u = update.effective_user
    if is_admin(u): return False
    if is_blocked(u.id):
        await update.message.reply_text(BLOCKED, parse_mode="Markdown")
        return True
    return False

async def start(update, context):
    u = update.effective_user
    context.user_data.clear()
    register(u.id, u.username, u.first_name)
    if await chk_block(update, context): return
    await update.message.reply_sticker(sticker=STICKER)
    await update.message.reply_photo(WELCOME_IMG, caption=WELCOME, parse_mode="Markdown", reply_markup=menu())

async def help_cmd(update, context):
    if await chk_block(update, context): return
    await update.message.reply_photo(WELCOME_IMG, caption="Поиск по ФИО, тел, IP, нику.", reply_markup=menu())

async def support_cmd(update, context):
    await update.message.reply_text("🆘 @kmosinter", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Поддержка", url="https://t.me/kmosinter")]]))

async def add_cmd(update, context):
    if not is_admin(update.effective_user): return
    if not context.args:
        await update.message.reply_text("/add ФИО | nick | phone | city | info"); return
    p = [x.strip() for x in " ".join(context.args).split("|")]
    while len(p) < 7: p.append("")
    if not p[0]: return
    db.execute("INSERT INTO people (name, nick, platform, phone, email, city, info, added_by) VALUES (?,?,?,?,?,?,?,?)", (p[0],p[1],p[2],p[3],p[4],p[5],p[6], update.effective_user.username or str(update.effective_user.id)))
    db.commit()
    await update.message.reply_text("✅ " + p[0])

async def approve_cmd(update, context):
    u = update.effective_user
    if not is_admin(u): return
    if len(context.args) < 2:
        await update.message.reply_text("/approve ID количество"); return
    uid = context.args[0]
    try: n = int(context.args[1])
    except: await update.message.reply_text("Число!"); return
    add_credits(uid, n)
    await update.message.reply_text("✅ +" + str(n) + " запросов для " + uid)

async def block_cmd(update, context):
    if not is_admin(update.effective_user): return
    if len(context.args) < 1: return
    uid = context.args[0]
    if "unblock" in update.message.text:
        unblock_user(uid); await update.message.reply_text("✅ " + uid + " разблокирован")
    else:
        block_user(uid); await update.message.reply_text("🚫 " + uid + " заблокирован")

async def logi_cmd(update, context):
    if not is_admin(update.effective_user): return
    cur = db.cursor()
    cur.execute("SELECT * FROM search_log ORDER BY created_at DESC LIMIT 20")
    rows = cur.fetchall()
    if not rows: await update.message.reply_text("Пусто"); return
    resp = "📋 *Поиски:*\n\n"
    for r in rows: resp += ("✅" if r[5] else "❌") + " @" + str(r[2] or r[1]) + " | " + r[4] + " | " + r[6] + "\n"
    await update.message.reply_text(resp[:4000], parse_mode="Markdown")

async def stats_cmd(update, context):
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM people"); ppl = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users"); usr = cur.fetchone()[0]
    await update.message.reply_text("📊 " + str(ppl) + " записей\n👥 " + str(usr) + " пользователей")

# Поиск
async def search_handler(update, context):
    if await chk_block(update, context): return
    u = update.effective_user
    register(u.id, u.username, u.first_name)
    info = get_user(u.id)
    if info and info[4] <= 0 and not is_admin(u):
        await update.message.reply_text("❌ Нет запросов!\n🛒 @kmosinter", reply_markup=menu()); return
    q = update.message.text.strip()
    if "|" in q and len(q.split("|")) >= 2 and is_admin(u):
        p = [x.strip() for x in q.split("|")]
        while len(p) < 7: p.append("")
        if p[0]:
            db.execute("INSERT INTO people (name, nick, platform, phone, email, city, info, added_by) VALUES (?,?,?,?,?,?,?,?)", (p[0],p[1],p[2],p[3],p[4],p[5],p[6], u.username or str(u.id)))
            db.commit()
            await update.message.reply_text("✅ " + p[0]); return
    results = search_db(q)
    db.execute("INSERT INTO search_log (uid, username, first_name, query, found) VALUES (?,?,?,?,?)", (str(u.id), u.username or "", u.first_name or "", q, 1 if results else 0))
    db.commit()
    if not results:
        await update.message.reply_text("❌ Ничего не найдено", reply_markup=menu()); return
    if not is_admin(u): spend_credit(u.id)
    info = get_user(u.id)
    resp, pid = format_person(results[0])
    resp += "\n\n💰 Запросов: " + str(info[4] if info else 0)
    await update.message.reply_text(resp, parse_mode="Markdown", reply_markup=export_btn(pid))

async def photo_handler(update, context):
    if await chk_block(update, context): return
    u = update.effective_user
    register(u.id, u.username, u.first_name)
    info = get_user(u.id)
    if info and info[4] <= 0 and not is_admin(u):
        await update.message.reply_text("❌ Нет запросов!", reply_markup=menu()); return
    await update.message.reply_text("🔍 Обрабатываю...")
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    path = "/home/AzzaPrivetKaka/photo_" + str(u.id) + ".jpg"
    await file.download_to_drive(path)
    resp = photo_meta(path) + "\n\n🔍 *Поиск места:*"
    if not is_admin(u): spend_credit(u.id)
    db.execute("INSERT INTO search_log (uid, username, first_name, query, found) VALUES (?,?,?,?,?)", (str(u.id), u.username or "", u.first_name or "", "📸 Фото", 1))
    db.commit()
    info = get_user(u.id)
    resp += "\n\n💰 Запросов: " + str(info[4] if info else 0)
    await update.message.reply_text(resp, parse_mode="Markdown", reply_markup=photo_btns())
    if os.path.exists(path): os.remove(path)

# Роутер
async def text_router(update, context):
    u = update.effective_user
    if await chk_block(update, context): return
    for key in ["snos", "sherlock", "phone", "ip"]:
        if context.user_data.get("wait_" + key):
            context.user_data["wait_" + key] = False
            val = update.message.text.strip()
            if key == "snos":
                target = val.replace("@", "")
                if not target: await update.message.reply_text("Введите username!", reply_markup=menu()); return
                info = get_user(u.id)
                if info and info[4] <= 0 and not is_admin(u): await update.message.reply_text("❌ Нет запросов!", reply_markup=menu()); return
                if not is_admin(u): spend_credit(u.id)
                await update.message.reply_text("⏳ Обработка для @" + target + "...")
                asyncio.create_task(snos_task(context, u.id, target)); return
            elif key == "sherlock":
                nick = val.replace("@", "")
                if not nick: await update.message.reply_text("Введите username!", reply_markup=menu()); return
                info = get_user(u.id)
                if info and info[4] <= 0 and not is_admin(u): await update.message.reply_text("❌ Нет запросов!", reply_markup=menu()); return
                msg = await update.message.reply_text("🔎 Ищу...")
                sites = search_nick(nick)
                if not sites:
                    db.execute("INSERT INTO search_log (uid, username, first_name, query, found) VALUES (?,?,?,?,?)", (str(u.id), u.username or "", u.first_name or "", "🔎 "+nick, 0))
                    db.commit(); await msg.edit_text("❌ Не найдено"); return
                if not is_admin(u): spend_credit(u.id)
                db.execute("INSERT INTO search_log (uid, username, first_name, query, found) VALUES (?,?,?,?,?)", (str(u.id), u.username or "", u.first_name or "", "🔎 "+nick, len(sites)))
                db.commit()
                info = get_user(u.id)
                resp = "🔎 *Профили @" + nick + ":*\n\n"
                for s, url in sites: resp += "• [" + s + "](" + url + ")\n"
                resp += "\n💰 Запросов: " + str(info[4] if info else 0)
                await msg.edit_text(resp, parse_mode="Markdown", reply_markup=menu()); return
            elif key == "phone":
                if not val: await update.message.reply_text("Введите номер!", reply_markup=menu()); return
                info = get_user(u.id)
                if info and info[4] <= 0 and not is_admin(u): await update.message.reply_text("❌ Нет запросов!", reply_markup=menu()); return
                await update.message.reply_text("📱 Проверяю " + val + "...")
                ok, status = check_phone_db(val)
                if not is_admin(u): spend_credit(u.id)
                db.execute("INSERT INTO search_log (uid, username, first_name, query, found) VALUES (?,?,?,?,?)", (str(u.id), u.username or "", u.first_name or "", "📱 "+val, 1 if ok else 0))
                db.commit()
                info = get_user(u.id)
                icon = "✅" if ok else "❌" if ok is False else "⚠️"
                await update.message.reply_text(icon + " *" + status + "*\n📱 " + val + "\n\n💰 " + str(info[4] if info else 0), parse_mode="Markdown", reply_markup=menu()); return
            elif key == "ip":
                if not val: await update.message.reply_text("Введите IP!", reply_markup=menu()); return
                info = get_user(u.id)
                if info and info[4] <= 0 and not is_admin(u): await update.message.reply_text("❌ Нет запросов!", reply_markup=menu()); return
                await update.message.reply_text("🌍 Ищу " + val + "...")
                result = ip_lookup(val)
                if not is_admin(u): spend_credit(u.id)
                db.execute("INSERT INTO search_log (uid, username, first_name, query, found) VALUES (?,?,?,?,?)", (str(u.id), u.username or "", u.first_name or "", "🌍 "+val, 1 if result else 0))
                db.commit()
                info = get_user(u.id)
                if result: await update.message.reply_text(result + "\n\n💰 " + str(info[4] if info else 0), parse_mode="Markdown", reply_markup=menu())
                else: await update.message.reply_text("❌ Не найдено\n💰 " + str(info[4] if info else 0), reply_markup=menu())
                return
    await search_handler(update, context)

async def snos_task(context, uid, target):
    await asyncio.sleep(90)
    try: await context.bot.send_message(uid, "✅ *Подарок доставлен!*\n🎁 @" + target + "\n⏳ Активируется в течение суток.", parse_mode="Markdown", reply_markup=menu())
    except: pass

# Кнопки
async def button_router(update, context):
    q = update.callback_query
    await q.answer()
    if await chk_block(update, context): return
    d, u = q.data, q.from_user
    if d == "back":
        context.user_data.clear()
        await q.message.delete()
        await q.message.reply_sticker(sticker=STICKER)
        await q.message.reply_photo(WELCOME_IMG, caption=WELCOME, parse_mode="Markdown", reply_markup=menu())
    elif d == "search": context.user_data.clear(); await q.edit_message_caption(caption="🔍 Введите ФИО, телефон или email.", reply_markup=back())
    elif d == "photo": context.user_data.clear(); await q.edit_message_caption(caption="📸 Отправьте фото.", reply_markup=back())
    elif d == "phone": context.user_data["wait_phone"] = True; await q.edit_message_caption(caption="📱 Введите номер.\n💰 1 запрос.", parse_mode="Markdown", reply_markup=back())
    elif d == "ip": context.user_data["wait_ip"] = True; await q.edit_message_caption(caption="🌍 Введите IP.\n💰 1 запрос.", parse_mode="Markdown", reply_markup=back())
    elif d == "sherlock": context.user_data["wait_sherlock"] = True; await q.edit_message_caption(caption="🔎 Введите username.\n💰 1 запрос.", reply_markup=back())
    elif d == "snos":
        info = get_user(u.id); bal = info[4] if info else 0
        context.user_data["wait_snos"] = True
        await q.edit_message_caption(caption="🎁 *sn0s*\n\nВведите username.\n💰 1 запрос\n💰 У вас: " + str(bal), parse_mode="Markdown", reply_markup=back())
    elif d == "profile":
        info = get_user(u.id)
        if info: await q.edit_message_caption(caption="👤 *Профиль*\n\n🆔 `" + str(info[0]) + "`\n👤 @" + str(info[1] or "нет") + "\n📅 " + str(info[3]) + "\n💰 Запросы: " + str(info[4]), parse_mode="Markdown", reply_markup=back())
        else: await q.answer("Нажмите /start", show_alert=True)
    elif d == "buy": await q.edit_message_caption(caption="🛒 @kmosinter", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✉️ Купить", url="https://t.me/kmosinter")]]))
    elif d.startswith("export_"):
        try:
            pid = int(d.split("_")[1])
            row = db.execute("SELECT * FROM people WHERE id = ?", (pid,)).fetchone()
            if row:
                txt = "FIO: " + str(row[1]) + "\n@" + str(row[2]) + "\n" + str(row[3]) + "\n" + str(row[4]) + "\n" + str(row[5]) + "\n" + str(row[6]) + "\n\n" + str(row[7])
                fname = "/home/AzzaPrivetKaka/person_" + str(pid) + ".txt"
                with open(fname, "w") as f: f.write(txt)
                with open(fname, "rb") as f: await q.message.reply_document(document=f, filename=str(row[1]).replace(" ", "_") + ".txt")
                if os.path.exists(fname): os.remove(fname)
        except: pass

# Запуск
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("support", support_cmd))
    app.add_handler(CommandHandler("add", add_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("approve", approve_cmd))
    app.add_handler(CommandHandler("block", block_cmd))
    app.add_handler(CommandHandler("unblock", block_cmd))
    app.add_handler(CommandHandler("logi", logi_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, photo_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))
    app.add_handler(CallbackQueryHandler(button_router))
    print("Бот запущен!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()