import os
import sqlite3
from contextlib import contextmanager
from config import DATABASE_PATH


# -----------------------------
# اتصال به دیتابیس
# -----------------------------

def _ensure_directory():
    directory = os.path.dirname(DATABASE_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)


@contextmanager
def get_db():
    _ensure_directory()

    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
        isolation_level=None
    )

    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        yield conn
    finally:
        conn.close()


# -----------------------------
# ساخت جداول
# -----------------------------

def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL DEFAULT '',
                username TEXT NOT NULL DEFAULT '',
                balance INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tx_key TEXT UNIQUE NOT NULL,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                tx_type TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                bet INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                payout INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                finished_at TEXT
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_balance
            ON users(balance)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_user
            ON transactions(user_id)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_games_user
            ON games(user_id)
        """)

        # بات به صورت پیش‌فرض روشن است
        db.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            VALUES('bot_enabled', '1')
        """)


# -----------------------------
# ثبت / بروزرسانی کاربر
# -----------------------------

def register_user(user_id, first_name="", username=""):
    user_id = int(user_id)
    first_name = first_name or ""
    username = username or ""

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        try:
            db.execute("""
                INSERT INTO users(
                    user_id,
                    first_name,
                    username,
                    balance
                )
                VALUES(?, ?, ?, 0)

                ON CONFLICT(user_id) DO UPDATE SET
                    first_name=excluded.first_name,
                    username=excluded.username,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                user_id,
                first_name,
                username
            ))

            db.execute("COMMIT")

        except Exception:
            db.execute("ROLLBACK")
            raise


# -----------------------------
# گرفتن کاربر
# -----------------------------

def get_user(user_id):
    with get_db() as db:
        return db.execute("""
            SELECT *
            FROM users
            WHERE user_id = ?
        """, (int(user_id),)).fetchone()


# -----------------------------
# گرفتن موجودی
# -----------------------------

def get_balance(user_id):
    with get_db() as db:
        row = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id = ?
        """, (int(user_id),)).fetchone()

        if row is None:
            return 0

        return int(row["balance"])


# -----------------------------
# تغییر اتمیک موجودی
# -----------------------------

def change_balance(
    user_id,
    amount,
    tx_type,
    tx_key,
    description=""
):
    """
    تغییر موجودی به صورت اتمیک.

    amount مثبت = شارژ
    amount منفی = کسر

    tx_key باید برای هر عملیات یکتا باشد.
    این باعث می‌شود یک عملیات دوبار اعمال نشود.
    """

    user_id = int(user_id)
    amount = int(amount)
    tx_key = str(tx_key)

    if not tx_key:
        raise ValueError("tx_key cannot be empty")

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        try:
            # ضد دوباره پرداخت
            existing = db.execute("""
                SELECT *
                FROM transactions
                WHERE tx_key = ?
            """, (tx_key,)).fetchone()

            if existing:
                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "balance": int(existing["balance_after"]),
                    "transaction_id": int(existing["id"])
                }

            # کاربر وجود داشته باشد
            user = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id = ?
            """, (user_id,)).fetchone()

            if user is None:
                db.execute("""
                    INSERT INTO users(
                        user_id,
                        first_name,
                        username,
                        balance
                    )
                    VALUES(?, '', '', 0)
                """, (user_id,))

                old_balance = 0
            else:
                old_balance = int(user["balance"])

            new_balance = old_balance + amount

            # جلوگیری از موجودی منفی
            if new_balance < 0:
                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "duplicate": False,
                    "reason": "insufficient_balance",
                    "balance": old_balance
                }

            # تغییر موجودی
            db.execute("""
                UPDATE users
                SET
                    balance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (
                new_balance,
                user_id
            ))

            # ثبت تراکنش
            cursor = db.execute("""
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    balance_before,
                    balance_after,
                    tx_type,
                    description
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (
                tx_key,
                user_id,
                amount,
                old_balance,
                new_balance,
                tx_type,
                description
            ))

            transaction_id = cursor.lastrowid

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "balance": new_balance,
                "transaction_id": transaction_id
            }

        except Exception:
            db.execute("ROLLBACK")
            raise


# -----------------------------
# کم کردن موجودی
# -----------------------------

def withdraw_balance(
    user_id,
    amount,
    tx_key,
    description="شرط بازی"
):
    amount = int(amount)

    if amount <= 0:
        return {
            "success": False,
            "reason": "invalid_amount"
        }

    return change_balance(
        user_id=user_id,
        amount=-amount,
        tx_type="bet",
        tx_key=tx_key,
        description=description
    )


# -----------------------------
# اضافه کردن موجودی
# -----------------------------

def add_balance(
    user_id,
    amount,
    tx_key,
    description="شارژ"
):
    amount = int(amount)

    if amount <= 0:
        return {
            "success": False,
            "reason": "invalid_amount"
        }

    return change_balance(
        user_id=user_id,
        amount=amount,
        tx_type="credit",
        tx_key=tx_key,
        description=description
    )


# -----------------------------
# انتقال بین دو کاربر
# -----------------------------

def transfer_balance(
    sender_id,
    receiver_id,
    amount,
    transfer_key
):
    sender_id = int(sender_id)
    receiver_id = int(receiver_id)
    amount = int(amount)

    if sender_id == receiver_id:
        return {
            "success": False,
            "reason": "self_transfer"
        }

    if amount <= 0:
        return {
            "success": False,
            "reason": "invalid_amount"
        }

    transfer_key = str(transfer_key)

    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        try:
            # اگر انتقال قبلاً انجام شده
            existing = db.execute("""
                SELECT *
                FROM transactions
                WHERE tx_key = ?
            """, (transfer_key + ":send",)).fetchone()

            if existing:
                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "balance": get_balance(sender_id)
                }

            sender = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id = ?
            """, (sender_id,)).fetchone()

            if sender is None:
                db.execute("ROLLBACK")
                return {
                    "success": False,
                    "reason": "sender_not_found"
                }

            sender_balance = int(sender["balance"])

            if sender_balance < amount:
                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "balance": sender_balance
                }

            # ساخت گیرنده اگر وجود نداشته باشد
            db.execute("""
                INSERT OR IGNORE INTO users(
                    user_id,
                    first_name,
                    username,
                    balance
                )
                VALUES(?, '', '', 0)
            """, (receiver_id,))

            receiver = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id = ?
            """, (receiver_id,)).fetchone()

            receiver_balance = int(receiver["balance"])

            new_sender_balance = sender_balance - amount
            new_receiver_balance = receiver_balance + amount

            # کم کردن از فرستنده
            db.execute("""
                UPDATE users
                SET
                    balance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (
                new_sender_balance,
                sender_id
            ))

            # اضافه کردن به گیرنده
            db.execute("""
                UPDATE users
                SET
                    balance = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
            """, (
                new_receiver_balance,
                receiver_id
            ))

            # تراکنش فرستنده
            db.execute("""
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    balance_before,
                    balance_after,
                    tx_type,
                    description
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (
                transfer_key + ":send",
                sender_id,
                -amount,
                sender_balance,
                new_sender_balance,
                "transfer_out",
                f"انتقال به {receiver_id}"
            ))

            # تراکنش گیرنده
            db.execute("""
                INSERT INTO transactions(
                    tx_key,
                    user_id,
                    amount,
                    balance_before,
                    balance_after,
                    tx_type,
                    description
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (
                transfer_key + ":receive",
                receiver_id,
                amount,
                receiver_balance,
                new_receiver_balance,
                "transfer_in",
                f"دریافت از {sender_id}"
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "sender_balance": new_sender_balance,
                "receiver_balance": new_receiver_balance
            }

        except Exception:
            db.execute("ROLLBACK")
            raise


# -----------------------------
# همه کاربران برای پنل مالک
# فقط اسم + موجودی
# -----------------------------

def get_all_users():
    with get_db() as db:
        return db.execute("""
            SELECT
                user_id,
                first_name,
                username,
                balance
            FROM users
            ORDER BY first_name COLLATE NOCASE ASC
        """).fetchall()


# -----------------------------
# تنظیمات بات
# -----------------------------

def get_setting(key, default=None):
    with get_db() as db:
        row = db.execute("""
            SELECT value
            FROM settings
            WHERE key = ?
        """, (key,)).fetchone()

        if row is None:
            return default

        return row["value"]


def set_setting(key, value):
    with get_db() as db:
        db.execute("""
            INSERT INTO settings(key, value)
            VALUES(?, ?)

            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value
        """, (
            str(key),
            str(value)
        ))


def is_bot_enabled():
    return get_setting("bot_enabled", "1") == "1"


def set_bot_enabled(enabled):
    set_setting(
        "bot_enabled",
        "1" if enabled else "0"
    )


# -----------------------------
# ثبت بازی
# -----------------------------

def create_game(
    game_id,
    chat_id,
    message_id,
    user_id,
    game_type,
    bet
):
    with get_db() as db:
        try:
            db.execute("""
                INSERT INTO games(
                    game_id,
                    chat_id,
                    message_id,
                    user_id,
                    game_type,
                    bet,
                    status
                )
                VALUES(?, ?, ?, ?, ?, ?, 'pending')
            """, (
                str(game_id),
                int(chat_id),
                int(message_id),
                int(user_id),
                str(game_type),
                int(bet)
            ))

            return True

        except sqlite3.IntegrityError:
            return False


# -----------------------------
# گرفتن بازی
# -----------------------------

def get_game(game_id):
    with get_db() as db:
        return db.execute("""
            SELECT *
            FROM games
            WHERE game_id = ?
        """, (str(game_id),)).fetchone()


# -----------------------------
# پایان بازی
# -----------------------------

def finish_game(
    game_id,
    result,
    payout=0
):
    with get_db() as db:
        db.execute("BEGIN IMMEDIATE")

        try:
            game = db.execute("""
                SELECT *
                FROM games
                WHERE game_id = ?
            """, (str(game_id),)).fetchone()

            if game is None:
                db.execute("ROLLBACK")
                return {
                    "success": False,
                    "reason": "game_not_found"
                }

            if game["status"] == "finished":
                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "payout": int(game["payout"])
                }

            db.execute("""
                UPDATE games
                SET
                    status = 'finished',
                    result = ?,
                    payout = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE game_id = ?
            """, (
                str(result),
                int(payout),
                str(game_id)
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "payout": int(payout)
            }

        except Exception:
            db.execute("ROLLBACK")
            raise
