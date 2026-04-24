import os
import asyncio
import sqlite3
import aiohttp
import json
from bs4 import BeautifulSoup
from datetime import datetime
import yt_dlp
from aiogram import Bot, Dispatcher, F, types
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

# --- СКРАПЕР ДЛЯ PINTEREST (Видео + Фото) ---
async def get_pinterest_content(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"}
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, allow_redirects=True) as response:
            html = await response.text()
        
        soup = BeautifulSoup(html, 'html.parser')
        script_tag = soup.find("script", id="__PWS_DATA__")
        
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                pin_data = data.get('props', {}).get('initialProps', {}).get('data', {}).get('pin', {})
                
                # Пробуем найти видео
                videos = pin_data.get('videos', {}).get('video_list', {})
                for res in ['V_720P', 'V_480P', 'V_360P']:
                    if res in videos:
                        return videos[res].get('url'), "video"
                
                # Если видео нет, ищем фото (оригинал)
                images = pin_data.get('images', {}).get('orig', {})
                if images:
                    return images.get('url'), "photo"
            except: pass

        # Запасной вариант через мета-теги
        v_meta = soup.find("meta", property="og:video:secure_url") or soup.find("meta", property="og:video")
        if v_meta: return v_meta['content'], "video"
        
        img_meta = soup.find("meta", property="og:image")
        if img_meta: return img_meta['content'], "photo"
        
    return None, None

# --- ЗАГРУЗКА ---
async def download_file(url, path):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            if r.status == 200:
                with open(path, 'wb') as f: f.write(await r.read())
                return True
    return False

# --- ПРИВЕТСТВИЕ ---
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()
    text = (
        "❤️ **Привет! Я бот для скачивания из соцсетей.**\n\n"
        "Отправь мне ссылку на:\n"
        "• YouTube Shorts\n• TikTok\n• Instagram\n• Pinterest\n\n"
        "🚀 **Всё бесплатно!** Лимит файла: 50 МБ.\n"
        f"{BOT_USERNAME}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👨‍💻 Поддержка", url=f"tg://user?id={ADMIN_ID}")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- ОБРАБОТКА ССЫЛОК ---
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):
    # Проверка Обязательной Подписки
    ch_id = cur.execute("SELECT value FROM settings WHERE key='ch_id'").fetchone()
    if ch_id:
        try:
            m = await bot.get_chat_member(ch_id[0], message.from_user.id)
            if m.status == "left":
                url = cur.execute("SELECT value FROM settings WHERE key='ch_url'").fetchone()[0]
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=url)]])
                return await message.answer("❌ Подпишитесь на канал, чтобы скачивать видео!", reply_markup=kb)
        except: pass

    status = await message.answer("⏳")
    url = message.text
    file_path = f"downloads/{message.from_user.id}_{int(datetime.now().timestamp())}"

    try:
        # ПИНТЕРЕСТ
        if "pin.it" in url or "pinterest.com" in url:
            direct_url, m_type = await get_pinterest_content(url)
            if not direct_url: return await status.edit_text("❌ Не нашел медиа по ссылке.")
            
            file_path += ".mp4" if m_type == "video" else ".jpg"
            if await download_file(direct_url, file_path):
                if m_type == "video":
                    await bot.send_video(message.chat.id, video=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")
                    await bot.send_audio(message.chat.id, audio=FSInputFile(file_path), caption=f"🎵 Звук\n❤️ {BOT_USERNAME}")
                else:
                    await bot.send_photo(message.chat.id, photo=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")
            else: raise Exception("Err")

        # ОСТАЛЬНОЕ (TikTok, YT, Insta)
        else:
            file_path += ".mp4"
            ydl_opts = {'format': 'best[ext=mp4]/best', 'outtmpl': file_path, 'quiet': True, 'max_filesize': 50*1024*1024}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, ydl.download, [url])
            
            await bot.send_video(message.chat.id, video=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")
            await bot.send_audio(message.chat.id, audio=FSInputFile(file_path), caption=f"🎵 Звук из видео\n❤️ {BOT_USERNAME}")

        if os.path.exists(file_path): os.remove(file_path)
        await status.delete()

    except Exception as e:
        await status.edit_text("❌ Ошибка или файл более 50 МБ.")
        if os.path.exists(file_path): os.remove(file_path)

# --- АДМИНКА ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def adm(message: Message):
    cur.execute("SELECT COUNT(*) FROM users")
    await message.answer(f"📊 Юзеров: {cur.fetchone()[0]}\n\nКоманды:\n/setchannel ID URL\n/send Текст")

@dp.message(Command("setchannel"), F.from_user.id == ADMIN_ID)
async def setch(message: Message, command: CommandObject):
    try:
        args = command.args.split()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('ch_id', ?), ('ch_url', ?)", (args[0], args[1]))
        db.commit()
        await message.answer("✅ Канал ОП установлен")
    except: await message.answer("Ошибка. Формат: `/setchannel -100xxx https://t.me/...`")

@dp.message(Command("send"), F.from_user.id == ADMIN_ID)
async def sendall(message: Message):
    txt = message.text.replace("/send ", "")
    cur.execute("SELECT id FROM users")
    users = cur.fetchall()
    for u in users:
        try:
            await bot.send_message(u[0], txt)
            await asyncio.sleep(0.05)
        except: pass
    await message.answer("✅ Рассылка завершена")

async def main():
    if not os.path.exists('downloads'): os.makedirs('downloads')
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
