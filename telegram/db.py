import sqlite3
from datetime import datetime

def get_db():
    """Функция для подключения к базе данных"""
    return sqlite3.connect('database.db', check_same_thread=False)

def create_tables():
    """Функция для создания таблиц в базе данных"""
    with get_db() as conn:
        cursor = conn.cursor()

        cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS withdraws (
                ID INTEGER PRIMARY KEY,
                AMOUNT REAL,
                DATE TEXT,
                STATUS TEXT DEFAULT 'pending'
            )
        ''')
        
        cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS users (
                ID INTEGER PRIMARY KEY,
                BALANCE INTEGER DEFAULT 0,
                REG_DATE TEXT
            )
        ''')
        
        cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS numbers (
                NUMBER TEXT PRIMARY KEY,
                ID_OWNER INTEGER,
                TAKE_DATE TEXT DEFAULT "0",
                SHUTDOWN_DATE TEXT DEFAULT "0",
                MODERATOR_ID INTEGER,
                VERIFICATION_CODE TEXT,
                STATUS TEXT DEFAULT 'активен'
            )
        ''')
        
        # Проверяем, существует ли столбец CONFIRMED_BY_MODERATOR_ID, и добавляем его, если нет
        cursor.execute("PRAGMA table_info(numbers)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'CONFIRMED_BY_MODERATOR_ID' not in columns:
            cursor.execute('ALTER TABLE numbers ADD COLUMN CONFIRMED_BY_MODERATOR_ID INTEGER')

        cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS settings (
                CRYPTO_PAY TEXT,
                PRICE TEXT,
                MIN_TIME INTEGER DEFAULT 30
            )
        ''')
        
        cursor.execute(''' 
            CREATE TABLE IF NOT EXISTS personal (
                ID INTEGER PRIMARY KEY,
                TYPE TEXT
            )
        ''')
        
        # Инициализация настроек по умолчанию, если их нет
        cursor.execute('SELECT COUNT(*) FROM settings')
        if cursor.fetchone()[0] == 0:
            cursor.execute('INSERT INTO settings (PRICE, MIN_TIME) VALUES (?, ?)',
                         ("4/30", 30))  # Значения по умолчанию: 4$ за 30 минут, мин. время 30 минут
        
        conn.commit()

def add_user(user_id, balance=0, reg_date=None):
    """Функция для добавления нового пользователя"""
    if reg_date is None:
        reg_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT OR IGNORE INTO users (ID, BALANCE, REG_DATE) VALUES (?, ?, ?)', 
                       (user_id, balance, reg_date))
        conn.commit()

def update_balance(user_id, amount):
    """Функция для обновления баланса пользователя"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE users SET BALANCE = BALANCE + ? WHERE ID = ?', (amount, user_id))
        conn.commit()

def add_number(number, user_id):
    """Функция для добавления нового номера"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('INSERT INTO numbers (NUMBER, ID_OWNER, TAKE_DATE, SHUTDOWN_DATE) VALUES (?, ?, ?, ?)', 
                       (number, user_id, '0', '0'))
        conn.commit()

def update_number_status(number, status, moderator_id=None):
    """Функция для обновления статуса номера"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('UPDATE numbers SET SHUTDOWN_DATE = ?, MODERATOR_ID = ? WHERE NUMBER = ?', 
                       (status, moderator_id, number))
        conn.commit()

def get_user_numbers(user_id):
    """Функция для получения всех номеров пользователя"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT NUMBER, TAKE_DATE, SHUTDOWN_DATE FROM numbers WHERE ID_OWNER = ?''', (user_id,))
        numbers = cursor.fetchall()
    return numbers

def is_moderator(user_id):
    """Функция для проверки, является ли пользователь модератором"""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ID FROM personal WHERE ID = ? AND TYPE = 'moder'", (user_id,))
        return cursor.fetchone() is not None

# Создаём таблицы при импорте модуля
create_tables()