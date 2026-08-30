import os
import sqlite3
from contextlib import contextmanager

from config import DATABASE_PATH


def _ensure_directory():
    directory = os.path.dirname(DATABASE_PATH)

    if directory:
        os.makedirs(directory, exist_ok=True)


@contextmanager
def get_db():
    _ensure_directory()

    db = sqlite3.connect(
        DATABASE_PATH,
        timeout=30,
        isolation_level=None
    )

    db.row_factory = sqlite3.Row

    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=30000")

        yield db

    finally:
        db.close()


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
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                game_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'finished',
                result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        db.execute("""
            INSERT OR IGNORE INTO settings(key, value)
            VALUES('bot_enabled', '1')
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_users_balance
            ON users(balance)
        """)

        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_transactions_user
            ON transactions(user_id)
        """)


# =========================================================
# USERS
# =========================================================

def register_user(user_id, first_name="", username=""):

    user_id = int(user_id)

    with get_db() as db:

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
            first_name or "",
            username or ""
        ))


def get_user(user_id):

    with get_db() as db:

        return db.execute("""
            SELECT *
            FROM users
            WHERE user_id=?
        """, (int(user_id),)).fetchone()


def get_balance(user_id):

    with get_db() as db:

        row = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (int(user_id),)).fetchone()

        if row is None:
            return 0

        return int(row["balance"])


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


# =========================================================
# BALANCE
# =========================================================

def change_balance(
    user_id,
    amount,
    tx_type,
    tx_key,
    description=""
):

    user_id = int(user_id)
    amount = int(amount)
    tx_key = str(tx_key)

    if not tx_key:
        return {
            "success": False,
            "reason": "invalid_key"
        }

    with get_db() as db:

        db.execute("BEGIN IMMEDIATE")

        try:

            old_tx = db.execute("""
                SELECT *
                FROM transactions
                WHERE tx_key=?
            """, (tx_key,)).fetchone()

            if old_tx:

                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "balance": int(
                        old_tx["balance_after"]
                    )
                }

            user = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id=?
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

                old_balance = int(
                    user["balance"]
                )

            new_balance = old_balance + amount

            if new_balance < 0:

                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "balance": old_balance
                }

            db.execute("""
                UPDATE users
                SET
                    balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_balance,
                user_id
            ))

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
                tx_key,
                user_id,
                amount,
                old_balance,
                new_balance,
                tx_type,
                description
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "balance": new_balance
            }

        except Exception:

            db.execute("ROLLBACK")
            raise


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


def withdraw_balance(
    user_id,
    amount,
    tx_key,
    description="کسر"
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
        tx_type="debit",
        tx_key=tx_key,
        description=description
    )


# =========================================================
# TRANSFER
# =========================================================

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

    send_key = f"{transfer_key}:send"
    receive_key = f"{transfer_key}:receive"

    with get_db() as db:

        db.execute("BEGIN IMMEDIATE")

        try:

            duplicate = db.execute("""
                SELECT *
                FROM transactions
                WHERE tx_key=?
            """, (send_key,)).fetchone()

            if duplicate:

                db.execute("COMMIT")

                return {
                    "success": True,
                    "duplicate": True,
                    "sender_balance": int(
                        duplicate["balance_after"]
                    )
                }

            sender = db.execute("""
                SELECT balance
                FROM users
                WHERE user_id=?
            """, (sender_id,)).fetchone()

            if sender is None:

                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "sender_not_found"
                }

            sender_balance = int(
                sender["balance"]
            )

            if sender_balance < amount:

                db.execute("ROLLBACK")

                return {
                    "success": False,
                    "reason": "insufficient_balance",
                    "balance": sender_balance
                }

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
                WHERE user_id=?
            """, (receiver_id,)).fetchone()

            receiver_balance = int(
                receiver["balance"]
            )

            new_sender = (
                sender_balance - amount
            )

            new_receiver = (
                receiver_balance + amount
            )

            db.execute("""
                UPDATE users
                SET
                    balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_sender,
                sender_id
            ))

            db.execute("""
                UPDATE users
                SET
                    balance=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE user_id=?
            """, (
                new_receiver,
                receiver_id
            ))

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
                send_key,
                sender_id,
                -amount,
                sender_balance,
                new_sender,
                "transfer_out",
                f"انتقال به {receiver_id}"
            ))

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
                receive_key,
                receiver_id,
                amount,
                receiver_balance,
                new_receiver,
                "transfer_in",
                f"دریافت از {sender_id}"
            ))

            db.execute("COMMIT")

            return {
                "success": True,
                "duplicate": False,
                "sender_balance": new_sender,
                "receiver_balance": new_receiver
            }

        except Exception:

            db.execute("ROLLBACK")
            raise


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key, default=None):

    with get_db() as db:

        row = db.execute("""
            SELECT value
            FROM settings
            WHERE key=?
        """, (str(key),)).fetchone()

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

    return (
        get_setting(
            "bot_enabled",
            "1"
        ) == "1"
    )


def set_bot_enabled(enabled):

    set_setting(
        "bot_enabled",
        "1" if enabled else "0"
    )


# =========================================================
# GAMES
# =========================================================

def create_game(
    game_id,
    chat_id,
    message_id,
    user_id,
    game_type,
    amount=0
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
                    amount
                )
                VALUES(?, ?, ?, ?, ?, ?)
            """, (
                str(game_id),
                int(chat_id),
                int(message_id),
                int(user_id),
                str(game_type),
                int(amount)
            ))

            return True

        except sqlite3.IntegrityError:

            return False


def finish_game(
    game_id,
    result
):

    with get_db() as db:

        db.execute("""
            UPDATE games
            SET
                status='finished',
                result=?
            WHERE game_id=?
        """, (
            str(result),
            str(game_id)
        ))


def get_game(game_id):

    with get_db() as db:

        return db.execute("""
            SELECT *
            FROM games
            WHERE game_id=?
        """, (str(game_id),)).fetchone()
