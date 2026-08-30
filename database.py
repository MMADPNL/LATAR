import os
import sqlite3
from contextlib import contextmanager

from config import DATABASE_PATH


def ensure_directory():
    directory = os.path.dirname(DATABASE_PATH)

    if directory:
        os.makedirs(directory, exist_ok=True)


@contextmanager
def get_db():
    ensure_directory()

    db = sqlite3.connect(
        DATABASE_PATH,
        timeout=30
    )

    db.row_factory = sqlite3.Row

    try:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA busy_timeout=30000")

        yield db

        db.commit()

    except Exception:
        db.rollback()
        raise

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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
                description TEXT DEFAULT '',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                game_type TEXT NOT NULL,
                display_amount INTEGER NOT NULL DEFAULT 0,
                user_value INTEGER NOT NULL,
                bot_value INTEGER NOT NULL,
                result TEXT NOT NULL,
                reward INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        db.execute("""
            INSERT OR IGNORE INTO settings(
                key,
                value
            )
            VALUES(
                'bot_enabled',
                '1'
            )
        """)


def register_user(
    user_id,
    first_name="",
    username=""
):

    with get_db() as db:

        db.execute("""
            INSERT INTO users(
                user_id,
                first_name,
                username,
                balance
            )
            VALUES(
                ?,
                ?,
                ?,
                0
            )

            ON CONFLICT(user_id)
            DO UPDATE SET
                first_name=excluded.first_name,
                username=excluded.username,
                updated_at=CURRENT_TIMESTAMP
        """, (
            int(user_id),
            first_name or "",
            username or ""
        ))


def get_balance(user_id):

    with get_db() as db:

        row = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (
            int(user_id),
        )).fetchone()

        if row is None:
            return 0

        return int(row["balance"])


def change_balance(
    user_id,
    amount,
    tx_key,
    tx_type,
    description=""
):

    user_id = int(user_id)
    amount = int(amount)
    tx_key = str(tx_key)

    if not tx_key:
        return {
            "success": False,
            "reason": "invalid_tx_key"
        }

    with get_db() as db:

        existing = db.execute("""
            SELECT *
            FROM transactions
            WHERE tx_key=?
        """, (
            tx_key,
        )).fetchone()

        if existing:

            return {
                "success": True,
                "duplicate": True,
                "balance": int(
                    existing["balance_after"]
                )
            }

        user = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (
            user_id,
        )).fetchone()

        if user is None:

            db.execute("""
                INSERT INTO users(
                    user_id,
                    balance
                )
                VALUES(
                    ?,
                    0
                )
            """, (
                user_id,
            ))

            old_balance = 0

        else:

            old_balance = int(
                user["balance"]
            )

        new_balance = old_balance + amount

        if new_balance < 0:

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
            VALUES(
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """, (
            tx_key,
            user_id,
            amount,
            old_balance,
            new_balance,
            tx_type,
            description
        ))

        return {
            "success": True,
            "duplicate": False,
            "balance": new_balance
        }


def add_balance(
    user_id,
    amount,
    tx_key,
    description="جایزه"
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
        tx_key=tx_key,
        tx_type="credit",
        description=description
    )


def remove_balance(
    user_id,
    amount,
    tx_key,
    description="کسر توسط مالک"
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
        tx_key=tx_key,
        tx_type="debit",
        description=description
    )


def transfer_balance(
    sender_id,
    receiver_id,
    amount,
    tx_key
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

    tx_key = str(tx_key)

    with get_db() as db:

        existing = db.execute("""
            SELECT *
            FROM transactions
            WHERE tx_key=?
        """, (
            tx_key + ":send",
        )).fetchone()

        if existing:

            return {
                "success": True,
                "duplicate": True,
                "sender_balance": int(
                    existing["balance_after"]
                )
            }

        sender = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (
            sender_id,
        )).fetchone()

        if sender is None:

            return {
                "success": False,
                "reason": "sender_not_found"
            }

        sender_balance = int(
            sender["balance"]
        )

        if sender_balance < amount:

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
            VALUES(
                ?,
                '',
                '',
                0
            )
        """, (
            receiver_id,
        ))

        receiver = db.execute("""
            SELECT balance
            FROM users
            WHERE user_id=?
        """, (
            receiver_id,
        )).fetchone()

        receiver_balance = int(
            receiver["balance"]
        )

        new_sender = sender_balance - amount
        new_receiver = receiver_balance + amount

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
            VALUES(
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """, (
            tx_key + ":send",
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
            VALUES(
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """, (
            tx_key + ":receive",
            receiver_id,
            amount,
            receiver_balance,
            new_receiver,
            "transfer_in",
            f"دریافت از {sender_id}"
        ))

        return {
            "success": True,
            "duplicate": False,
            "sender_balance": new_sender,
            "receiver_balance": new_receiver
        }


def get_all_users():

    with get_db() as db:

        return db.execute("""
            SELECT
                user_id,
                first_name,
                username,
                balance
            FROM users
            ORDER BY first_name COLLATE NOCASE
        """).fetchall()


def is_bot_enabled():

    with get_db() as db:

        row = db.execute("""
            SELECT value
            FROM settings
            WHERE key='bot_enabled'
        """).fetchone()

        if row is None:
            return True

        return row["value"] == "1"


def set_bot_enabled(enabled):

    with get_db() as db:

        db.execute("""
            INSERT INTO settings(
                key,
                value
            )
            VALUES(
                'bot_enabled',
                ?
            )

            ON CONFLICT(key)
            DO UPDATE SET
                value=excluded.value
        """, (
            "1" if enabled else "0",
        ))


def save_game(
    user_id,
    chat_id,
    game_type,
    display_amount,
    user_value,
    bot_value,
    result,
    reward
):

    with get_db() as db:

        db.execute("""
            INSERT INTO games(
                user_id,
                chat_id,
                game_type,
                display_amount,
                user_value,
                bot_value,
                result,
                reward
            )
            VALUES(
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?
            )
        """, (
            int(user_id),
            int(chat_id),
            str(game_type),
            int(display_amount),
            int(user_value),
            int(bot_value),
            str(result),
            int(reward)
        ))
