import os
import asyncio
import sqlite3
import aiohttp
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton

# ---------------- НАСТРОЙКИ ----------------
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

# ---------------- COBALT API ЧЕРЕЗ GATEWAY ----------------
async def get_media_link(url):
    api_url = "https://cors.isomorphic-git.org/https://api.cobalt.tools/api/json"

    payload = {
        "url": url,
        "vQuality": "720",
        "isAudioOnly": False
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=40)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(api_url, json=payload, headers=headers) as response:
                if response.status != 200:
                    print("Cobalt status:", response.status)
                    return None

                data = await response.json()

                # статус stream или redirect
                if "url" in data:
                    return data["url"]

    except Exception as e:
        print("Cobalt error:", e)

    return None


# ---------------- СКАЧИВАНИЕ ФАЙЛА ----------------
async def download_file(url, filename):
    try:
        timeout = aiohttp.ClientTimeout(total=60)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with open(filename, "wb") as f:
                        f.write(await resp.read())
                    return True
    except Exception as e:
        print("Download error:", e)

    return False


# ---------------- START ----------------
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()

    text = (
        "🔥 **Универсальный загрузчик видео**\n\n"
        "📌 Отправь ссылку — получишь файл.\n\n"
        "Поддержка:\n"
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


# ---------------- ОБРАБОТКА ССЫЛОК ----------------
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):

    status = await message.answer("⏳ Получаю видео...")

    url = message.text.strip()
    filename = f"{message.from_user.id}_{int(datetime.now().timestamp())}.mp4"

    try:
        media_url = await get_media_link(url)

        if not media_url:
            return await status.edit_text("❌ Не удалось получить видео. Возможно сервис временно недоступен.")

        success = await download_file(media_url, filename)

        if not success:
            return await status.edit_text("❌ Ошибка скачивания файла.")

        await bot.send_video(
            message.chat.id,
            FSInputFile(filename),
            caption=f"✅ Готово!\n❤️ {BOT_USERNAME}"
        )

        await status.delete()

    except Exception as e:
        print("Main error:", e)
        await status.edit_text("❌ Произошла ошибка.")

    finally:
        if os.path.exists(filename):
            os.remove(filename)


# ---------------- ЗАПУСК ----------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
