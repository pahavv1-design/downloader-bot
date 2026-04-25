import os
import asyncio
import sqlite3
import yt_dlp
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = "@HoardVideoBot" 

DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR): os.makedirs(DATA_DIR)
DB_PATH = os.path.join(DATA_DIR, "bot_data.db")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, prem_until DATETIME)")
cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
db.commit()

# --- РАЗВОРАЧИВАНИЕ КОРОТКИХ ССЫЛОК ---
async def expand_url(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=10) as response:
                return str(response.url)
    except:
        return url

# --- ЗАГРУЗКА МЕДИА ---
async def download_media(url, user_id):
    if not os.path.exists('downloads'): os.makedirs('downloads')
    
    # Разворачиваем pin.it
    full_url = await expand_url(url)
    
    timestamp = int(datetime.now().timestamp())
    out_tmpl = f"downloads/{user_id}_{timestamp}.%(ext)s"
    
    # ИСПРАВЛЕННЫЙ ФОРМАТ: 'best' — самый надежный для Pinterest
    ydl_opts = {
        'format': 'best', 
        'outtmpl': out_tmpl,
        'quiet': True,
        'no_warnings': True,
        'headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        },
        'noplaylist': True,
    }

    def extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(full_url, download=True)
            return ydl.prepare_filename(info)

    loop = asyncio.get_event_loop()
    try:
        file_path = await loop.run_in_executor(None, extract)
        return file_path
    except Exception as e:
        print(f"Ошибка YT-DLP: {e}")
        return None

# --- КРАСИВОЕ ПРИВЕТСТВИЕ ---
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()
    
    welcome_text = (
        "❤️ **Привет! Это бот для скачивания видео/фото/аудио из популярных социальных сетей.**\n\n"
        "🧐 **Как пользоваться:**\n"
        "1️⃣ Зайди в соцсеть (TikTok, Instagram и др.).\n"
        "2️⃣ Выбери интересное видео или фото.\n"
        "3️⃣ Нажми кнопку **«Скопировать ссылку»**.\n"
        "4️⃣ Отправь ссылку мне и жди файл!\n\n"
        "🔗 **Бот поддерживает:**\n"
        "• YouTube Shorts 📺\n"
        "• Instagram Reels 📸\n"
        "• TikTok 🎵\n"
        "• Pinterest 📌\n\n"
        f"👤 {BOT_USERNAME}"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Premium", callback_data="buy_prem")],
        [InlineKeyboardButton(text="👨‍💻 Поддержка", url=f"tg://user?id={ADMIN_ID}")]
    ])
    await message.answer(welcome_text, reply_markup=kb, parse_mode="Markdown")

# --- ОБРАБОТКА ССЫЛОК ---
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):
    # Проверка подписки (ОП)
    ch_id_data = cur.execute("SELECT value FROM settings WHERE key='ch_id'").fetchone()
    if ch_id_data:
        try:
            m = await bot.get_chat_member(chat_id=ch_id_data[0], user_id=message.from_user.id)
            if m.status in ["left", "kicked"]:
                url = cur.execute("SELECT value FROM settings WHERE key='ch_url'").fetchone()[0]
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=url)]])
                return await message.answer("❌ Сначала подпишись на канал!", reply_markup=kb)
        except: pass

    status = await message.answer("⏳ **Загрузка началась...**", parse_mode="Markdown")
    url = message.text.strip()
    file_path = None

    try:
        file_path = await download_media(url, message.from_user.id)
        
        if not file_path or not os.path.exists(file_path):
            return await status.edit_text("❌ Не удалось скачать файл. Ссылка может быть битой или приватной.")

        ext = file_path.lower()
        # Отправка видео
        if ext.endswith(('.mp4', '.mov', '.webm', '.mkv')):
            await bot.send_video(
                message.chat.id, 
                video=FSInputFile(file_path), 
                caption=f"✅ **Готово!**\n❤️ {BOT_USERNAME}",
                parse_mode="Markdown"
            )
        # Отправка фото
        elif ext.endswith(('.jpg', '.jpeg', '.png', '.webp', '.gif')):
            await bot.send_photo(
                message.chat.id, 
                photo=FSInputFile(file_path), 
                caption=f"✅ **Готово!**\n❤️ {BOT_USERNAME}",
                parse_mode="Markdown"
            )
        else:
            await bot.send_document(message.chat.id, document=FSInputFile(file_path))

        await status.delete()

    except Exception as e:
        print(f"Error: {e}")
        await status.edit_text("❌ Произошла ошибка. Попробуйте еще раз позже.")
    
    finally:
        # Удаление временного файла
        if file_path and os.path.exists(file_path):
            try: os.remove(file_path)
            except: pass

# --- АДМИНКА ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def adm(message: Message):
    cur.execute("SELECT COUNT(*) FROM users")
    count = cur.fetchone()[0]
    await message.answer(f"📊 Юзеров: {count}\n\n/setchannel ID URL\n/send Текст")

@dp.message(Command("setchannel"), F.from_user.id == ADMIN_ID)
async def setch(message: Message, command: CommandObject):
    try:
        args = command.args.split()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('ch_id', ?), ('ch_url', ?)", (args[0], args[1]))
        db.commit()
        await message.answer("✅ Канал для подписки успешно установлен.")
    except: await message.answer("Формат: `/setchannel -100 ID URL`")

@dp.message(Command("send"), F.from_user.id == ADMIN_ID)
async def sendall(message: Message):
    txt = message.text.replace("/send ", "")
    cur.execute("SELECT id FROM users")
    for u in cur.fetchall():
        try: await bot.send_message(u[0], txt)
        except: pass
    await message.answer("✅ Рассылка завершена.")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
