import os
import asyncio
import sqlite3
from datetime import datetime, timedelta
import yt_dlp
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command, CommandObject
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile, LabeledPrice, PreCheckoutQuery

# --- НАСТРОЙКИ ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
BOT_USERNAME = "@HoardVideoBot"

# Путь к базе данных в защищенную папку (как просит Bothost)
DATA_DIR = "/app/data"
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
DB_PATH = os.path.join(DATA_DIR, "bot_data.db")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
db = sqlite3.connect(DB_PATH)
cur = db.cursor()
cur.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, prem_until DATETIME)")
db.commit()

# --- ФУНКЦИЯ СКАЧИВАНИЯ (БЕЗ FFMPEG) ---
def download_media(url, user_id):
    # Папка для временных файлов
    tmp_dir = 'downloads'
    if not os.path.exists(tmp_dir): os.makedirs(tmp_dir)

    # 1. Скачиваем ВИДЕО
    v_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': f'{tmp_dir}/{user_id}_v.%(ext)s',
        'quiet': True, 'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(v_opts) as ydl:
        v_info = ydl.extract_info(url, download=True)
        v_path = ydl.prepare_filename(v_info)
        v_size = os.path.getsize(v_path) / (1024 * 1024)

    # 2. Скачиваем АУДИО (в оригинальном формате m4a/mp3 без конвертации)
    a_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': f'{tmp_dir}/{user_id}_a.%(ext)s',
        'quiet': True, 'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(a_opts) as ydl:
        a_info = ydl.extract_info(url, download=True)
        a_path = ydl.prepare_filename(a_info)
    
    return v_path, a_path, v_size

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_prem_status(user_id):
    cur.execute("SELECT prem_until FROM users WHERE id = ?", (user_id,))
    res = cur.fetchone()
    if res and res[0]:
        until = datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
        if until > datetime.now(): return until
    return None

# --- КОМАНДА START ---
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()
    
    prem = get_prem_status(message.from_user.id)
    status = f"💎 Premium до: {prem.strftime('%d.%m.%Y')}" if prem else "🆓 Статус: Бесплатный (30МБ)"
    
    text = (
        "❤️ **Привет! Это бот для скачивания видео/фото/аудио из популярных социальных сетей.**\n\n"
        "🧐 **Как пользоваться:**\n"
        "1. Зайди в одну из социальных сетей.\n"
        "2. Выбери интересное видео/фото.\n"
        "3. Нажми кнопку «Скопировать ссылку».\n"
        "4. Отправь ссылку боту и получи скачанный файл!\n\n"
        "🔗 **Бот может скачивать из:**\n"
        "• YouTube Shorts\n• Instagram\n• TikTok\n• Pinterest\n\n"
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
    is_prem = get_prem_status(message.from_user.id)
    limit = 50 if is_prem else 30
    
    status_emoji = await message.answer("⏳")

    try:
        loop = asyncio.get_event_loop()
        v_path, a_path, v_size = await loop.run_in_executor(None, download_media, message.text, message.from_user.id)
        
        if v_size > limit:
            for f in [v_path, a_path]: 
                if os.path.exists(f): os.remove(f)
            return await status_emoji.edit_text(f"⚠️ Видео весит {v_size:.1f} МБ.\nВаш лимит: {limit} МБ.\n\n💎 Купите Premium для лимита 50 МБ!")

        # Отправка видео
        await bot.send_video(message.chat.id, video=FSInputFile(v_path), caption=f"❤️ {BOT_USERNAME}")
        # Отправка аудио
        await bot.send_audio(message.chat.id, audio=FSInputFile(a_path), caption=f"❤️ {BOT_USERNAME}")

        # Удаление файлов
        for f in [v_path, a_path]: 
            if os.path.exists(f): os.remove(f)
        await status_emoji.delete()

    except Exception as e:
        await status_emoji.edit_text("❌ Видео не найдено или ссылка защищена.")

# --- ПЛАТЕЖИ И АДМИНКА ---
@dp.callback_query(F.data == "buy_prem")
async def pay(call: types.CallbackQuery):
    await bot.send_invoice(
        chat_id=call.from_user.id, title="Premium доступ", description="Лимит 50МБ на 30 дней",
        payload="p", currency="XTR", prices=[LabeledPrice(label="Оплата", amount=50)]
    )

@dp.pre_checkout_query()
async def q(q: PreCheckoutQuery): await bot.answer_pre_checkout_query(q.id, ok=True)

@dp.message(F.successful_payment)
async def ok(message: Message):
    date = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("UPDATE users SET prem_until = ? WHERE id = ?", (date, message.from_user.id))
    db.commit()
    await message.answer("🎉 Premium активирован!")

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def adm(message: Message):
    cur.execute("SELECT COUNT(*) FROM users")
    await message.answer(f"📊 Юзеров: {cur.fetchone()[0]}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
