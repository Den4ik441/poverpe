import telebot
from telebot import types
import sqlite3
from datetime import datetime, timedelta
import random
import re
import config
import threading
from math import floor
import time

# Инициализация объекта бота
bot = telebot.TeleBot(config.BOT_TOKEN)

# Создание таблиц в базе данных
with sqlite3.connect('database.db') as conn:
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS requests (
        ID INTEGER PRIMARY KEY,
        LAST_REQUEST TIMESTAMP,
        STATUS TEXT DEFAULT 'pending'
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        ID INTEGER PRIMARY KEY,
        BALANCE REAL DEFAULT 0,
        REG_DATE TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS numbers (
        NUMBER TEXT PRIMARY KEY,
        ID_OWNER INTEGER,
        TAKE_DATE TEXT,
        SHUTDOWN_DATE TEXT,
        MODERATOR_ID INTEGER,
        CONFIRMED_BY_MODERATOR_ID INTEGER,
        VERIFICATION_CODE TEXT,
        STATUS TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS personal (
        ID INTEGER PRIMARY KEY,
        TYPE TEXT
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS withdraws (
        ID INTEGER,
        AMOUNT REAL,
        DATE TEXT,
        STATUS TEXT
    )''')
    # Создаем таблицу settings, если она еще не существует
    cursor.execute('''CREATE TABLE IF NOT EXISTS settings (
        PRICE REAL  -- Цена за номер
    )''')
    
    # Проверяем, существует ли столбец HOLD_TIME, и добавляем его, если отсутствует
    cursor.execute("PRAGMA table_info(settings)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'HOLD_TIME' not in columns:
        cursor.execute('ALTER TABLE settings ADD COLUMN HOLD_TIME INTEGER')
    
    # Проверяем, есть ли уже данные в таблице settings
    cursor.execute('SELECT COUNT(*) FROM settings')
    count = cursor.fetchone()[0]
    
    # Если данных нет, вставляем начальные значения: 2$ за номер, холд 5 минут
    if count == 0:
        cursor.execute('INSERT INTO settings (PRICE, HOLD_TIME) VALUES (?, ?)', (2.0, 5))
    else:
        # Если данные есть, но столбец HOLD_TIME новый, устанавливаем значение по умолчанию
        cursor.execute('UPDATE settings SET HOLD_TIME = ? WHERE HOLD_TIME IS NULL', (5,))
    
    conn.commit()

# Класс для работы с базой данных
class Database:
    def get_db(self):
        return sqlite3.connect('database.db')

    def is_moderator(self, user_id):
        with self.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM personal WHERE ID = ? AND TYPE = ?', (user_id, 'moder'))
            return cursor.fetchone() is not None

    def update_balance(self, user_id, amount):
        with self.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET BALANCE = BALANCE + ? WHERE ID = ?', (amount, user_id))
            conn.commit()

db = Database()

# Главное меню с системой заявок
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        
        # Проверка статуса пользователя
        cursor.execute('SELECT LAST_REQUEST, STATUS FROM requests WHERE ID = ?', (user_id,))
        request = cursor.fetchone()
        
        # Если пользователь уже одобрен
        if request and request[1] == 'approved':
            show_main_menu(message)
            return
        
        # Если пользователь не одобрен, проверяем время последнего запроса
        if request:
            last_request_time = datetime.strptime(request[0], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - last_request_time < timedelta(minutes=15):
                time_left = 15 - ((datetime.now() - last_request_time).seconds // 60)
                bot.send_message(message.chat.id, 
                                f"⏳ Ожидайте подтверждения. Вы сможете отправить новый запрос через {time_left} минут.")
                return
        
        # Создание или обновление запроса
        cursor.execute('INSERT OR REPLACE INTO requests (ID, LAST_REQUEST, STATUS) VALUES (?, ?, ?)',
                      (user_id, current_date, 'pending'))
        conn.commit()
        
        # Сообщение пользователю
        bot.send_message(message.chat.id, 
                        "👋 Здравствуйте! Ожидайте, пока вас впустят в бота.")
        
        # Уведомление админу с кнопками
        username = f"@{message.from_user.username}" if message.from_user.username else "Нет username"
        admin_text = f"📝 Пользователь {user_id} {username} пытается зарегистрироваться в боте"
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("✅ Впустить в бота", callback_data=f"approve_user_{user_id}"),
            types.InlineKeyboardButton("❌ Отказать в доступе", callback_data=f"reject_user_{user_id}")
        )
        
        for admin_id in config.ADMINS_ID:
            try:
                bot.send_message(admin_id, admin_text, reply_markup=markup)
            except:
                continue


@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_user_"))
def approve_user_callback(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT STATUS FROM requests WHERE ID = ?', (user_id,))
        request = cursor.fetchone()
        
        if request:
            cursor.execute('UPDATE requests SET STATUS = "approved" WHERE ID = ?', (user_id,))
        else:
            cursor.execute('INSERT INTO requests (ID, LAST_REQUEST, STATUS) VALUES (?, ?, ?)',
                          (user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'approved'))
        conn.commit()
        
        try:
            bot.send_message(user_id, "✅ Вас впустили в бота! Напишите /start")
        except:
            bot.edit_message_text(f"✅ Пользователь {user_id} одобрен, но уведомление не доставлено",
                                 call.message.chat.id,
                                 call.message.message_id)
        bot.edit_message_text(f"✅ Пользователь {user_id} одобрен",
                             call.message.chat.id,
                             call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_user_"))
def reject_user_callback(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для выполнения этого действия!")
        return
    
    user_id = int(call.data.split("_")[2])
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        # Обновляем статус на "rejected" и обновляем время последнего запроса
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('UPDATE requests SET STATUS = "rejected", LAST_REQUEST = ? WHERE ID = ?',
                      (current_date, user_id))
        conn.commit()
        
        try:
            bot.send_message(user_id, "❌ Вам отказано в доступе. Вы сможете отправить новый запрос через 15 минут.")
        except:
            bot.edit_message_text(f"❌ Пользователь {user_id} отклонён, но уведомление не доставлено",
                                 call.message.chat.id,
                                 call.message.message_id)
        bot.edit_message_text(f"❌ Пользователь {user_id} отклонён",
                             call.message.chat.id,
                             call.message.message_id)
                             
def show_main_menu(message):
    user_id = message.from_user.id
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"[+] Новый пользователь зарегистрировался:")
    print(f"🆔 ID: {user_id}")
    print(f"👤 Имя: {message.from_user.first_name} {message.from_user.last_name or ''}")
    print(f"🔗 Username: @{message.from_user.username or 'нет'}")
    print(f"📅 Дата регистрации: {current_date}")
    print("-" * 40)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (ID, BALANCE, REG_DATE) VALUES (?, ?, ?)',
                      (user_id, 0, current_date))
        
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
        
        cursor.execute('SELECT NUMBER FROM numbers WHERE MODERATOR_ID = ? AND SHUTDOWN_DATE = "0" AND VERIFICATION_CODE IS NULL', 
                      (user_id,))
        active_number = cursor.fetchone()
        conn.commit()

    # Определяем роли пользователя
    is_admin = user_id in config.ADMINS_ID
    is_moderator = db.is_moderator(user_id)

    # Текст приветствия
    if is_moderator and not is_admin:
        # Только модератор
        welcome_text = "📝 <b>Заявки</b>"
    else:
        # Обычный пользователь или администратор (включая случай, если он также модератор)
        welcome_text = (
            f"<b>📢 Добро пожаловать в {config.SERVICE_NAME}</b>\n\n"
            f"<b>⏳ График работы:</b> <code>{config.WORK_TIME}</code>\n\n"
            "<b>💼 Как это работает?</b>\n"
            "• <i>Вы продаёте номер</i> – <b>мы предоставляем стабильные выплаты.</b>\n"
            f"• <i>Моментальные выплаты</i> – <b>после {hold_time} минут работы.</b>\n\n"
            "<b>💰 Тарифы на сдачу номеров:</b>\n"
            f"▪️ <code>{price}$</code> за номер (холд {hold_time} минут)\n"
            f"<b>📍 Почему выбирают {config.SERVICE_NAME} ?</b>\n"
            "✅ <i>Прозрачные условия сотрудничества</i>\n"
            "✅ <i>Выгодные тарифы и моментальные выпла ты</i>\n"
            "✅ <i>Оперативная поддержка 24/7</i>\n\n"
            "<b>🔹 Начните зарабатывать прямо сейчас!</b>"
        )
    
    if active_number and is_moderator:
        welcome_text += f"\n\n⚠️ У вас есть активный номер: {active_number[0]}\nПродолжите работу с ним в разделе 'Получить номер'."

    markup = types.InlineKeyboardMarkup()
    
    # Добавляем кнопки в зависимости от роли пользователя
    # Кнопки "Сдать номер" и "Мой профиль" для обычных пользователей и администраторов
    if not is_moderator or is_admin:
        markup.row(
            types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
            types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number")
        )
    
    # Кнопка "Админка" для администратора
    if is_admin:
        markup.add(types.InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel"))
    
    # Кнопки для модератора
    if is_moderator:
        markup.add(
            types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"),
            types.InlineKeyboardButton("📱 Мои номера", callback_data="moderator_numbers")
        )

    # Проверяем, вызывается ли функция при редактировании сообщения
    if hasattr(message, 'chat'):
         bot.send_message(message.chat.id, welcome_text, parse_mode='HTML', reply_markup=markup)
    else:
        bot.edit_message_text(welcome_text, message.message.chat.id, message.message.message_id, parse_mode='HTML', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "admin_panel")
def admin_panel(call):
    if call.from_user.id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            today = datetime.now().strftime("%Y-%m-%d")
            
            cursor.execute('''
                SELECT TAKE_DATE, SHUTDOWN_DATE 
                FROM numbers 
                WHERE SHUTDOWN_DATE LIKE ? || "%" 
                AND TAKE_DATE != "0" 
                AND TAKE_DATE != "1"
            ''', (today,))
            
            total_numbers = 0
            numbers_count = 0
            
            for take_date, shutdown_date in cursor.fetchall():
                numbers_count += 1
                total_numbers += 1

        admin_text = (
            "<b>⚙️ Панель администратора</b>\n\n"
            f"📱 Слетевших номеров: <code>{numbers_count}</code>\n"
            f"📊 Всего обработанных номеров: <code>{total_numbers}</code>"
        )

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("👥 Модераторы", callback_data="moderators"))
        markup.add(types.InlineKeyboardButton("➖ Удалить модератора", callback_data="delete_moderator"))
        markup.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="broadcast"))
        markup.add(types.InlineKeyboardButton("⚙️ Настройки", callback_data="settings"))
        markup.add(types.InlineKeyboardButton("📱 Все номера", callback_data="all_numbers"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        
        bot.edit_message_text(admin_text,
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='HTML',
                            reply_markup=markup)

def check_time():
    while True:
        current_time = datetime.now().strftime("%H:%M")
        if current_time == config.CLEAR_TIME:
            clear_database()
            time.sleep(61)
        time.sleep(30)

def check_numbers_for_payment():
    while True:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
            result = cursor.fetchone()
            price, hold_time = result if result else (2.0, 5)
            
            # Исключаем номера с TAKE_DATE = "0" или "1"
            cursor.execute('SELECT NUMBER, ID_OWNER, TAKE_DATE FROM numbers WHERE SHUTDOWN_DATE = "0" AND STATUS = "активен" AND TAKE_DATE NOT IN ("0", "1")')
            active_numbers = cursor.fetchall()
            
            current_time = datetime.now()
            for number, owner_id, take_date in active_numbers:
                try:
                    take_time = datetime.strptime(take_date, "%Y-%m-%d %H:%M:%S")
                    time_diff = (current_time - take_time).total_seconds() / 60  # Время в минутах
                    
                    if time_diff >= hold_time:
                        # Начисляем оплату
                        db.update_balance(owner_id, price)
                        bot.send_message(owner_id, 
                                       f"✅ Ваш номер {number} проработал {hold_time} минут!\n"
                                       f"💵 Вам начислено: ${price}")
                        # Отмечаем номер как завершенный
                        shutdown_date = current_time.strftime("%Y-%m-%d %H:%M:%S")
                        cursor.execute('UPDATE numbers SET SHUTDOWN_DATE = ? WHERE NUMBER = ?', (shutdown_date, number))
                        conn.commit()
                except ValueError as e:
                    print(f"Ошибка при обработке номера {number}: {e}")
                    continue
        
        time.sleep(60)  # Проверяем каждую минуту
def clear_database():
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT ID_OWNER FROM numbers WHERE ID_OWNER NOT IN (SELECT ID FROM personal WHERE TYPE = "ADMIN" OR TYPE = "moder")')
        users = cursor.fetchall()
        
        cursor.execute('DELETE FROM numbers')
        conn.commit()
        
        for user in users:
            try:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number"))
                bot.send_message(user[0], "🔄 Очередь очищена.\n📱 Пожалуйста, поставьте свои номера снова.", reply_markup=markup)
            except:
                continue
        
        for admin_id in config.ADMINS_ID:
            try:
                bot.send_message(admin_id, "🔄 Очередь очищена, пользователи предупреждены.")
            except:
                continue

def run_bot():
    time_checker = threading.Thread(target=check_time)
    time_checker.daemon = True
    time_checker.start()
    
    payment_checker = threading.Thread(target=check_numbers_for_payment)
    payment_checker.daemon = True
    payment_checker.start()
    
    bot.polling(none_stop=True)

def check_balance_and_fix(user_id):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT BALANCE FROM users WHERE ID = ?', (user_id,))
        user = cursor.fetchone()
        if user and user[0] < 0:
            cursor.execute('UPDATE users SET BALANCE = 0 WHERE ID = ?', (user_id,))
            conn.commit()

@bot.callback_query_handler(func=lambda call: call.data == "profile")
def show_profile(call):
    user_id = call.from_user.id
    check_balance_and_fix(user_id)
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM users WHERE ID = ?', (user_id,))
        user = cursor.fetchone()
        
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
        
        if user:
            cursor.execute('SELECT COUNT(*) FROM numbers WHERE ID_OWNER = ? AND SHUTDOWN_DATE = "0"', (user_id,))
            active_numbers = cursor.fetchone()[0]
            
            roles = []
            if user_id in config.ADMINS_ID:
                roles.append("👑 Администратор")
            if db.is_moderator(user_id):
                roles.append("🛡 Модератор")
            if not roles:
                roles.append("👤 Пользователь")
            
            profile_text = (f"👤 <b>Ваш профиль:</b>\n\n"
                          f"🆔ID ссылкой: <code>https://t.me/@id{user_id}</code>\n"
                          f"🆔 ID: <code>{user[0]}</code>\n"
                          f"💰 Баланс: {user[1]} $\n"
                          f"📱 Активных номеров: {active_numbers}\n"
                          f"🎭 Роль: {' | '.join(roles)}\n"
                          f"📅 Дата регистрации: {user[2]}\n"
                          f"💵 Текущая ставка: {price}$ за номер\n"
                          f"⏱ Время холда: {hold_time} минут")

            markup = types.InlineKeyboardMarkup()
            markup.add(
                types.InlineKeyboardButton("💳 Вывести", callback_data="withdraw"),
                types.InlineKeyboardButton("📱 Мои номера", callback_data="my_numbers")
            )
            
            if user_id in config.ADMINS_ID:
                cursor.execute('SELECT COUNT(*) FROM users')
                total_users = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(*) FROM numbers WHERE SHUTDOWN_DATE = "0"')
                active_total = cursor.fetchone()[0]
                cursor.execute('SELECT COUNT(*) FROM numbers')
                total_numbers = cursor.fetchone()[0]
                
                profile_text += (f"\n\n📊 <b>Статистика бота:</b>\n"
                               f"👥 Всего пользователей: {total_users}\n"
                               f"📱 Активных номеров: {active_total}\n"
                               f"📊 Всего номеров: {total_numbers}")
            
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
            
            bot.edit_message_text(profile_text,
                                call.message.chat.id,
                                call.message.message_id,
                                reply_markup=markup,
                                parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "withdraw")
def start_withdrawal_request(call):
    user_id = call.from_user.id
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT BALANCE FROM users WHERE ID = ?', (user_id,))
        balance = cursor.fetchone()[0]
        
        if balance > 0:
            msg = bot.edit_message_text(f"💰 Ваш баланс: {balance}$\n💳 Вы хотите вывести весь ваш баланс?",
                                      call.message.chat.id,
                                      call.message.message_id)
            bot.register_next_step_handler(msg, handle_withdrawal_request, balance)
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.edit_message_text("❌ На вашем балансе недостаточно средств для вывода",
                                call.message.chat.id,
                                call.message.message_id,
                                reply_markup=markup)

def handle_withdrawal_request(message, amount):
    user_id = message.from_user.id
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT BALANCE FROM users WHERE ID = ?', (user_id,))
        user = cursor.fetchone()

        if user and user[0] > 0:
            new_balance = 0
            cursor.execute('UPDATE users SET BALANCE = ? WHERE ID = ?', (new_balance, user_id))
            current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('INSERT INTO withdraws (ID, AMOUNT, DATE, STATUS) VALUES (?, ?, ?, ?)', 
                          (user_id, user[0], current_date, "pending"))
            conn.commit()

            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id,
                           f"✅ Заявка на вывод {user[0]}$ успешно создана!\n⏳ Ожидайте обработки администратором",
                           reply_markup=markup)
            
            bot.send_message(user_id, f"✅ Ваш баланс был уменьшен на {user[0]}$. Новый баланс: 0$.")
            
            admin_message = (
                f"💰 Новая заявка на выплату\n\n"
                f"👤 ID: {user_id}\n"
                f"💵 Сумма: {user[0]}$\n\n"
                f"📱 Вечная ссылка ANDROID: tg://openmessage?user_id={user_id}\n"
                f"📱 Вечная ссылка IOS: https://t.me/@id{user_id}"
            )
            admin_markup = types.InlineKeyboardMarkup()
            admin_markup.add(
                types.InlineKeyboardButton("✅ Отправить чек", callback_data=f"send_check_{user_id}_{user[0]}"),
                types.InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_withdraw_{user_id}_{user[0]}")
            )
            for admin_id in config.ADMINS_ID:
                try:
                    bot.send_message(admin_id, admin_message, reply_markup=admin_markup)
                except:
                    continue
        else:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад в профиль", callback_data="profile"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ У вас нет средств на балансе для вывода.", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("send_check_"))
def request_check_link(call):
    if call.from_user.id in config.ADMINS_ID:
        user_id, amount = call.data.split("_")[2:]
        msg = bot.edit_message_text("🔗 Отправьте ссылку на чек:",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_check_link, user_id, amount)

def process_check_link(message, user_id, amount):
    if message.from_user.id in config.ADMINS_ID:
        check_link = message.text
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM withdraws WHERE ID = ? AND AMOUNT = ?', (int(user_id), float(amount)))
            conn.commit()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Активировать чек", url=check_link))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.send_message(int(user_id),
                           f"✅ Ваша выплата {amount}$ готова!\n💳 Нажмите кнопку ниже для активации чека",
                           reply_markup=markup)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("reject_withdraw_"))
def reject_withdraw(call):
    if call.from_user.id in config.ADMINS_ID:
        _, _, user_id, amount = call.data.split("_")
        amount = float(amount)
        
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET BALANCE = BALANCE + ? WHERE ID = ?', (amount, int(user_id)))
            cursor.execute('DELETE FROM withdraws WHERE ID = ? AND AMOUNT = ?', (int(user_id), amount))
            conn.commit()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💳 Попробовать снова", callback_data="withdraw"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        try:
            bot.send_message(int(user_id),
                           f"❌ Ваша заявка на вывод {amount}$ отклонена\n💰 Средства возвращены на баланс",
                           reply_markup=markup)
        except:
            pass
        
        markup_admin = types.InlineKeyboardMarkup()
        markup_admin.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup_admin.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("✅ Выплата отклонена, средства возвращены",
                            call.message.chat.id,
                            call.message.message_id,
                            reply_markup=markup_admin)

@bot.callback_query_handler(func=lambda call: call.data == "moderators")
def moderators(call):
    if call.from_user.id in config.ADMINS_ID:
        markup = types.InlineKeyboardMarkup()
        markup.add(
            types.InlineKeyboardButton("➕ Добавить", callback_data="add_moder"),
            types.InlineKeyboardButton("➖ Удалить", callback_data="remove_moder")
        )
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("👥 Управление модераторами:", 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_moder")
def add_moder_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("👤 Введите ID пользователя для назначения модератором:",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_add_moder)

def process_add_moder(message):
    try:
        new_moder_id = int(message.text)
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM personal WHERE ID = ? AND TYPE = ?', (new_moder_id, 'moder'))
            if cursor.fetchone() is None:
                try:
                    bot.send_message(new_moder_id, "🎉 Вам выданы права модератора! Напишите /start, чтобы начать работу.")
                    cursor.execute('INSERT INTO personal (ID, TYPE) VALUES (?, ?)', (new_moder_id, 'moder'))
                    conn.commit()
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
                    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                    bot.send_message(message.chat.id, f"✅ Пользователь {new_moder_id} успешно назначен модератором!", reply_markup=markup)
                except telebot.apihelper.ApiTelegramException:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
                    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                    bot.send_message(message.chat.id, f"❌ Ошибка: Пользователь {new_moder_id} не начал диалог с ботом!", reply_markup=markup)
            else:
                markup = types.InlineKeyboardMarkup()
                markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
                markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                bot.send_message(message.chat.id, "⚠️ Этот пользователь уже является модератором!", reply_markup=markup)
    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, "❌ Ошибка! Введите корректный ID пользователя (только цифры)", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "remove_moder")
def remove_moder_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("👤 Введите ID пользователя для удаления из модераторов:",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_remove_moder)

def process_remove_moder(message):
    try:
        moder_id = int(message.text)
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM personal WHERE ID = ? AND TYPE = ?', (moder_id, 'moder'))
            conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            if cursor.rowcount > 0:
                try:
                    bot.send_message(moder_id, "⚠️ У вас были отозваны права модератора.")
                except:
                    pass
                bot.send_message(message.chat.id, f"✅ Пользователь {moder_id} успешно удален из модераторов!", reply_markup=markup)
            else:
                bot.send_message(message.chat.id, "⚠️ Этот пользователь не является модератором!", reply_markup=markup)
    except ValueError:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, "❌ Ошибка! Введите корректный ID пользователя (только цифры)", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "delete_moderator")
def delete_moderator_request(call):
    if call.from_user.id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ID FROM personal WHERE TYPE = 'moder'")
            moderators = cursor.fetchall()
        
        if not moderators:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.edit_message_text("❌ Нет модераторов для удаления",
                                call.message.chat.id,
                                call.message.message_id,
                                reply_markup=markup)
            return

        text = "👥 Выберите модератора для удаления:\n\n"
        markup = types.InlineKeyboardMarkup()
        for moder in moderators:
            text += f"ID: {moder[0]}\n"
            markup.add(types.InlineKeyboardButton(f"Удалить {moder[0]}", callback_data=f"confirm_delete_moder_{moder[0]}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_delete_moder_"))
def confirm_delete_moderator(call):
    if call.from_user.id in config.ADMINS_ID:
        moder_id = int(call.data.split("_")[3])
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM personal WHERE ID = ? AND TYPE = 'moder'", (moder_id,))
            affected_rows = cursor.rowcount
            conn.commit()
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        if affected_rows > 0:
            try:
                bot.send_message(moder_id, "⚠️ Ваши права модератора были отозваны администратором.")
            except:
                pass
            bot.edit_message_text(f"✅ Модератор с ID {moder_id} успешно удален",
                                call.message.chat.id,
                                call.message.message_id,
                                reply_markup=markup)
        else:
            bot.edit_message_text(f"❌ Модератор с ID {moder_id} не найден",
                                call.message.chat.id,
                                call.message.message_id,
                                reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "broadcast")
def request_broadcast_message(call):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("📢 Введите текст для рассылки:",
                                  call.message.chat.id,
                                  call.message.message_id,
                                  reply_markup=markup)
        bot.register_next_step_handler(msg, process_broadcast_message)

def process_broadcast_message(message):
    if message.from_user.id in config.ADMINS_ID:
        broadcast_text = message.text
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT ID FROM users')
            users = cursor.fetchall()
        
        success = 0
        failed = 0
        for user in users:
            try:
                bot.send_message(user[0], broadcast_text)
                success += 1
            except Exception:
                failed += 1
        
        stats_text = (f"📊 <b>Статистика рассылки:</b>\n\n"
                     f"✅ Успешно отправлено: {success}\n"
                     f"❌ Не удалось отправить: {failed}\n"
                     f"👥 Всего пользователей: {len(users)}")
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📢 Новая рассылка", callback_data="broadcast"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в админ-панель", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, stats_text, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "my_numbers")
def show_my_numbers(call):
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE, STATUS FROM numbers WHERE ID_OWNER = ?', 
                          (call.from_user.id,))
            numbers = cursor.fetchall()

        if not numbers:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.edit_message_text("📭 У вас нет номеров.", 
                                call.message.chat.id, 
                                call.message.message_id, 
                                reply_markup=markup)
            return

        text = "<b>📋 Список твоих номеров:</b>\n\n"
        for number, take_date, shutdown_date, status in numbers:
            text += f"📱 Номер: {number}\n"
            text += f"📊 Статус: {status if status else 'Не указан'}\n"
            if take_date == "0":
                text += "⏳ Ожидает подтверждения\n"
            elif take_date == "1":
                text += "⏳ Ожидает код\n"
            else:
                text += f"🟢 Встал: {take_date}\n"
            if shutdown_date != "0":
                text += f"❌ Слетел: {shutdown_date}\n"
            text += "────────────────────\n"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup,
                            parse_mode='HTML')

    except Exception as e:
        print(f"Ошибка в show_my_numbers: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("❌ Произошла ошибка при получении списка номеров.", 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup)
        

@bot.callback_query_handler(func=lambda call: call.data == "settings")
def show_settings(call):
    if call.from_user.id in config.ADMINS_ID:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
            result = cursor.fetchone()
            price, hold_time = result if result else (2.0, 5)
        
        settings_text = (
            "<b>⚙️ Настройки оплаты</b>\n\n"
            f"Текущая ставка: <code>{price}$</code> за номер\n"
            f"Время холда: <code>{hold_time}</code> минут\n\n"
            "Выберите параметр для изменения:"
        )
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("💰 Изменить сумму", callback_data="change_amount"))
        markup.add(types.InlineKeyboardButton("⏱ Изменить время холда", callback_data="change_hold_time"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        
        bot.edit_message_text(settings_text,
                            call.message.chat.id,
                            call.message.message_id,
                            parse_mode='HTML',
                            reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "change_amount")
def change_amount_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("💰 Введите новую сумму оплаты (в долларах, например: 2):",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_change_amount)

def process_change_amount(message):
    if message.from_user.id in config.ADMINS_ID:
        try:
            new_amount = float(message.text)
            if new_amount <= 0:
                raise ValueError
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE settings SET PRICE = ?', (new_amount,))
                conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, f"✅ Сумма оплаты изменена на {new_amount}$", reply_markup=markup)
        except ValueError:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ Введите корректное положительное число!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "change_hold_time")
def change_hold_time_request(call):
    if call.from_user.id in config.ADMINS_ID:
        msg = bot.edit_message_text("⏱ Введите новое время холда (в минутах, например: 5):",
                                  call.message.chat.id,
                                  call.message.message_id)
        bot.register_next_step_handler(msg, process_change_hold_time)

def process_change_hold_time(message):
    if message.from_user.id in config.ADMINS_ID:
        try:
            new_time = int(message.text)
            if new_time <= 0:
                raise ValueError
            with db.get_db() as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE settings SET HOLD_TIME = ?', (new_time,))
                conn.commit()
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, f"✅ Время холда изменено на {new_time} минут", reply_markup=markup)
        except ValueError:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="settings"))
            markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            bot.send_message(message.chat.id, "❌ Введите корректное положительное целое число!", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "get_number")
def get_number_callback(call):
    if not db.is_moderator(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ У вас нет прав модератора!")
        return

    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            
            # Проверяем, есть ли у модератора уже взятый номер, который ещё не обработан
            cursor.execute('''SELECT NUMBER 
                            FROM numbers 
                            WHERE MODERATOR_ID = ? 
                            AND SHUTDOWN_DATE = "0" 
                            AND VERIFICATION_CODE IS NULL''', 
                          (call.from_user.id,))
            existing_number = cursor.fetchone()

            if existing_number:
                number = existing_number[0]
                message_text = (f"📱 <b>Номер:</b> {number}\n"
                               "⚙️ Вы уже взяли этот номер на проверку.\n"
                               "Ожидайте код от владельца или отметьте номер как невалидный.")
            else:
                # Ищем новый номер для модерации
                cursor.execute('''SELECT * 
                                FROM numbers 
                                WHERE TAKE_DATE = "0"
                                AND MODERATOR_ID IS NULL
                                AND SHUTDOWN_DATE = "0"
                                AND (STATUS = "ожидает" OR STATUS IS NULL)
                                ORDER BY RANDOM()
                                LIMIT 1''')
                number_data = cursor.fetchone()

                if not number_data:
                    markup = types.InlineKeyboardMarkup()
                    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
                    bot.edit_message_text("❌ Нет доступных номеров для модерации.", 
                                        call.message.chat.id, 
                                        call.message.message_id, 
                                        reply_markup=markup)
                    return

                number = number_data[0]  # NUMBER — первый столбец в таблице numbers
                owner_id = number_data[1]  # ID_OWNER — второй столбец

                # Обновляем данные номера: модератор берёт его на проверку
                cursor.execute('''UPDATE numbers 
                                SET TAKE_DATE = "1", 
                                    MODERATOR_ID = ?,
                                    SHUTDOWN_DATE = "0",
                                    VERIFICATION_CODE = NULL,
                                    STATUS = "проверка кода"
                                WHERE NUMBER = ?''', 
                              (call.from_user.id, number))
                conn.commit()

                # Уведомляем владельца номера
                markup_owner = types.InlineKeyboardMarkup()
                markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
                try:
                    bot.send_message(owner_id, 
                                    f"📱 Ваш номер {number} взят на проверку модератором.\n"
                                    "Ожидайте запрос кода.",
                                    reply_markup=markup_owner)
                except Exception as e:
                    print(f"Не удалось уведомить владельца {owner_id}: {e}")

                message_text = (f"📱 <b>Номер:</b> {number}\n"
                               "⚙️ Номер взят на проверку.\n"
                               "Запросите код у владельца.")

            # Создаём кнопки для модератора
            markup_mod = types.InlineKeyboardMarkup()
            markup_mod.add(types.InlineKeyboardButton("✉️ Отправить код", callback_data=f"send_code_{number}"))
            markup_mod.add(types.InlineKeyboardButton("❌ Не валидный", callback_data=f"invalid_{number}"))
            markup_mod.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
            bot.edit_message_text(message_text, 
                                call.message.chat.id, 
                                call.message.message_id, 
                                reply_markup=markup_mod,
                                parse_mode='HTML')

    except Exception as e:
        print(f"Ошибка в get_number_callback: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        bot.edit_message_text("❌ Произошла ошибка при получении номера. Попробуйте снова.", 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup)
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("send_code_"))
def send_verification_code(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
    
    if owner:
        markup = types.ReplyKeyboardRemove()
        msg = bot.send_message(owner[0], f"📱 Введите код для номера {number}, который будет отправлен модератору:", reply_markup=markup)
        bot.edit_message_text(f"📱 Номер: {number}\n✉️ Запрос кода отправлен владельцу.", call.message.chat.id, call.message.message_id)
                
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('UPDATE numbers SET VERIFICATION_CODE = "" WHERE NUMBER = ?', (number,))
            cursor.execute('UPDATE numbers SET MODERATOR_ID = ? WHERE NUMBER = ?', (call.from_user.id, number))
            conn.commit()
        
        bot.register_next_step_handler(msg, process_verification_code_input, number, call.from_user.id)

def process_verification_code_input(message, number, moderator_id):
    user_input = message.text.strip()
    
    if not user_input:
        markup = types.ReplyKeyboardRemove()
        msg = bot.send_message(message.chat.id, "❌ Код не может быть пустым! Введите код:", reply_markup=markup)
        bot.register_next_step_handler(msg, process_verification_code_input, number, moderator_id)
        return

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET VERIFICATION_CODE = ? WHERE NUMBER = ?', (user_input, number))
        conn.commit()

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("✅ Да, код верный", callback_data=f"confirm_code_{number}_{user_input}"),
        types.InlineKeyboardButton("❌ Нет, изменить", callback_data=f"change_code_{number}")
    )
    bot.send_message(message.chat.id, f"Вы ввели код: {user_input}\nЭто правильный код?", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_code_"))
def confirm_code(call):
    number = call.data.split("_")[2]
    code = "_".join(call.data.split("_")[3:])
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            # Получаем ID модератора
            cursor.execute('SELECT MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
            result = cursor.fetchone()
            if not result:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            moderator_id = result[0]
        
        # Уведомляем владельца
        bot.send_message(call.from_user.id, f"✅ Код '{code}' отправлен модератору.")
        
        # Отправляем код модератору и запрашиваем, встал ли номер
        if moderator_id:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("✅ Да, встал", callback_data=f"number_active_{number}"))
            markup.add(types.InlineKeyboardButton("❌ Нет, изменить", callback_data=f"number_invalid_{number}"))
            bot.send_message(moderator_id, 
                            f"📱 Код по вашему номеру {number}\nКод: {code}\n\n"
                            "Встал ли номер?", 
                            reply_markup=markup)
    
    except Exception as e:
        print(f"Ошибка в confirm_code: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при подтверждении кода.")
        

@bot.callback_query_handler(func=lambda call: call.data.startswith("change_code_"))
def change_code(call):
    number = call.data.split("_")[2]
    
    markup = types.ReplyKeyboardRemove()
    msg = bot.send_message(call.from_user.id, "Введите новый код:", reply_markup=markup)
    bot.register_next_step_handler(msg, process_verification_code_input, number, call.from_user.id)

    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET VERIFICATION_CODE = "" WHERE NUMBER = ?', (number,))
        conn.commit()

def create_back_to_main_markup():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    return markup

@bot.callback_query_handler(func=lambda call: call.data.startswith("code_entered_"))
def confirm_verification_code(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET VERIFICATION_CODE = NULL WHERE NUMBER = ?', (number,))
        cursor.execute('SELECT MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
        moderator_id = cursor.fetchone()[0]
        conn.commit()

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    bot.edit_message_text(f"✅ Код для номера {number} отправлен модератору.", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup)

    if moderator_id:
        markup_mod = types.InlineKeyboardMarkup()
        markup_mod.add(
            types.InlineKeyboardButton("✅ Подтвердить", callback_data=f"moderator_confirm_{number}"),
            types.InlineKeyboardButton("❌ Не встал", callback_data=f"moderator_reject_{number}")
        )
        try:
            bot.send_message(moderator_id, 
                           f"📱 Номер {number} готов к подтверждению.\nПожалуйста, подтвердите или отклоните.", 
                           reply_markup=markup_mod)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("code_error_"))
def handle_verification_error(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
        moderator_id = cursor.fetchone()[0]
        cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
        conn.commit()
    
    bot.edit_message_text(f"❌ Номер {number} удалён из системы из-за ошибки в коде.", 
                         call.message.chat.id, 
                         call.message.message_id)

    for admin_id in config.ADMINS_ID:
        try:
            bot.send_message(admin_id, f"❌ Код был неправильный, номер {number} из очереди удалён.")
        except:
            pass

    if moderator_id:
        markup_mod = types.InlineKeyboardMarkup()
        markup_mod.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
        markup_mod.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        try:
            bot.send_message(moderator_id, 
                           f"❌ Номер {number} был удалён владельцем из-за ошибки в коде.", 
                           reply_markup=markup_mod)
        except:
            pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("moderator_reject_"))
def handle_number_rejection(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
        cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
        conn.commit()

        if owner:
            markup_owner = types.InlineKeyboardMarkup()
            markup_owner.add(types.InlineKeyboardButton("📱 Сдать номер снова", callback_data="submit_number"))
            markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            try:
                bot.send_message(owner[0], 
                               f"❌ Ваш номер {number} был отклонен модератором.\n📱 Проверьте номер и сдайте заново.", 
                               reply_markup=markup_owner)
            except:
                pass

    markup_mod = types.InlineKeyboardMarkup()
    markup_mod.add(types.InlineKeyboardButton("📲 Получить новый номер", callback_data="get_number"))
    markup_mod.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    bot.edit_message_text(f"📱 Номер {number} отклонен и удалён из очереди.\n❌ Номер не встал.", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup_mod)

@bot.callback_query_handler(func=lambda call: call.data.startswith("moderator_confirm_"))
def moderator_confirm_number(call):
    number = call.data.split("_")[2]
    current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET STATUS = "активен", MODERATOR_ID = NULL, CONFIRMED_BY_MODERATOR_ID = ?, TAKE_DATE = ? WHERE NUMBER = ?', 
                      (call.from_user.id, current_date, number))
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
        conn.commit()

    if owner:
        markup_owner = types.InlineKeyboardMarkup()
        markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.send_message(owner[0], 
                        "✅ Ваш номер подтвержден и поставлен в работу. Оплата будет начислена через 5 минут, если номер не слетит.",
                        reply_markup=markup_owner)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
    bot.edit_message_text(f"📱 Номер {number} поставлен в работу. Оплата будет начислена через 5 минут, если номер не слетит.", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "moderator_numbers")
def moderator_numbers(call):
    if not db.is_moderator(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ У вас нет прав модератора!")
        return

    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            # Номера, которые модератор взял на модерацию (ещё не подтверждены)
            cursor.execute('SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE, STATUS FROM numbers WHERE MODERATOR_ID = ?', 
                          (call.from_user.id,))
            active_numbers = cursor.fetchall()
            
            # Номера, которые модератор подтвердил (включая слетевшие)
            cursor.execute('SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE, STATUS FROM numbers WHERE CONFIRMED_BY_MODERATOR_ID = ?', 
                          (call.from_user.id,))
            confirmed_numbers = cursor.fetchall()

        response = "📱 <b>Список ваших арендованных номеров:</b>\n\n"
        markup = types.InlineKeyboardMarkup()
        has_numbers = False

        if active_numbers:
            has_numbers = True
            response += "🔧 Номера в обработке:\n\n"
            for number, take_date, shutdown_date, status in active_numbers:
                response += f"📱 Номер: {number}\n"
                response += f"📊 Статус: {status if status else 'Не указан'}\n"
                if take_date == "0":
                    response += "⏳ Ожидает подтверждения\n"
                elif take_date == "1":
                    response += "⏳ Ожидает код\n"
                else:
                    response += f"🟢 Встал: {take_date}\n"
                if shutdown_date != "0":
                    response += f"❌ Слетел: {shutdown_date}\n"
                response += "────────────────────\n"
                markup.add(types.InlineKeyboardButton(f"📱 {number}", callback_data=f"moderator_number_{number}"))

        if confirmed_numbers:
            has_numbers = True
            response += "✅ Подтверждённые номера:\n\n"
            for number, take_date, shutdown_date, status in confirmed_numbers:
                response += f"📱 Номер: {number}\n"
                response += f"📊 Статус: {status if status else 'Не указан'}\n"
                if take_date == "0":
                    response += "⏳ Ожидает подтверждения\n"
                elif take_date == "1":
                    response += "⏳ Ожидает код\n"
                else:
                    response += f"🟢 Встал: {take_date}\n"
                if shutdown_date != "0":
                    response += f"❌ Слетел: {shutdown_date}\n"
                response += "────────────────────\n"
                markup.add(types.InlineKeyboardButton(f"📱 {number}", callback_data=f"moderator_number_{number}"))

        if not has_numbers:
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
            bot.edit_message_text("📱 У вас нет арендованных номеров.", 
                                call.message.chat.id, 
                                call.message.message_id, 
                                reply_markup=markup)
        else:
            markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
            bot.edit_message_text(response, 
                                call.message.chat.id, 
                                call.message.message_id, 
                                reply_markup=markup,
                                parse_mode='HTML')

    except Exception as e:
        print(f"Ошибка в moderator_numbers: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        bot.edit_message_text("❌ Произошла ошибка при получении списка номеров.", 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup)
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("number_active_"))
def number_active(call):
    number = call.data.split("_")[2]
    
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            # Обновляем статус номера на "активен" и устанавливаем TAKE_DATE
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('''UPDATE numbers 
                            SET STATUS = "активен", 
                                TAKE_DATE = ?, 
                                CONFIRMED_BY_MODERATOR_ID = ?, 
                                MODERATOR_ID = NULL 
                            WHERE NUMBER = ?''', 
                          (current_time, call.from_user.id, number))
            conn.commit()
            
            # Получаем ID владельца
            cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
            owner_id = cursor.fetchone()[0]
        
        # Уведомляем модератора
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(f"✅ Номер {number} подтверждён и теперь активен.\n"
                             "📝 Укажите, если номер слетит, в разделе «Мои номера».", 
                             call.message.chat.id, 
                             call.message.message_id, 
                             reply_markup=markup)
        
        # Уведомляем владельца
        bot.send_message(owner_id, f"✅ Ваш номер {number} подтверждён и теперь активен.\n"
                                  "⏳ Отсчёт времени начался.")
    
    except Exception as e:
        print(f"Ошибка в number_active: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при подтверждении номера.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("number_invalid_"))
def number_invalid(call):
    number = call.data.split("_")[2]
    
    try:
        # Возвращаем модератору возможность запросить код заново или отметить как невалидный
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("✉️ Отправить код заново", callback_data=f"send_code_{number}"))
        markup.add(types.InlineKeyboardButton("❌ Не валидный", callback_data=f"invalid_{number}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_main"))
        bot.edit_message_text(f"📱 Номер: {number}\n"
                             "Пожалуйста, выберите действие:", 
                             call.message.chat.id, 
                             call.message.message_id, 
                             reply_markup=markup)
    
    except Exception as e:
        print(f"Ошибка в number_invalid: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке номера.")


@bot.callback_query_handler(func=lambda call: call.data.startswith("moderator_number_"))
def show_number_details(call):
    number = call.data.split("_")[2]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT STATUS, TAKE_DATE, SHUTDOWN_DATE, MODERATOR_ID, CONFIRMED_BY_MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
        data = cursor.fetchone()

    if data:
        status, take_date, shutdown_date, moderator_id, confirmed_by_moderator_id = data
        text = (f"📱 <b>Статус номера:</b> {status}\n"
                f"📱 <b>Номер:</b> {number}\n")
        if take_date not in ("0", "1"):
            text += f"🟢 <b>Встал:</b> {take_date}\n"
        if shutdown_date != "0":
            text += f"❌ <b>Слетел:</b> {shutdown_date}\n"

        markup = types.InlineKeyboardMarkup()
        # Показываем кнопку "Слетел" только для активных номеров (SHUTDOWN_DATE = "0")
        # и только если номер либо в обработке (MODERATOR_ID), либо подтверждён (CONFIRMED_BY_MODERATOR_ID)
        if shutdown_date == "0" and (moderator_id == call.from_user.id or confirmed_by_moderator_id == call.from_user.id):
            markup.add(types.InlineKeyboardButton("🔴 Слетел", callback_data=f"number_failed_{number}"))
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="moderator_numbers"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup,
                            parse_mode='HTML')
        
@bot.callback_query_handler(func=lambda call: call.data.startswith("number_failed_"))
def handle_number_failed(call):
    number = call.data.split("_")[2]
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            # Получаем данные о номере
            cursor.execute('SELECT TAKE_DATE, ID_OWNER, CONFIRMED_BY_MODERATOR_ID FROM numbers WHERE NUMBER = ?', (number,))
            data = cursor.fetchone()
            if not data:
                bot.answer_callback_query(call.id, "❌ Номер не найден!")
                return
            
            take_date, owner_id, confirmed_by_moderator_id = data
            
            # Получаем HOLD_TIME из настроек
            cursor.execute('SELECT HOLD_TIME FROM settings')
            result = cursor.fetchone()
            hold_time = result[0] if result else 5  # По умолчанию 5 минут
            
            # Вычисляем время работы
            end_time = datetime.now()
            if take_date in ("0", "1"):
                work_time = 0  # Если номер ещё не подтверждён, время работы = 0
                worked_enough = False
            else:
                start_time = datetime.strptime(take_date, "%Y-%m-%d %H:%M:%S")
                work_time = (end_time - start_time).total_seconds() / 60  # Время в минутах
                worked_enough = work_time >= hold_time
            
            # Обновляем статус номера
            shutdown_date = end_time.strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute('UPDATE numbers SET SHUTDOWN_DATE = ?, STATUS = "слетел" WHERE NUMBER = ?', 
                          (shutdown_date, number))
            conn.commit()
        
        # Формируем сообщение для модератора
        mod_message = (f"❌ Номер {number} отмечен как слетевший.\n"
                      f"⏳ Время работы: {work_time:.2f} минут\n")
        if take_date not in ("0", "1"):
            mod_message += f"🟢 Встал: {take_date}\n"
        mod_message += f"❌ Слетел: {shutdown_date}\n"
        if not worked_enough:
            mod_message += f"⚠️ Номер не отработал минимальное время ({hold_time} минут)!"
        
        # Уведомляем владельца
        owner_message = (f"❌ Ваш номер {number} слетел.\n"
                        f"⏳ Время работы: {work_time:.2f} минут")
        if not worked_enough:
            owner_message += f"\n⚠️ Номер не отработал минимальное время ({hold_time} минут)!"
        bot.send_message(owner_id, owner_message)
        
        # Обновляем сообщение модератору
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="moderator_numbers"))
        bot.edit_message_text(mod_message, 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup,
                            parse_mode='HTML')
    
    except Exception as e:
        print(f"Ошибка в handle_number_failed: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка при обработке номера.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("invalid_"))
def handle_invalid_number(call):
    number = call.data.split("_")[1]
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT ID_OWNER FROM numbers WHERE NUMBER = ?', (number,))
        owner = cursor.fetchone()
        cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))
        conn.commit()

        if owner:
            markup_owner = types.InlineKeyboardMarkup()
            markup_owner.add(types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number"))
            markup_owner.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
            try:
                bot.send_message(owner[0], 
                               f"❌ Ваш номер был отклонен модератором.\n📱 Проверьте номер и сдайте заново.", 
                               reply_markup=markup_owner)
            except:
                pass

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.edit_message_text("✅ Номер успешно удален из системы", 
                         call.message.chat.id, 
                         call.message.message_id, 
                         reply_markup=markup)

def is_russian_number(phone_number):
    # Удаляем пробелы и лишние символы
    phone_number = phone_number.strip()
    # Если номер начинается с "7" или "8", добавляем "+7"
    if phone_number.startswith("7") or phone_number.startswith("8"):
        phone_number = "+7" + phone_number[1:]
    # Если номер не начинается с "+", добавляем его
    if not phone_number.startswith("+"):
        phone_number = "+" + phone_number
    # Проверяем формат: +7 и 10 цифр после
    pattern = r'^\+7\d{10}$'
    return phone_number if bool(re.match(pattern, phone_number)) else None

@bot.callback_query_handler(func=lambda call: call.data == "submit_number")
def request_number(call):
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    msg = bot.send_message(call.message.chat.id, 
                         f"📱 Введите ваши номера телефона (по одному в строке):\nПример:\n+79991234567\n+79001234567\n+79021234567\n💵 Текущая цена: {price}$ за номер\n⏱ Холд: {hold_time} минут",
                         reply_markup=markup,
                         parse_mode='HTML')
    bot.register_next_step_handler(msg, process_numbers)

def process_numbers(message):
    # Проверяем, что сообщение содержит текст
    if not message or not message.text:
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📱 Попробовать снова", callback_data="submit_number"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, "❌ Пожалуйста, отправьте номера текстом!", reply_markup=markup)
        return

    # Разбиваем введённый текст на список номеров
    numbers = message.text.strip().split('\n')
    if not numbers or all(not num.strip() for num in numbers):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📱 Попробовать снова", callback_data="submit_number"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, "❌ Вы не указали ни одного номера!", reply_markup=markup)
        return

    valid_numbers = []
    invalid_numbers = []
    
    # Проверяем и корректируем номера
    for number in numbers:
        number = number.strip()
        if not number:  # Пропускаем пустые строки
            continue
        corrected_number = is_russian_number(number)
        if corrected_number:
            valid_numbers.append(corrected_number)
        else:
            invalid_numbers.append(number)

    # Если нет валидных номеров, сообщаем об этом
    if not valid_numbers:
        response_text = "❌ Все введённые номера некорректны!\nПожалуйста, вводите номера в формате +79991234567."
        if invalid_numbers:
            response_text += "\n\n❌ Неверный формат:\n" + "\n".join(invalid_numbers)
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("📱 Попробовать снова", callback_data="submit_number"))
        markup.add(types.InlineKeyboardButton("🔙 Вернуться в меню", callback_data="back_to_main"))
        bot.send_message(message.chat.id, response_text, reply_markup=markup, parse_mode='HTML')
        return

    # Добавляем валидные номера в базу данных
    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            success_count = 0
            already_exists = 0
            successfully_added = []  # Список успешно добавленных номеров

            for number in valid_numbers:
                try:
                    # Проверяем, существует ли номер в базе
                    cursor.execute('SELECT NUMBER, SHUTDOWN_DATE FROM numbers WHERE NUMBER = ?', (number,))
                    existing_number = cursor.fetchone()

                    if existing_number:
                        if existing_number[1] == "0":  # Номер активен
                            already_exists += 1
                            continue
                        else:
                            # Удаляем старый номер, чтобы можно было добавить новый
                            cursor.execute('DELETE FROM numbers WHERE NUMBER = ?', (number,))

                    # Добавляем новый номер
                    cursor.execute('INSERT INTO numbers (NUMBER, ID_OWNER, TAKE_DATE, SHUTDOWN_DATE, STATUS) VALUES (?, ?, ?, ?, ?)',
                                  (number, message.from_user.id, '0', '0', 'ожидает'))
                    success_count += 1
                    successfully_added.append(number)
                except sqlite3.IntegrityError:
                    already_exists += 1
                    continue
            conn.commit()

        # Формируем ответ
        response_text = "<b>📊 Результат добавления номеров:</b>\n\n"
        if success_count > 0:
            response_text += f"✅ Успешно добавлено: {success_count} номеров\n"
            response_text += "📱 Добавленные номера:\n" + "\n".join(successfully_added) + "\n"
        if already_exists > 0:
            response_text += f"⚠️ Уже существуют: {already_exists} номеров\n"
        if invalid_numbers:
            response_text += f"❌ Неверный формат:\n" + "\n".join(invalid_numbers) + "\n"

        # Логируем добавленные номера
        print(f"Пользователь {message.from_user.id} добавил номера: {successfully_added}")

    except Exception as e:
        print(f"Ошибка в process_numbers: {e}")
        response_text = "❌ Произошла ошибка при добавлении номеров. Попробуйте снова."

    # Отправляем ответ пользователю
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📱 Добавить ещё", callback_data="submit_number"))
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
    bot.send_message(message.chat.id, response_text, reply_markup=markup, parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: call.data == "all_numbers")
def show_all_numbers(call):
    if call.from_user.id not in config.ADMINS_ID:
        bot.answer_callback_query(call.id, "❌ У вас нет прав для просмотра списка номеров!")
        return

    try:
        with db.get_db() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT NUMBER, ID_OWNER, TAKE_DATE, SHUTDOWN_DATE, MODERATOR_ID, STATUS, CONFIRMED_BY_MODERATOR_ID FROM numbers')
            numbers = cursor.fetchall()

        if not numbers:
            text = "📭 Номеров нет в базе данных."
        else:
            text = "<b>📋 Список всех номеров:</b>\n\n"
            for number, owner_id, take_date, shutdown_date, moderator_id, status, confirmed_by_moderator_id in numbers:
                text += f"📱 <b>Номер:</b> {number}\n"
                text += f"👤 <b>Владелец:</b> {owner_id}\n"
                text += f"📊 <b>Статус:</b> {status if status else 'Не указан'}\n"
                if take_date == "0":
                    text += "⏳ Ожидает подтверждения\n"
                elif take_date == "1":
                    text += "⏳ Ожидает код\n"
                else:
                    text += f"🟢 Встал: {take_date}\n"
                if shutdown_date != "0":
                    text += f"❌ Слетел: {shutdown_date}\n"
                if moderator_id:
                    text += f"🛡 <b>Модератор:</b> {moderator_id}\n"
                if confirmed_by_moderator_id:
                    text += f"✅ <b>Подтвердил:</b> {confirmed_by_moderator_id}\n"
                text += "────────────────────\n"

        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')

    except Exception as e:
        print(f"Ошибка в show_all_numbers: {e}")
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_panel"))
        markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main"))
        bot.edit_message_text("❌ Произошла ошибка при получении списка номеров.", 
                            call.message.chat.id, 
                            call.message.message_id, 
                            reply_markup=markup)
                
@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main(call):
    user_id = call.from_user.id
    
    with db.get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT PRICE, HOLD_TIME FROM settings')
        result = cursor.fetchone()
        price, hold_time = result if result else (2.0, 5)
        
        cursor.execute('SELECT NUMBER FROM numbers WHERE MODERATOR_ID = ? AND SHUTDOWN_DATE = "0" AND VERIFICATION_CODE IS NULL', 
                      (user_id,))
        active_number = cursor.fetchone()
    
    # Определяем роли пользователя
    is_admin = user_id in config.ADMINS_ID
    is_moderator = db.is_moderator(user_id)

    # Текст приветствия
    if is_moderator and not is_admin:
        # Только модератор
        welcome_text = "📝 <b>Заявки</b>"
    else:
        # Обычный пользователь или администратор (включая случай, если он также модератор)
        welcome_text = (
            f"<b>📢 Добро пожаловать в {config.SERVICE_NAME}</b>\n\n"
            f"<b>⏳ График работы:</b> <code>{config.WORK_TIME}</code>\n\n"
            "<b>💼 Как это работает?</b>\n"
            "• <i>Вы продаёте номер</i> – <b>мы предоставляем стабильные выплаты.</b>\n"
            f"• <i>Моментальные выплаты</i> – <b>после {hold_time} минут работы.</b>\n\n"
            "<b>💰 Тарифы на сдачу номеров:</b>\n"
            f"▪️ <code>{price}$</code> за номер (холд {hold_time} минут)\n"
            f"<b>📍 Почему выбирают {config.SERVICE_NAME} ?</b>\n"
            "✅ <i>Прозрачные условия сотрудничества</i>\n"
            "✅ <i>Выгодные тарифы и моментальные выплаты</i>\n"
            "✅ <i>Оперативная поддержка 24/7</i>\n\n"
            "<b>🔹 Начните зарабатывать прямо сейчас!</b>"
        )
    
    if active_number and is_moderator:
        welcome_text += f"\n\n⚠️ У вас есть активный номер: {active_number[0]}\nПродолжите работу с ним в разделе 'Получить номер'."
    
    markup = types.InlineKeyboardMarkup()
    
    # Добавляем кнопки в зависимости от роли пользователя
    # Кнопки "Сдать номер" и "Мой профиль" для обычных пользователей и администраторов
    if not is_moderator or is_admin:
        markup.row(
            types.InlineKeyboardButton("👤 Мой профиль", callback_data="profile"),
            types.InlineKeyboardButton("📱 Сдать номер", callback_data="submit_number")
        )
    
    # Кнопка "Админка" для администратора
    if is_admin:
        markup.add(types.InlineKeyboardButton("⚙️ Админка", callback_data="admin_panel"))
    
    # Кнопки для модератора
    if is_moderator:
        markup.add(
            types.InlineKeyboardButton("📲 Получить номер", callback_data="get_number"),
            types.InlineKeyboardButton("📱 Мои номера", callback_data="moderator_numbers")
        )
    
    bot.edit_message_text(welcome_text, 
                         call.message.chat.id, 
                         call.message.message_id, 
                         parse_mode='HTML', 
                         reply_markup=markup)

if __name__ == "__main__":
    run_bot()