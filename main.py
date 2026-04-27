import os
import asyncio
import sqlite3
import aiohttp
import re
import random
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = "@HoardVideoBot"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# ---------------- БАЗА ----------------
db = sqlite3.connect("bot.db")
cur = db.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY)")
db.commit()

# -------- СПИСОК БЕСПЛАТНЫХ ПРОКСИ --------
PROXIES = [
    "http://51.158.68.68:8811",
    "http://51.79.144.52:3128",
    "http://163.172.182.164:3128",
    "http://8.219.97.248:80",
    "http://20.111.54.16:8123",
]

# -------- ПОЛУЧЕНИЕ PINTEREST VIDEO --------
async def get_pinterest_video(url):
    proxy = random.choice(PROXIES)

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=20)

        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:

            # Разворачиваем pin.it
            async with session.get(url, allow_redirects=True, proxy=proxy) as resp:
                final_url = str(resp.url)

            final_url = final_url.replace("www.pinterest.com", "m.pinterest.com")

            async with session.get(final_url, proxy=proxy) as resp:
                html = await resp.text()

            # Ищем mp4
            match = re.search(r'https://v\d\.pinimg\.com/videos/.*?\.mp4', html)

            if match:
                return match.group(0)

    except Exception as e:
        print("Proxy error:", e)

    return None


# -------- СКАЧИВАНИЕ --------
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


# -------- START --------
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()

    text = (
        "🔥 **Pinterest Downloader (Proxy Mode)**\n\n"
        "📌 Отправь ссылку на Pinterest — попробуем обойти блокировку.\n\n"
        "✅ Работает через прокси\n"
        f"{BOT_USERNAME}"
    )

    await message.answer(text, parse_mode="Markdown")


# -------- ОБРАБОТКА --------
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):

    status = await message.answer("⏳ Пытаюсь через прокси...")

    url = message.text.strip()
    filename = f"{message.from_user.id}_{int(datetime.now().timestamp())}.mp4"

    try:
        video_url = await get_pinterest_video(url)

        if not video_url:
            return await status.edit_text("❌ Не удалось получить видео через прокси.")

        success = await download_file(video_url, filename)

        if not success:
            return await status.edit_text("❌ Ошибка скачивания файла.")

        await bot.send_video(message.chat.id, FSInputFile(filename))
        await status.delete()

    except Exception as e:
        print(e)
        await status.edit_text("❌ Ошибка.")

    finally:
        if os.path.exists(filename):
            os.remove(filename)


async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
