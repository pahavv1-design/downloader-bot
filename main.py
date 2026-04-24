import os
import asyncio
import sqlite3
import aiohttp
import json
import re
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import yt_dlp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, LabeledPrice, PreCheckoutQuery

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

# --- СПЕЦИАЛЬНЫЙ СКРАПЕР PINTEREST ---
async def get_pinterest_media(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        # 1. Разворачиваем короткую ссылку
        async with session.get(url, allow_redirects=True) as response:
            full_url = str(response.url)
            html = await response.text()
        
        # 2. Ищем данные в скрипте __PWS_DATA__
        soup = BeautifulSoup(html, 'html.parser')
        script_tag = soup.find("script", id="__PWS_DATA__")
        
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                # Копаем глубоко в JSON Пинтереста, чтобы найти MP4
                pins = data.get('props', {}).get('initialProps', {}).get('data', {}).get('pin', {})
                video_data = pins.get('videos', {}).get('video_list', {})
                
                # Пробуем найти V_720P или V_HLSV3 (но нам нужен именно mp4)
                for key in ['V_720P', 'V_480P', 'V_360P']:
                    if key in video_data:
                        return video_data[key].get('url'), "video"
            except: pass

        # 3. Запасной вариант: ищем через мета-теги
        video_meta = soup.find("meta", property="og:video:secure_url") or soup.find("meta", property="og:video")
        if video_meta: return video_meta['content'], "video"
        
        image_meta = soup.find("meta", property="og:image")
        if image_meta: return image_meta['content'], "image"
        
    return None, None

# --- ФУНКЦИЯ ЗАГРУЗКИ ФАЙЛА ---
async def download_file(url, path):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            if resp.status == 200:
                with open(path, 'wb') as f:
                    f.write(await resp.read())
                return True
    return False

# --- ПРИВЕТСТВИЕ ---
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()
    text = (
        "❤️ **Привет! Это бот для скачивания видео/фото/аудио из популярных социальных сетей.**\n\n"
        "🧐 **Как пользоваться:**\n"
        "1. Зайди в одну из соцсетей.\n"
        "2. Выбери видео или фото.\n"
        "3. Скопируй ссылку.\n"
        "4. Отправь её мне!\n\n"
        "🔗 **Поддерживаю:** YouTube Shorts, Instagram, TikTok, Pinterest.\n"
        "⚠️ **Лимит:** до 50 МБ.\n\n"
        f"{BOT_USERNAME}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Premium", callback_data="buy_prem")],
        [InlineKeyboardButton(text="👨‍💻 Поддержка", url=f"tg://user?id={ADMIN_ID}")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- ОБРАБОТКА ССЫЛОК ---
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):
    # Обязательная подписка (ОП)
    ch_id = cur.execute("SELECT value FROM settings WHERE key='ch_id'").fetchone()
    if ch_id:
        try:
            m = await bot.get_chat_member(ch_id[0], message.from_user.id)
            if m.status == "left":
                url = cur.execute("SELECT value FROM settings WHERE key='ch_url'").fetchone()[0]
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=url)]])
                return await message.answer("❌ Сначала подпишись на канал!", reply_markup=kb)
        except: pass

    status = await message.answer("⏳")
    url = message.text
    file_path = f"downloads/{message.from_user.id}_{datetime.now().timestamp()}"

    try:
        # Если это Pinterest
        if "pin.it" in url or "pinterest.com" in url:
            direct_url, media_type = await get_pinterest_media(url)
            if not direct_url:
                return await status.edit_text("❌ Не удалось найти видео по этой ссылке.")
            
            ext = "mp4" if media_type == "video" else "jpg"
            file_path += f".{ext}"
            
            if await download_file(direct_url, file_path):
                if media_type == "video":
                    await bot.send_video(message.chat.id, video=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")
                    await bot.send_audio(message.chat.id, audio=FSInputFile(file_path), caption=f"🎵 Звук\n❤️ {BOT_USERNAME}")
                else:
                    await bot.send_photo(message.chat.id, photo=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")
            else: raise Exception("Download failed")

        # Остальные соцсети (TikTok, YT, Insta) через yt-dlp
        else:
            file_path += ".mp4"
            ydl_opts = {'format': 'best[ext=mp4]/best', 'outtmpl': file_path, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, ydl.download, [url])
            
            await bot.send_video(message.chat.id, video=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")
            await bot.send_audio(message.chat.id, audio=FSInputFile(file_path), caption=f"🎵 Звук\n❤️ {BOT_USERNAME}")

        if os.path.exists(file_path): os.remove(file_path)
        await status.delete()

    except Exception as e:
        print(f"Error: {e}")
        await status.edit_text("❌ Ошибка загрузки. Попробуйте другую ссылку.")
        if os.path.exists(file_path): os.remove(file_path)

# --- АДМИНКА ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def adm(message: Message):
    cur.execute("SELECT COUNT(*) FROM users")
    await message.answer(f"📊 Юзеров: {cur.fetchone()[0]}\n/setchannel ID URL\n/send Текст")

@dp.message(Command("setchannel"), F.from_user.id == ADMIN_ID)
async def setch(message: Message, command: CommandObject):
    try:
        args = command.args.split()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('ch_id', ?), ('ch_url', ?)", (args[0], args[1]))
        db.commit()
        await message.answer("✅ Готово")
    except: await message.answer("Формат: `/setchannel ID URL`")

@dp.message(Command("send"), F.from_user.id == ADMIN_ID)
async def sendall(message: Message):
    txt = message.text.replace("/send ", "")
    cur.execute("SELECT id FROM users")
    for u in cur.fetchall():
        try: await bot.send_message(u[0], txt)
        except: pass

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
