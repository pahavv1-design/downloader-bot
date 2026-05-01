import sqlite3
from datetime import datetime

def init_db():
    with sqlite3.connect('bot.db') as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS users 
                        (user_id INTEGER PRIMARY KEY, downloads_today INTEGER DEFAULT 0, last_date TEXT)''')

def add_user(user_id):
    today = datetime.now().strftime('%Y-%m-%d')
    with sqlite3.connect('bot.db') as conn:
        conn.execute('INSERT OR IGNORE INTO users (user_id, last_date) VALUES (?, ?)', (user_id, today))

def check_limit(user_id, max_limit):
    today = datetime.now().strftime('%Y-%m-%d')
    with sqlite3.connect('bot.db') as conn:
        user = conn.execute('SELECT downloads_today, last_date FROM users WHERE user_id = ?', (user_id,)).fetchone()
        if not user: return True
        downloads, last_date = user
        if last_date != today:
            conn.execute('UPDATE users SET downloads_today = 0, last_date = ? WHERE user_id = ?', (today, user_id))
            return True
        return downloads < max_limit

def increment_limit(user_id):
    with sqlite3.connect('bot.db') as conn:
        conn.execute('UPDATE users SET downloads_today = downloads_today + 1 WHERE user_id = ?', (user_id,))

def get_stats():
    with sqlite3.connect('bot.db') as conn:
        return conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]

def get_all_users():
    with sqlite3.connect('bot.db') as conn:
        return [row[0] for row in conn.execute('SELECT user_id FROM users').fetchall()]
