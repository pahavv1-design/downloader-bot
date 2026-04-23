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

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- БАЗА ДАННЫХ ---
db = sqlite3.connect("bot_data.db")
cur = db.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY, 
    prem_until DATETIME,
    username TEXT
)""")
cur.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
db.commit()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def get_setting(key, default=None):
    cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cur.fetchone()
    return res[0] if res else default

def set_setting(key, value):
    cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()

def get_prem_status(user_id):
    cur.execute("SELECT prem_until FROM users WHERE id = ?", (user_id,))
    res = cur.fetchone()
    if res and res[0]:
        until = datetime.strptime(res[0], '%Y-%m-%d %H:%M:%S')
        if until > datetime.now():
            return until
    return None

async def is_subscribed(user_id):
    channel_id = get_setting("channel_id")
    if not channel_id: return True
    try:
        member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except: return True

# --- ПРИВЕТСТВИЕ ---
@dp.message(Command("start"))
async def start(message: Message):
    # Регистрируем юзера
    cur.execute("INSERT OR IGNORE INTO users (id, username) VALUES (?, ?)", (message.from_user.id, message.from_user.username))
    db.commit()
    
    prem_end = get_prem_status(message.from_user.id)
    status_text = f"💎 Premium активен до: {prem_end.strftime('%d.%m.%Y')}" if prem_end else "🆓 Статус: Бесплатный (лимит 20МБ)"

    text = (
        f"❤️ Привет! Это бот для скачивания медиа.\n\n"
        f"👤 Ваш статус: {status_text}\n\n"
        "🔗 Ссылки: YouTube Shorts, TikTok, Instagram, Pinterest\n\n"
        "💳 Купите Premium, чтобы увеличить лимит до 50МБ и поддержать проект!"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить Premium (50 ⭐)", callback_data="buy_prem")],
        [InlineKeyboardButton(text="⚙️ Написать админу", url=f"tg://user?id={ADMIN_ID}")]
    ])
    await message.answer(text, reply_markup=kb)

# --- ПРОЦЕСС АВТОМАТИЧЕСКОЙ ОПЛАТЫ (STARS) ---

@dp.callback_query(F.data == "buy_prem")
async def process_buy(call: types.CallbackQuery):
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title="Premium на 30 дней",
        description="✅ Лимит до 50 МБ\n✅ Скачивание без очереди\n✅ Поддержка автора",
        payload="premium_30_days",
        currency="XTR", # Телеграм Звёзды
        prices=[LabeledPrice(label="Оплата", amount=50)] # Цена в звёздах
    )

@dp.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery):
    # Бот одобряет покупку (проверка, всё ли в порядке)
    await bot.answer_pre_checkout_query(query.id, ok=True)

@dp.message(F.successful_payment)
async def success_payment(message: Message):
    # ЭТОТ БЛОК СРАБОТАЕТ САМ СРАЗУ ПОСЛЕ ОПЛАТЫ
    days = 30
    current_prem = get_prem_status(message.from_user.id)
    
    # Если премиум уже есть, прибавляем к нему, если нет - к текущей дате
    start_date = current_prem if current_prem else datetime.now()
    new_end_date = (start_date + timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
    
    cur.execute("UPDATE users SET prem_until = ? WHERE id = ?", (new_end_date, message.from_user.id))
    db.commit()

    # Сообщение пользователю
    await message.answer(
        f"🎉 Спасибо за покупку!\n"
        f"💎 Premium активирован автоматически до: **{new_end_date}**\n\n"
        f"Теперь вы можете присылать тяжелые видео (до 50 МБ).",
        parse_mode="Markdown"
    )
    
    # Сообщение тебе (Админу)
    await bot.send_message(
        ADMIN_ID, 
        f"💰 **Новая покупка!**\n"
        f"Юзер: @{message.from_user.username} (ID: `{message.from_user.id}`)\n"
        f"Сумма: 50 ⭐"
    )

# --- СКАЧИВАНИЕ ---
def download_video(url, user_id):
    ydl_opts = {
        'format': 'best[ext=mp4]/best',
        'outtmpl': f'downloads/{user_id}_%(id)s.%(ext)s',
        'quiet': True, 'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)
        size = os.path.getsize(path) / (1024 * 1024)
        return path, size

@dp.message(F.text.contains("http"))
async def handle_link(message: Message):
    if not await is_subscribed(message.from_user.id):
        url = get_setting("channel_url", "https://t.me/tg")
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Подписаться", url=url)]])
        return await message.answer("❌ Подпишитесь на канал для работы бота!", reply_markup=kb)

    prem_end = get_prem_status(message.from_user.id)
    limit = 50 if prem_end else 20
    status = await message.answer("⏳ Скачиваю...")

    try:
        loop = asyncio.get_event_loop()
        path, size = await loop.run_in_executor(None, download_video, message.text, message.from_user.id)
        
        if size > limit:
            os.remove(path)
            return await status.edit_text(f"⚠️ Вес видео ({size:.1f}МБ) превышает ваш лимит {limit}МБ. Купите Premium!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎 Купить", callback_data="buy_prem")]]))

        await bot.send_video(message.chat.id, video=FSInputFile(path), caption=f"✅ Готово! ({size:.1f} МБ)")
        os.remove(path)
        await status.delete()
    except:
        await status.edit_text("❌ Ошибка. Ссылка не поддерживается или видео недоступно.")

# --- АДМИНКА ---
@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin(message: Message):
    cur.execute("SELECT COUNT(*) FROM users")
    cnt = cur.fetchone()[0]
    await message.answer(f"📊 Юзеров: {cnt}\n\nКоманды:\n/give ID — выдать вручную\n/setchannel ID URL — канал ОП")

@dp.message(Command("give"), F.from_user.id == ADMIN_ID)
async def give_manually(message: Message, command: CommandObject):
    uid = command.args
    new_end = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("UPDATE users SET prem_until = ? WHERE id = ?", (new_end, uid))
    db.commit()
    await message.answer(f"✅ Выдано до {new_end}")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
