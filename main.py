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

# --- ФУНКЦИЯ РАЗВОРАЧИВАНИЯ ССЫЛОК (Для Pinterest) ---
async def resolve_url(url):
    if "pin.it" in url or "t.co" in url:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, allow_redirects=True) as response:
                return str(response.url)
    return url

# --- ФУНКЦИЯ СКАЧИВАНИЯ ---
def download_media(url, user_id):
    tmp_dir = 'downloads'
    if not os.path.exists(tmp_dir): os.makedirs(tmp_dir)

    # Опции для видео
    v_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{tmp_dir}/{user_id}_v.%(ext)s',
        'quiet': True, 'no_warnings': True,
    }
    # Опции для аудио
    a_opts = {
        'format': 'bestaudio[ext=m4a]/bestaudio/best',
        'outtmpl': f'{tmp_dir}/{user_id}_a.%(ext)s',
        'quiet': True, 'no_warnings': True,
    }

    with yt_dlp.YoutubeDL(v_opts) as ydl:
        v_info = ydl.extract_info(url, download=True)
        v_path = ydl.prepare_filename(v_info)
        v_size = os.path.getsize(v_path) / (1024 * 1024)
        is_video = v_info.get('ext') not in ['jpg', 'png', 'jpeg', 'webp']

    with yt_dlp.YoutubeDL(a_opts) as ydl:
        try:
            a_info = ydl.extract_info(url, download=True)
            a_path = ydl.prepare_filename(a_info)
        except: a_path = None # Если звука нет (например, это просто фото)

    return v_path, a_path, v_size, is_video

# --- ПРИВЕТСТВИЕ (КАК НА КАРТИНКЕ) ---
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
        "• YouTube Shorts\n"
        "• Instagram\n"
        "• TikTok\n"
        "• Pinterest\n\n"
        "⚠️ **Внимание:** Лимит загрузки — **30 МБ**.\n"
        "💎 Для видео до 50 МБ купите Premium.\n\n"
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
    # Проверка ОП (обязательной подписки)
    ch_id = cur.execute("SELECT value FROM settings WHERE key='ch_id'").fetchone()
    if ch_id:
        try:
            member = await bot.get_chat_member(ch_id[0], message.from_user.id)
            if member.status == "left":
                url = cur.execute("SELECT value FROM settings WHERE key='ch_url'").fetchone()[0]
                kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=url)]])
                return await message.answer("❌ Сначала подпишись на канал!", reply_markup=kb)
        except: pass

    # Проверка лимитов
    cur.execute("SELECT prem_until FROM users WHERE id = ?", (message.from_user.id,))
    res = cur.fetchone()
    is_prem = res[0] and datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S') > datetime.now()
    limit = 50 if is_prem else 30
    
    status_emoji = await message.answer("⏳")

    try:
        # Разворачиваем короткую ссылку
        full_url = await resolve_url(message.text)
        
        loop = asyncio.get_event_loop()
        v_path, a_path, v_size, is_video = await loop.run_in_executor(None, download_media, full_url, message.from_user.id)
        
        if v_size > limit:
            if v_path and os.path.exists(v_path): os.remove(v_path)
            if a_path and os.path.exists(a_path): os.remove(a_path)
            return await status_emoji.edit_text(f"⚠️ Файл {v_size:.1f}МБ превышает лимит {limit}МБ.\n💎 Купите Premium!")

        # Отправка контента
        if is_video:
            await bot.send_video(message.chat.id, video=FSInputFile(v_path), caption=f"❤️ {BOT_USERNAME}")
        else:
            await bot.send_photo(message.chat.id, photo=FSInputFile(v_path), caption=f"❤️ {BOT_USERNAME}")

        # Отправка звука (если есть)
        if a_path and os.path.exists(a_path):
            await bot.send_audio(message.chat.id, audio=FSInputFile(a_path), caption=f"❤️ {BOT_USERNAME}")

        # Удаление
        if v_path and os.path.exists(v_path): os.remove(v_path)
        if a_path and os.path.exists(a_path): os.remove(a_path)
        await status_emoji.delete()

    except Exception as e:
        await status_emoji.edit_text("❌ Видео не найдено или ссылка защищена.")

# --- АДМИНКА И ОПЛАТА (Без изменений) ---
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

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def adm(message: Message):
    cur.execute("SELECT COUNT(*) FROM users")
    await message.answer(f"📊 Юзеров: {cur.fetchone()[0]}\n`/setchannel ID URL` - ОП\n`/give ID` - Премиум\n`/send Текст` - Рассылка")

@dp.message(Command("setchannel"), F.from_user.id == ADMIN_ID)
async def set_ch(message: Message, command: CommandObject):
    try:
        args = command.args.split()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('ch_id', ?)", (args[0],))
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('ch_url', ?)", (args[1],))
        db.commit()
        await message.answer("✅ Канал ОП обновлен")
    except: await message.answer("Формат: `/setchannel -100xxx https://t.me/link`")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
