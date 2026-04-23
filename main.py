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
db.commit()

# --- ФУНКЦИЯ ЗАГРУЗКИ ---
def download_media(url, user_id):
    tmp_dir = 'downloads'
    if not os.path.exists(tmp_dir): os.makedirs(tmp_dir)

    # Настройки yt-dlp для работы с фото и видео
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{tmp_dir}/{user_id}_%(title).50s.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'add_header': ['User-Agent: Mozilla/5.0'], # Чтобы соцсети не банили
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        file_path = ydl.prepare_filename(info)
        
        # Вытягиваем описание (фишка для репостеров)
        description = info.get('description') or info.get('title') or ""
        
        # Если это Pinterest и скачалось как фото (небольшой размер или формат картинки)
        is_video = info.get('ext') in ['mp4', 'mkv', 'webm', 'mov']
        
        return file_path, is_video, description, os.path.getsize(file_path) / (1024 * 1024)

# --- ПРИВЕТСТВИЕ ---
@dp.message(Command("start"))
async def start(message: Message):
    cur.execute("INSERT OR IGNORE INTO users (id) VALUES (?)", (message.from_user.id,))
    db.commit()
    
    text = (
        "❤️ **Привет! Я твой личный загрузчик медиа.**\n\n"
        "✨ **Что я умею:**\n"
        "• Качать видео из TikTok, Instagram, Shorts\n"
        "• Сохранять фото и видео из Pinterest\n"
        "• Вырезать музыку из любого ролика\n"
        "• **New!** Копировать описание поста для ваших репостов\n\n"
        "💡 **Лимиты:**\n"
        "— Вам доступно до **30 МБ** на один файл.\n"
        "— Для видео до 50 МБ и быстрой загрузки есть Premium.\n\n"
        f"📩 Отправь мне ссылку!"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить Premium", callback_data="buy_prem")],
        [InlineKeyboardButton(text="👨‍💻 Поддержка", url=f"tg://user?id={ADMIN_ID}")]
    ])
    await message.answer(text, reply_markup=kb, parse_mode="Markdown")

# --- ОБРАБОТКА ССЫЛОК ---
@dp.message(F.text.contains("http"))
async def handle_link(message: Message):
    cur.execute("SELECT prem_until FROM users WHERE id = ?", (message.from_user.id,))
    res = cur.fetchone()
    is_prem = res[0] and datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S') > datetime.now()
    
    limit = 50 if is_prem else 30
    status = await message.answer("⏳")

    try:
        loop = asyncio.get_event_loop()
        file_path, is_video, desc, size = await loop.run_in_executor(None, download_media, message.text, message.from_user.id)
        
        if size > limit:
            if os.path.exists(file_path): os.remove(file_path)
            return await status.edit_text(f"⚠️ Файл слишком тяжелый ({size:.1f} МБ).\nВаш лимит: {limit} МБ.")

        # Отправка контента
        if is_video:
            await bot.send_video(message.chat.id, video=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")
        else:
            await bot.send_photo(message.chat.id, photo=FSInputFile(file_path), caption=f"❤️ {BOT_USERNAME}")

        # ФИШКА: Отправляем описание в копируемом блоке
        if desc and len(desc) > 5:
            # Очищаем описание от лишнего и берем первые 500 символов
            clean_desc = desc[:500] + "..." if len(desc) > 500 else desc
            await message.answer(f"📝 **Описание (нажми, чтобы скопировать):**\n\n`{clean_desc}`", parse_mode="Markdown")

        if os.path.exists(file_path): os.remove(file_path)
        await status.delete()

    except Exception as e:
        print(f"Error: {e}")
        await status.edit_text("❌ Не удалось скачать. Возможно, ссылка приватная или Pinterest защищен.")

# --- ОСТАЛЬНОЙ ФУНКЦИОНАЛ (Premium, Admin) ---
@dp.callback_query(F.data == "buy_prem")
async def pay(call: types.CallbackQuery):
    await bot.send_invoice(
        chat_id=call.from_user.id, title="Premium", description="Лимит 50МБ на 30 дней",
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

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
