import os, asyncio, yt_dlp, subprocess
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import init_db, add_user, check_limit, increment_limit, get_stats, get_all_users

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DAILY_LIMIT = 5 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Функция сжатия видео
def compress_video(input_path, output_path):
    # Сжимаем видео до ~45МБ используя кодек libx264
    cmd = [
        'ffmpeg', '-i', input_path, '-vcodec', 'libx264', '-crf', '28', 
        '-preset', 'ultrafast', '-fs', '45M', '-y', output_path
    ]
    subprocess.run(cmd)

@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id)
    await message.answer(f"👋 Привет! Пришли ссылку на YouTube, TikTok, Reels или Pinterest.\n\n"
                         f"📊 Твой лимит: {DAILY_LIMIT} видео в день.\n"
                         "Я могу скачать как видео, так и звук!")

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin(message: types.Message):
    await message.answer(f"📊 Юзеров: {get_stats()}\nРассылка: `/send текст`")

@dp.message(Command("send"), F.from_user.id == ADMIN_ID)
async def broadcast(message: types.Message):
    text = message.text.replace("/send ", "")
    for u_id in get_all_users():
        try: await bot.send_message(u_id, text)
        except: pass
    await message.answer("✅ Готово")

@dp.message(F.text.startswith("http"))
async def pre_download(message: types.Message):
    if not check_limit(message.from_user.id, DAILY_LIMIT):
        return await message.answer("❌ Лимит на сегодня исчерпан!")
    
    kb = InlineKeyboardBuilder()
    kb.row(types.InlineKeyboardButton(text="🎥 Видео", callback_data=f"dl_video_{message.text}"))
    kb.row(types.InlineKeyboardButton(text="🎵 Звук (MP3)", callback_data=f"dl_audio_{message.text}"))
    await message.answer("Что скачиваем?", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("dl_"))
async def download_logic(callback: types.CallbackQuery):
    data = callback.data.split("_")
    mode = data[1]
    url = data[2]
    user_id = callback.from_user.id
    
    await callback.message.edit_text("⏳ Начинаю загрузку...")
    
    folder = f"dl_{user_id}"
    if not os.path.exists(folder): os.makedirs(folder)
    
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best' if mode == 'video' else 'bestaudio/best',
        'outtmpl': f'{folder}/file.%(ext)s',
        'noplaylist': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)

        # Если скачиваем видео
        if mode == 'video':
            size = os.path.getsize(file_path) / (1024 * 1024)
            if size > 49:
                await callback.message.edit_text("⚙️ Видео тяжелое, сжимаю...")
                compressed_path = f"{folder}/compressed.mp4"
                compress_video(file_path, compressed_path)
                file_path = compressed_path
            
            await bot.send_video(user_id, types.FSInputFile(file_path), caption="✅ Видео готово!")
        
        # Если скачиваем звук
        else:
            audio_path = f"{folder}/audio.mp3"
            subprocess.run(['ffmpeg', '-i', file_path, '-q:a', '0', '-map', 'a', audio_path, '-y'])
            await bot.send_audio(user_id, types.FSInputFile(audio_path), caption="🎵 Звук извлечен!")

        increment_limit(user_id)
        await callback.message.delete()
        
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка. Возможно, видео защищено или слишком длинное.")
    
    # Очистка
    for f in os.listdir(folder): os.remove(os.path.join(folder, f))
    os.rmdir(folder)

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
