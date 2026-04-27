import os
import asyncio
import sqlite3
import aiohttp
import re
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = "@HoardVideoBot"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ---
db = sqlite3.connect("bot.db")
cur = db.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
db.commit()

# ---------- PINTEREST PARSER ДЛЯ BOTHOST ----------
async def get_pinterest_video(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    }

    try:
        async with aiohttp.ClientSession(headers=headers) as session:

            # Разворачиваем pin.it
            async with session.get(url, allow_redirects=True) as resp:
                final_url = str(resp.url)

            # Меняем на мобильную версию
            final_url = final_url.replace("www.pinterest.com", "m.pinterest.com")

            async with session.get(final_url) as resp:
                html = await resp.text()

            # Ищем прямую mp4 ссылку
            match = re.search(r'https://v\d\.pinimg\.com/videos/.*?\.mp4', html)

            if match:
                return match.group(0)

    except Exception as e:
        print("Pinterest error:", e)

    return None


# ---------- СКАЧИВАНИЕ ----------
async def download_file(url, filename):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with open(filename, "wb") as f:
                        f.write(await resp.read())
                    return True
    except:
        pass
    return False


# ---------- START ----------
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()

    text = (
        "❤️ **Привет! Я бот для скачивания видео.**\n\n"
        "📌 Отправь ссылку и я загружу файл.\n\n"
        "🔗 Поддержка:\n"
        "• YouTube Shorts 📺\n"
        "• Instagram Reels 📸\n"
        "• TikTok 🎵\n"
        "• Pinterest 📌\n\n"
        f"{BOT_USERNAME}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💻 Поддержка", url=f"tg://user?id={ADMIN_ID}")]
    ])

    await message.answer(text, parse_mode="Markdown", reply_markup=kb)


# ---------- ОБРАБОТКА ССЫЛОК ----------
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):

    status = await message.answer("⏳ Загружаю...")

    url = message.text.strip()
    filename = f"{message.from_user.id}_{int(datetime.now().timestamp())}.mp4"

    try:

        # Если Pinterest
        if "pinterest" in url or "pin.it" in url:

            video_url = await get_pinterest_video(url)

            if not video_url:
                return await status.edit_text("❌ Видео не найдено. Возможно это фото или приватный пин.")

            success = await download_file(video_url, filename)

            if not success:
                return await status.edit_text("❌ Ошибка загрузки файла.")

            await bot.send_video(message.chat.id, FSInputFile(filename))
            await status.delete()

        else:
            await status.edit_text("⚠️ Сейчас версия для Bothost поддерживает только Pinterest.")

    except Exception as e:
        print(e)
        await status.edit_text("❌ Произошла ошибка.")

    finally:
        if os.path.exists(filename):
            os.remove(filename)


# ---------- ЗАПУСК ----------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
