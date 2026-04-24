import os
import asyncio
import sqlite3
import aiohttp
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

# --- ФУНКЦИЯ РАЗВОРАЧИВАНИЯ ССЫЛОК ---
async def resolve_url(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True, timeout=10) as response:
                return str(response.url)
    except: return url

# --- СКАЧИВАНИЕ ---
def download_media(url, user_id):
    tmp_dir = 'downloads'
    if not os.path.exists(tmp_dir): os.makedirs(tmp_dir)

    # Специальные настройки для обхода защиты Pinterest и Instagram
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{tmp_dir}/{user_id}_%(id)s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'referer': 'https://www.pinterest.com/',
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        
        # Проверка: видео или фото
        is_video = info.get('ext') in ['mp4', 'mkv', 'webm', 'mov']
        size = os.path.getsize(path) / (1024 * 1024)
        
        return path, size, is_video

# --- ПРИВЕТСТВИЕ ---
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()
    
    text = (
        "❤️ **Привет! Это бот для скачивания видео/фото/аудио из популярных социальных сетей.**\n\n"
        "🧐 **Как пользоваться:**\n"
        "1. Зайди в одну из социальных сетей.\n"
        "2. Выбери интересное видео/фото.\n"
        "3. Нажми кнопку «Скопировать ссылку».\n"
        "4. Отправь ссылку боту и получи скачанный файл!\n\n"
        "🔗 **Бот может скачивать из:**\n"
        "• YouTube Shorts\n• Instagram\n• TikTok\n• Pinterest\n\n"
        "⚠️ **Внимание:** Лимит бесплатной загрузки — **50 МБ**.\n"
        "💎 Для поддержки проекта купите Premium.\n\n"
        f"{BOT_USERNAME}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить Premium", callback_data="buy_prem")],
        [InlineKeyboardButton(text="👨‍💻 Поддержка", url=f"tg://user?id={ADMIN_ID}")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- ОБРАБОТКА ССЫЛОК ---
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):
    # Проверка ОП (подписки)
    ch_id = cur.execute("SELECT value FROM settings WHERE key='ch_id'").fetchone()
    if ch_id:
        try:
            member = await bot.get_chat_member(ch_id[0], message.from_user.id)
            if member.status == "left":
                url = cur.execute("SELECT value FROM settings WHERE key='ch_url'").fetchone()[0]
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=url)]])
                return await message.answer("❌ Сначала подпишись на канал!", reply_markup=kb)
        except: pass

    # Лимит теперь 50 МБ для всех (максимум Telegram)
    limit = 50
    status = await message.answer("⏳")

    try:
        url = await resolve_url(message.text)
        
        loop = asyncio.get_event_loop()
        path, size, is_video = await loop.run_in_executor(None, download_media, url, message.from_user.id)
        
        if size > limit:
            if os.path.exists(path): os.remove(path)
            return await status.edit_text(f"⚠️ Файл слишком большой ({size:.1f} МБ).\nМаксимальный лимит Telegram: 50 МБ.")

        if is_video:
            # Отправляем видео
            await bot.send_video(message.chat.id, video=FSInputFile(path), caption=f"❤️ {BOT_USERNAME}")
            # Звуковая фишка (пробуем вытащить звук)
            try:
                await bot.send_audio(message.chat.id, audio=FSInputFile(path), caption=f"🎵 Звук из видео\n❤️ {BOT_USERNAME}")
            except: pass
        else:
            await bot.send_photo(message.chat.id, photo=FSInputFile(path), caption=f"❤️ {BOT_USERNAME}")

        if os.path.exists(path): os.remove(path)
        await status.delete()

    except Exception as e:
        await status.edit_text("❌ Ошибка загрузки. Возможно, это приватное видео или ссылка устарела.")

# --- ОПЛАТА И АДМИНКА ---
@dp.callback_query(F.data == "buy_prem")
async def buy(call: types.CallbackQuery):
    await bot.send_invoice(call.from_user.id, "Premium", "Поддержка проекта", "p", "XTR", [LabeledPrice(label="Оплата", amount=50)])

@dp.pre_checkout_query()
async def q(q: PreCheckoutQuery): await bot.answer_pre_checkout_query(q.id, ok=True)

@dp.message(F.successful_payment)
async def ok(message: Message):
    date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("UPDATE users SET prem_until = ? WHERE id = ?", (date, message.from_user.id))
    db.commit()
    await message.answer(f"🎉 Спасибо за поддержку! Premium активен до {date}!")

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
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
