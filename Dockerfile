FROM python:3.11-slim

WORKDIR /app

# Устанавливаем зависимости системы (минимальный набор)
RUN apt-get update && apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код
COPY . .

# Порт приложения
EXPOSE 8000

# Переменные окружения по умолчанию (лучше переопределять через docker-compose/.env)
ENV PYTHONUNBUFFERED=1

# Команда запуска сервера
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

