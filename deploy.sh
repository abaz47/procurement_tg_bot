#!/bin/bash

# Скрипт для развертывания Telegram бота закупок

set -e

echo "Развертывание Telegram бота закупок..."

# Проверяем наличие Docker
if ! command -v docker &> /dev/null; then
    echo "Docker не установлен. Установите Docker и повторите попытку."
    exit 1
fi

# Проверяем наличие docker-compose
if ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose не установлен. Установите Docker Compose и повторите попытку."
    exit 1
fi

# Проверяем наличие .env файла
if [ ! -f ".env" ]; then
    echo "Файл .env не найден. Создайте файл .env с TELEGRAM_BOT_TOKEN."
    exit 1
fi

# Проверяем наличие users.cfg
if [ ! -f "users.cfg" ]; then
    echo "Файл users.cfg не найден. Создайте файл конфигурации пользователей."
    exit 1
fi

# Создаем директорию для логов
mkdir -p logs

# Останавливаем старый контейнер (если есть)
echo "Останавливаем старый контейнер..."
docker-compose down || true

# Собираем новый образ
echo "Собираем Docker образ..."
docker-compose build

# Запускаем контейнер
echo "Запускаем бота..."
docker-compose up -d

# Проверяем статус
echo "Проверяем статус..."
sleep 3
docker-compose ps

echo "Бот успешно развернут!"
echo "Для просмотра логов используйте: docker-compose logs -f"
echo "Для остановки используйте: docker-compose down"
