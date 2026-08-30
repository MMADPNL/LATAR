import os

# توکن ربات را در Environment Variables با نام BOT_TOKEN قرار بده
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# آیدی عددی مالک ربات را در Environment Variables با نام OWNER_ID قرار بده
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

# کانال/گروه اجباری
FORCE_CHAT = "@LATAR_tek"

# ارز داخلی بات
CURRENCY = "DOGS"

# ضریب‌ها
LOTTERY_ODD_EVEN = 1.8
LOTTERY_RED_WHITE = 1.8
LOTTERY_GOAL_OUT = 1.5
BOT_GAME = 2.0

# حداکثر تعداد راند بازی با ربات
MAX_ROUNDS = 4

# مسیر دیتابیس دائمی
DATABASE_PATH = "data/database.db"
