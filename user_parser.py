import asyncio
import logging
import sqlite3
import sys
import os
from datetime import datetime
from telethon import TelegramClient, errors
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.tl.types import PeerChannel

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('parser.log', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

API_ID = 37780238  # ВАШ_API_ID
API_HASH = 'fbfe8a419fea2f1ee79b9cc32bc49e18'  # ВАШ_API_HASH
PHONE_NUMBER = '+959760950133'  # Номер аккаунта для парсера

# Инициализация клиента Telegram
client = TelegramClient('user_session', API_ID, API_HASH)

# Инициализация базы данных
def init_db():
    conn = sqlite3.connect('tasks.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parsing_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_link TEXT NOT NULL,
            status TEXT DEFAULT 'ожидает',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS parsed_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER,
            message_id INTEGER,
            date TIMESTAMP,
            text TEXT,
            views INTEGER,
            forwards INTEGER,
            FOREIGN KEY (task_id) REFERENCES parsing_tasks (id)
        )
    ''')
    conn.commit()
    conn.close()
    logging.info("База данных tasks.db инициализирована")

# Функция для парсинга канала
async def parse_channel(channel_link, task_id):
    try:
        logging.info(f"Начинаю парсинг канала: {channel_link}")
        
        # Получаем entity канала
        entity = await client.get_entity(channel_link)
        
        # Проверяем, что это канал
        if not isinstance(entity, PeerChannel):
            logging.error(f"{channel_link} не является каналом")
            return
        
        # Получаем историю сообщений
        all_messages = []
        offset_id = 0
        limit = 100
        total_messages = 0
        
        while True:
            history = await client(GetHistoryRequest(
                peer=entity,
                offset_id=offset_id,
                offset_date=None,
                add_offset=0,
                limit=limit,
                max_id=0,
                min_id=0,
                hash=0
            ))
            
            if not history.messages:
                break
                
            messages = history.messages
            all_messages.extend(messages)
            
            # Сохраняем сообщения в базу данных
            conn = sqlite3.connect('tasks.db')
            cursor = conn.cursor()
            
            for msg in messages:
                # Проверяем, есть ли уже такое сообщение
                cursor.execute(
                    "SELECT id FROM parsed_messages WHERE task_id = ? AND message_id = ?",
                    (task_id, msg.id)
                )
                if cursor.fetchone():
                    continue
                
                # Извлекаем данные
                text = msg.message or ""
                date = msg.date
                views = getattr(msg, 'views', 0)
                forwards = getattr(msg, 'forwards', 0)
                
                # Сохраняем в базу
                cursor.execute(
                    "INSERT INTO parsed_messages (task_id, message_id, date, text, views, forwards) VALUES (?, ?, ?, ?, ?, ?)",
                    (task_id, msg.id, date, text, views, forwards)
                )
            
            conn.commit()
            conn.close()
            
            total_messages += len(messages)
            logging.info(f"Получено {len(messages)} сообщений. Всего: {total_messages}")
            
            if len(messages) < limit:
                break
                
            offset_id = messages[-1].id
        
        logging.info(f"Парсинг канала {channel_link} завершен. Всего сообщений: {total_messages}")
        
    except errors.ChannelPrivateError:
        logging.error(f"Канал {channel_link} является приватным или недоступен")
    except errors.ChannelInvalidError:
        logging.error(f"Неверная ссылка на канал: {channel_link}")
    except Exception as e:
        logging.error(f"Ошибка при парсинге канала {channel_link}: {e}")

# Основной цикл проверки задач
async def main_loop():
    logging.info("🚀 Запуск основного цикла проверки задач...")
    
    while True:
        try:
            # Подключаемся к базе данных
            conn = sqlite3.connect('tasks.db')
            cursor = conn.cursor()
            
            # Ищем задачу со статусом 'ожидает'
            cursor.execute("SELECT id, channel_link FROM parsing_tasks WHERE status = 'ожидает' LIMIT 1")
            task = cursor.fetchone()
            
            if task:
                task_id, channel_link = task
                logging.info(f"Найдена задача {task_id}: парсинг канала {channel_link}")
                
                # Обновляем статус на 'в процессе'
                cursor.execute("UPDATE parsing_tasks SET status = 'в процессе' WHERE id = ?", (task_id,))
                conn.commit()
                
                try:
                    # Парсим канал
                    await parse_channel(channel_link, task_id)
                    
                    # Обновляем статус на 'выполнено'
                    cursor.execute("UPDATE parsing_tasks SET status = 'выполнено' WHERE id = ?", (task_id,))
                    conn.commit()
                    logging.info(f"Задача {task_id} выполнена.")
                    
                except Exception as e:
                    logging.error(f"Ошибка при выполнении задачи {task_id}: {e}")
                    # Обновляем статус на 'ошибка'
                    cursor.execute("UPDATE parsing_tasks SET status = 'ошибка' WHERE id = ?", (task_id,))
                    conn.commit()
                    
                # Пауза между задачами
                await asyncio.sleep(5)
            else:
                # Если задач нет, ждем 30 секунд перед следующей проверкой
                logging.info("Задач для обработки нет. Ожидание 30 секунд...")
                await asyncio.sleep(30)
                
            conn.close()
            
        except Exception as e:
            logging.error(f"Ошибка в основном цикле: {e}")
            await asyncio.sleep(30)

# Главная функция
async def main():
    init_db()
    await client.start(PHONE_NUMBER)
    logging.info("✅ Клиент Telegram успешно авторизован")
    logging.info("✅ Парсер готов к работе")
    
    # Запускаем основной цикл проверки задач
    await main_loop()

# Запуск программы
if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Парсер остановлен пользователем")
    except Exception as e:
        logging.error(f"Критическая ошибка: {e}")