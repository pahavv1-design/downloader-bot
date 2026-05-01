# Используем полную версию python (она тяжелее, но в ней реже возникают ошибки с зависимостями)
FROM python:3.11-bookworm

# Обновляем список пакетов и устанавливаем ffmpeg с флагом --fix-missing
RUN apt-get update --fix-missing && \
    apt-get install -y ffmpeg --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Сначала копируем только requirements, чтобы закэшировать установку библиотек
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальное
COPY . .

CMD ["python", "main.py"]
