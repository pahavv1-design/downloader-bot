import os, asyncio, yt_dlp, subprocess, logging
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import init_db, add_user, check_limit, increment_limit, get_stats, get_all_users

# Настройка логирования, чтобы видеть ошибки в консоли Bothost
logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DAILY_LIMIT = 15 

bot = Bot(token=TOKEN)
dp = Dispatcher()

def compress_video(input_path, output_path):
    cmd = [
        'ffmpeg', '-i', input_path, '-vcodec', 'libx264', '-crf', '28', 
        '-preset', 'ultrafast', '-fs', '45M', '-y', output_path
    ]
    subprocess.run(cmd)

@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id)
    logging.info(f"User {message.from_user.id} started the bot")
    await message.answer(f"👋 Привет! Я качаю видео и музыку из Pinterest, TikTok, YT, Instagram.\n\n"
                         f"📊 Лимит: {DAILY_LIMIT} загрузок в день.\n"
                         "Просто приши мне ссылку!")

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin(message: types.Message):
    await message.answer(f"📊 Юзеров: {get_stats()}\nРассылка: `/send текст`")

@dp.message(F.text.startswith("http"))
async def pre_download(message: types.Message):
    if not check_limit(message.from_user.id, DAILY_LIMIT):
        return await message.answer("❌ Лимит на сегодня исчерпан!")
    
    # Чтобы не превысить лимит кнопки в 64 байта, 
    # мы НЕ передаем ссылку в callback_data, а просто пишем тип
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🎥 Видео", callback_data="dl_video"))
    kb.row(types.InlineKeyboardButton(text="🎵 Звук (MP3)", callback_data="dl_audio"))
    await message.answer("Что скачиваем?", reply_markup=kb.as_markup(), reply_to_message_id=message.message_id)

@dp.callback_query(F.data.startswith("dl_"))
async def download_logic(callback: types.CallbackQuery):
    mode = callback.data.split("_")[1]
    # Берем ссылку из сообщения, на которое ответили кнопками
    url = callback.message.reply_to_message.text
    user_id = callback.from_user.id
    
    await callback.message.edit_text("⏳ Обработка... Пожалуйста, подождите.")
    
    folder = f"dl_{user_id}_{callback.message.message_id}"
    if not os.path.exists(folder): os.makedirs(folder)
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{folder}/file.%(ext)s',
        'noplaylist': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        if not os.path.exists(file_path):
            # Поиск любого скачанного файла
            files = [os.path.join(folder, f) for f in os.listdir(folder)]
            if files: file_path = files[0]

        if mode == 'video':
            size = os.path.getsize(file_path) / (1024 * 1024)
            if size > 48:
                await callback.message.edit_text("⚙️ Сжимаю видео...")
                comp_path = f"{folder}/c.mp4"
                compress_video(file_path, comp_path)
                file_path = comp_path
            
            await bot.send_video(user_id, types.FSInputFile(file_path), caption="✅ Готово!")
        else:
            audio_path = f"{folder}/audio.mp3"
            subprocess.run(['ffmpeg', '-i', file_path, '-vn', '-ar', '44100', '-ac', '2', '-ab', '192k', audio_path, '-y'])
            await bot.send_audio(user_id, types.FSInputFile(audio_path))

        increment_limit(user_id)
        await callback.message.delete()
        
    except Exception as e:
        logging.error(f"Download error: {e}")
        await callback.message.edit_text("❌ Не удалось скачать. Проверьте ссылку.")
    
    # Очистка
    try:
        for f in os.listdir(folder): os.remove(os.path.join(folder, f))
        os.rmdir(folder)
    except: pass

async def main():
    init_db()
    logging.info("Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
