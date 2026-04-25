import os
import asyncio
import sqlite3
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
cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
db.commit()

# --- ФУНКЦИЯ ЗАГРУЗКИ ЧЕРЕЗ COBALT API (Замена ffmpeg) ---
async def get_media_via_api(url):
    api_url = "https://api.cobalt.tools/api/json"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    payload = {
        "url": url,
        "vQuality": "720", # Качество видео
        "isAudioOnly": False
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, headers=headers) as response:
                data = await response.json()
                if data.get("status") == "stream" or data.get("status") == "picker":
                    return data.get("url") # Прямая ссылка на файл
                elif data.get("status") == "redirect":
                    return data.get("url")
    except Exception as e:
        print(f"API Error: {e}")
    return None

# --- СКАЧИВАНИЕ ФАЙЛА НА ХОСТИНГ ---
async def download_file(url, path):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=60) as resp:
                if resp.status == 200:
                    with open(path, 'wb') as f:
                        f.write(await resp.read())
                    return True
    except: pass
    return False

# --- КРАСИВОЕ ПРИВЕТСТВИЕ ---
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()
    
    welcome_text = (
        "❤️ **Привет! Я твой личный помощник по загрузке медиа!**\n\n"
        "🧐 **Как пользоваться:**\n"
        "1️⃣ Открой любую соцсеть.\n"
        "2️⃣ Скопируй ссылку на видео или фото.\n"
        "3️⃣ Пришли её мне, и я отправлю тебе файл!\n\n"
        "🔗 **Я поддерживаю:**\n"
        "• YouTube Shorts 📺\n"
        "• Instagram Reels 📸\n"
        "• TikTok 🎵\n"
        "• Pinterest (Видео и Фото) 📌\n\n"
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
    # Проверка обязательной подписки
    ch_id_data = cur.execute("SELECT value FROM settings WHERE key='ch_id'").fetchone()
    if ch_id_data:
        try:
            m = await bot.get_chat_member(chat_id=ch_id_data[0], user_id=message.from_user.id)
            if m.status in ["left", "kicked"]:
                url = cur.execute("SELECT value FROM settings WHERE key='ch_url'").fetchone()[0]
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=url)]])
                return await message.answer("❌ **Сначала подпишись на канал!**", reply_markup=kb, parse_mode="Markdown")
        except: pass

    status = await message.answer("⏳ **Загрузка видео...**", parse_mode="Markdown")
    url = message.text.strip()
    
    # Пытаемся получить прямую ссылку через API
    direct_url = await get_media_via_api(url)
    
    if not direct_url:
        return await status.edit_text("❌ **Ошибка:** Не удалось получить файл. Ссылка может быть приватной или неверной.")

    file_path = f"downloads/{message.from_user.id}_{int(datetime.now().timestamp())}.mp4"

    try:
        # Скачиваем файл на хостинг, чтобы отправить его от имени бота
        if await download_file(direct_url, file_path):
            await bot.send_video(
                message.chat.id, 
                video=FSInputFile(file_path), 
                caption=f"✅ **Готово!**\n❤️ {BOT_USERNAME}",
                parse_mode="Markdown"
            )
            await status.delete()
        else:
            await status.edit_text("❌ Ошибка при скачивании файла.")
    except Exception as e:
        print(f"Error: {e}")
        await status.edit_text("❌ Произошла ошибка при отправке.")
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)

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
        await message.answer("✅ Канал установлен.")
    except: await message.answer("Формат: `/setchannel -100xxx https://t.me/xxx`")

@dp.message(Command("send"), F.from_user.id == ADMIN_ID)
async def sendall(message: Message):
    txt = message.text.replace("/send ", "")
    cur.execute("SELECT id FROM users")
    for u in cur.fetchall():
        try: 
            await bot.send_message(u[0], txt)
            await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Рассылка завершена.")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
