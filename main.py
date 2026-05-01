import os, asyncio, yt_dlp, subprocess
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import init_db, add_user, check_limit, increment_limit, get_stats, get_all_users

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DAILY_LIMIT = 10 # Можно увеличить

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Функция сжатия
def compress_video(input_path, output_path):
    cmd = [
        'ffmpeg', '-i', input_path, '-vcodec', 'libx264', '-crf', '28', 
        '-preset', 'ultrafast', '-fs', '45M', '-y', output_path
    ]
    subprocess.run(cmd)

@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id)
    await message.answer(f"👋 Привет! Я качаю видео и музыку.\n\n"
                         f"✅ Поддерживаю: YouTube, TikTok, Pinterest, Instagram.\n"
                         f"📊 Твой лимит: {DAILY_LIMIT} загрузок в день.")

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin(message: types.Message):
    await message.answer(f"📊 Юзеров: {get_stats()}\nРассылка: `/send текст`")

@dp.message(F.text.startswith("http"))
async def pre_download(message: types.Message):
    if not check_limit(message.from_user.id, DAILY_LIMIT):
        return await message.answer("❌ Лимит на сегодня исчерпан!")
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🎥 Видео", callback_data=f"dl_video_{message.text}"))
    kb.row(types.InlineKeyboardButton(text="🎵 Звук (MP3)", callback_data=f"dl_audio_{message.text}"))
    await message.answer("Что именно скачиваем?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("dl_"))
async def download_logic(callback: types.CallbackQuery):
    data = callback.data.split("_", 2)
    mode = data[1]
    url = data[2]
    user_id = callback.from_user.id
    
    await callback.message.edit_text("⏳ Обработка... Пожалуйста, подождите.")
    
    folder = f"dl_{user_id}"
    if not os.path.exists(folder): os.makedirs(folder)
    
    # Улучшенные настройки для соцсетей
    ydl_opts = {
        # 'best' помогает забрать видео, если оно идет одним файлом (Pinterest)
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': f'{folder}/file.%(ext)s',
        'noplaylist': True,
        'quiet': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        if mode == 'video':
            # Проверяем, существует ли файл (yt-dlp иногда меняет расширение)
            if not os.path.exists(file_path):
                # Пробуем найти любой файл в папке
                files = os.listdir(folder)
                if files: file_path = os.path.join(folder, files[0])

            size = os.path.getsize(file_path) / (1024 * 1024)
            
            if size > 49:
                await callback.message.edit_text("⚙️ Видео тяжелое, сжимаю...")
                compressed_path = f"{folder}/compressed.mp4"
                compress_video(file_path, compressed_path)
                file_path = compressed_path
            
            await bot.send_video(user_id, types.FSInputFile(file_path), caption="✅ Готово!")
        
        else: # Режим аудио
            audio_path = f"{folder}/audio.mp3"
            # Принудительно перекодируем в mp3 через ffmpeg
            subprocess.run(['ffmpeg', '-i', file_path, '-vn', '-ar', '44100', '-ac', '2', '-b:a', '192k', audio_path, '-y'])
            await bot.send_audio(user_id, types.FSInputFile(audio_path), caption="🎵 Звук извлечен!")

        increment_limit(user_id)
        await callback.message.delete()
        
    except Exception as e:
        print(f"Error: {e}")
        await callback.message.edit_text(f"❌ Ошибка загрузки. Возможно, ссылка приватная или формат не поддерживается.")
    
    # Тщательная очистка
    try:
        for f in os.listdir(folder): os.remove(os.path.join(folder, f))
        os.rmdir(folder)
    except: pass
