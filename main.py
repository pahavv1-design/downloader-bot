import os, asyncio, yt_dlp, subprocess, logging, requests
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from database import init_db, add_user, check_limit, increment_limit, get_stats, get_all_users

logging.basicConfig(level=logging.INFO)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DAILY_LIMIT = 20 

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Раскрываем короткие ссылки pin.it
def resolve_url(url):
    if "pin.it" in url:
        res = requests.head(url, allow_redirects=True)
        return res.url
    return url

def compress_video(input_path, output_path):
    cmd = [
        'ffmpeg', '-i', input_path, '-vcodec', 'libx264', '-crf', '28', 
        '-preset', 'ultrafast', '-fs', '45M', '-y', output_path
    ]
    subprocess.run(cmd)

@dp.message(Command("start"))
async def start(message: types.Message):
    add_user(message.from_user.id)
    await message.answer(f"🚀 **Бот-загрузчик готов!**\n\nПрисылай ссылки из:\n• Pinterest 📌\n• TikTok 📱\n• YouTube 🎥\n• Instagram 📸\n\nЛимит: {DAILY_LIMIT} в день.")

@dp.message(Command("admin"), F.from_user.id == ADMIN_ID)
async def admin(message: types.Message):
    await message.answer(f"📊 Юзеров: {get_stats()}\nРассылка: `/send текст`")

@dp.message(F.text.contains("http"))
async def pre_download(message: types.Message):
    if not check_limit(message.from_user.id, DAILY_LIMIT):
        return await message.answer("❌ Лимит на сегодня исчерпан!")
    
    # Ищем ссылку в тексте (на случай если там есть еще слова)
    url = ""
    for word in message.text.split():
        if "http" in word:
            url = word
            break

    kb = InlineKeyboardBuilder()
    # Сохраняем первые 30 символов ссылки, чтобы не взорвать callback_data
    # Но саму ссылку возьмем из reply_to_message позже
    kb.row(types.InlineKeyboardButton(text="🎥 Видео", callback_data="dl_video"))
    kb.row(types.InlineKeyboardButton(text="🎵 Звук (MP3)", callback_data="dl_audio"))
    await message.answer("🎬 Что выгружаем?", reply_markup=kb.as_markup(), reply_to_message_id=message.message_id)

@dp.callback_query(F.data.startswith("dl_"))
async def download_logic(callback: types.CallbackQuery):
    mode = callback.data.split("_")[1]
    url = resolve_url(callback.message.reply_to_message.text)
    user_id = callback.from_user.id
    
    await callback.message.edit_text("⚙️ Подготовка файла... (обычно 10-30 сек)")
    
    folder = f"dl_{user_id}_{callback.message.message_id}"
    if not os.path.exists(folder): os.makedirs(folder)
    
    ydl_opts = {
        # Приоритет mp4, но разрешаем любой лучший формат
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
        'outtmpl': f'{folder}/file.%(ext)s',
        'noplaylist': True,
        'merge_output_format': 'mp4',
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        }
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            # Пытаемся определить имя файла
            files = [os.path.join(folder, f) for f in os.listdir(folder) if not f.endswith('.part')]
            if not files:
                raise Exception("Файл не найден")
            file_path = files[0]

        if mode == 'video':
            size = os.path.getsize(file_path) / (1024 * 1024)
            if size > 48:
                await callback.message.edit_text("🗜 Видео очень большое, сжимаю...")
                comp_path = f"{folder}/c.mp4"
                compress_video(file_path, comp_path)
                file_path = comp_path
            
            await bot.send_video(user_id, types.FSInputFile(file_path), caption="✅ Приятного просмотра!")
        else:
            audio_path = f"{folder}/audio.mp3"
            await callback.message.edit_text("🎵 Извлекаю аудиодорожку...")
            subprocess.run(['ffmpeg', '-i', file_path, '-vn', '-acodec', 'libmp3lame', '-ab', '192k', audio_path, '-y'])
            await bot.send_audio(user_id, types.FSInputFile(audio_path), caption="🎵 Аудио готово!")

        increment_limit(user_id)
        await callback.message.delete()
        
    except Exception as e:
        logging.error(f"Error: {e}")
        await callback.message.edit_text(f"❌ Ошибка. Скорее всего, Pinterest временно заблокировал доступ. Попробуйте другую ссылку.")
    
    # Очистка
    try:
        for f in os.listdir(folder): os.remove(os.path.join(folder, f))
        os.rmdir(folder)
    except: pass

async def main():
    init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
