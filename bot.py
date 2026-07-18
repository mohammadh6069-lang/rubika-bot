# -*- coding: utf-8 -*-
"""
=========================================================
   ربات لینک‌دونی ایران - روبیکا (Rubika) - نسخه 5
=========================================================
تغییرات نسبت به نسخه قبل:
  ✅ رفع باگ جدی: ارسال خودکار خلاصه‌ی لینک‌ها دیگر از asyncio.run در
     یک ترد جدا استفاده نمی‌کند (چون باعث تداخل با اتصال شبکه‌ی حلقه‌ی
     اصلی ربات و کرش کامل آن می‌شد - خطای "Main loop error" و
     "Timeout context manager should be used inside a task").
     حالا پیام‌های دوره‌ای با درخواست HTTP ساده و همزمان (requests)
     مستقیم به API روبیکا فرستاده می‌شوند، کاملاً مستقل از ربات اصلی.

⚠️ درباره‌ی چیزی که عمداً پیاده‌سازی نشد:
  فرستادن پیام‌های تصادفی و فریبنده مثل «سلام» یا «پروفایل من بازه»
  برای ترغیب مصنوعی افراد پیاده نشد، چون این کار اسپم و فریب کاربران
  گروه است، نه معرفی صادقانه‌ی محتوا. به‌جایش، ربات فقط خلاصه‌ی واقعی
  لینک‌های تازه‌ثبت‌شده را با عنوان شفاف می‌فرستد.

⚠️ محدودیت فنی مهم درباره‌ی تایید «ادمین بودن ربات»:
  کتابخانه‌های فعلی روبیکا همیشه متد مستقیمی برای «آیا ربات ادمین
  این گروه هست؟» ندارند. کد زیر تلاش می‌کند این را به‌صورت خودکار
  بررسی کند (در تابع verify_group)، اما اگر کتابخانه‌ی نصب‌شده‌ی شما
  این متد را نداشته باشد، فقط بر اساس «عضویت ربات در گروه» ادامه
  می‌دهد و از کاربر می‌خواهد خودش مطمئن شود که ربات را ادمین کرده.

نصب پیش‌نیاز (در ترمینال Pydroid 3):
    pip install rubka --break-system-packages
    pip install requests --break-system-packages

قبل از اجرا:
  1) مقدار TOKEN را با توکن ربات خودتان جایگزین کنید.
  2) دستور /myid را به ربات بفرستید تا آیدی دقیق چت خودتان را بگیرید.
  3) همان آیدی را دقیقاً (بدون فاصله‌ی اضافه) داخل ADMIN_IDS بگذارید.
  4) ربات را کامل ببندید و دوباره اجرا کنید.
  5) با دستور /admin یا دکمه «🛠 پنل ادمین» وارد پنل ادمین شوید.

برای کاربران عادی:
  1) در چت خصوصی ربات، روی «📝 ثبت لینک» بزنند تا یک کد ۶ رقمی بگیرند.
  2) ربات را داخل گروه خودشان اضافه و «ادمین» کنند.
  3) داخل همان گروه بنویسند: /verify <کد>
  4) به چت خصوصی ربات برگردند و دوباره «📝 ثبت لینک» را بزنند.
=========================================================
"""

import sqlite3
import re
import json
import threading
import random
import string
import requests
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime, timedelta

from rubka import Robot, Message
from rubka.button import ChatKeypadBuilder

# ---------------------------------------------------------
# تنظیمات اولیه
# ---------------------------------------------------------
TOKEN = "BJHDCC0ZHIVFZMKLGRMTXPWGSULVDLTJWPMHFSWRKADKEZYGEXHPVFREHQQJSIGS"          # توکن ربات خودتان را اینجا قرار دهید
DB_PATH = "linkdoni.db"                # مسیر فایل دیتابیس (فقط وقتی از Postgres استفاده نمی‌شود)

# ---------------------------------------------------------
# دیتابیس دائمی (اختیاری ولی برای هاست‌هایی مثل Render ضروری)
# ---------------------------------------------------------
# اگر این مقدار خالی باشد، ربات از یک فایل SQLite محلی استفاده می‌کند
# (خوب برای تست روی Pydroid، ولی روی Render با هر ری‌استارت پاک می‌شود).
#
# اگر یک آدرس اتصال Postgres (مثلاً از Supabase رایگان) اینجا بگذارید،
# ربات به‌جای SQLite از همان دیتابیس دائمی استفاده می‌کند - هم روی
# Pydroid هم روی Render، یعنی دیگر هیچ دیتایی گم نمی‌شود و هر دو جا
# از یک دیتابیس مشترک می‌خوانند.
#
# فرمت معمول Supabase (از Project Settings > Database > Connection
# string > URI، ترجیحاً حالت "Connection pooling"):
#   postgresql://postgres.XXXXXXXX:YOUR-PASSWORD@aws-0-xxxx.pooler.supabase.com:6543/postgres
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip() or ""
# ---------------------------------------------------------
USE_POSTGRES = bool(DATABASE_URL)

# آیدی عددی ادمین‌ها (به رشته تبدیل کنید). با /myid آیدی خودتان را می‌گیرید.
ADMIN_IDS = {
    "b0Icszk0sBn0d39e28ea01a2f06761dc",
}

bot = Robot(token=TOKEN)

# هر چند ساعت یک‌بار خلاصه‌ی لینک‌های تازه به گروه‌های تاییدشده فرستاده شود
BROADCAST_INTERVAL_HOURS = 3


# ---------------------------------------------------------
# لیست استان‌ها و شهرهای معروف/نیمه‌معروف ایران
# ---------------------------------------------------------
PROVINCES_CITIES = {
    "آذربایجان شرقی": ["تبریز", "مراغه", "مرند", "میانه", "اهر", "بناب"],
    "آذربایجان غربی": ["ارومیه", "خوی", "بوکان", "مهاباد", "میاندوآب", "سلماس"],
    "اردبیل": ["اردبیل", "پارس‌آباد", "مشگین‌شهر", "خلخال", "گرمی"],
    "اصفهان": ["اصفهان", "کاشان", "نجف‌آباد", "خمینی‌شهر", "شاهین‌شهر", "نطنز"],
    "البرز": ["کرج", "فردیس", "نظرآباد", "هشتگرد", "اشتهارد"],
    "ایلام": ["ایلام", "دهلران", "آبدانان", "ایوان"],
    "بوشهر": ["بوشهر", "برازجان", "گناوه", "کنگان", "دیلم"],
    "تهران": ["تهران", "اسلام‌شهر", "شهریار", "ورامین", "پاکدشت", "پردیس", "دماوند"],
    "چهارمحال و بختیاری": ["شهرکرد", "بروجن", "فارسان", "لردگان"],
    "خراسان جنوبی": ["بیرجند", "قائنات", "طبس", "فردوس", "نهبندان"],
    "خراسان رضوی": ["مشهد", "نیشابور", "سبزوار", "تربت حیدریه", "قوچان", "کاشمر"],
    "خراسان شمالی": ["بجنورد", "شیروان", "اسفراین", "جاجرم"],
    "خوزستان": ["اهواز", "آبادان", "خرمشهر", "دزفول", "بندر ماهشهر", "شوشتر"],
    "زنجان": ["زنجان", "ابهر", "خدابنده", "قیدار"],
    "سمنان": ["سمنان", "شاهرود", "دامغان", "گرمسار"],
    "سیستان و بلوچستان": ["زاهدان", "زابل", "چابهار", "ایرانشهر", "خاش"],
    "فارس": ["شیراز", "مرودشت", "جهرم", "کازرون", "فسا", "لار"],
    "قزوین": ["قزوین", "الوند", "تاکستان", "آبیک"],
    "قم": ["قم"],
    "کردستان": ["سنندج", "سقز", "بانه", "مریوان", "قروه"],
    "کرمان": ["کرمان", "رفسنجان", "سیرجان", "جیرفت", "بم", "زرند"],
    "کرمانشاه": ["کرمانشاه", "اسلام‌آباد غرب", "سنقر", "پاوه", "هرسین"],
    "کهگیلویه و بویراحمد": ["یاسوج", "گچساران", "دهدشت"],
    "گلستان": ["گرگان", "گنبد کاووس", "علی‌آباد کتول", "آزادشهر"],
    "گیلان": ["رشت", "بندر انزلی", "لاهیجان", "لنگرود", "آستارا", "رودسر"],
    "لرستان": ["خرم‌آباد", "بروجرد", "دورود", "الیگودرز", "کوهدشت"],
    "مازندران": ["ساری", "بابل", "آمل", "قائم‌شهر", "بابلسر", "چالوس", "نوشهر"],
    "مرکزی": ["اراک", "ساوه", "خمین", "محلات", "دلیجان"],
    "هرمزگان": ["بندرعباس", "میناب", "قشم", "بندر لنگه", "کیش"],
    "همدان": ["همدان", "ملایر", "نهاوند", "تویسرکان", "اسدآباد"],
    "یزد": ["یزد", "میبد", "اردکان", "بافق", "تفت"],
}

MAIN_MENU_REGISTER = "📝 ثبت لینک"
MAIN_MENU_BROWSE = "📂 نمایش لینک‌ها"
MAIN_MENU_ADMIN = "🛠 پنل ادمین"
BTN_CANCEL = "❌ انصراف"
BTN_BACK = "🔙 بازگشت به منو"
BTN_SKIP_TITLE = "رد شدن (بدون نام)"

ADMIN_LIST_ALL = "📋 لیست همه لینک‌ها"
ADMIN_DELETE_BY_ID = "🗑 حذف لینک با شناسه"
ADMIN_DEDUP = "🧹 حذف لینک‌های تکراری"
ADMIN_TEST_DIGEST = "📨 ارسال آزمایشی خلاصه"
ADMIN_BACK = "🔙 بازگشت به منوی اصلی"


# ===========================================================
#                     بخش دیتابیس (SQLite یا Postgres)
# ===========================================================
class Row(dict):
    """
    یک ردیف دیتابیس که هم مثل دیکشنری (row['col']) قابل خواندن است -
    دقیقاً مثل sqlite3.Row که قبلاً استفاده می‌کردیم. این کلاس باعث
    می‌شود همه‌ی توابع پایین‌تر (که با row['...'] کار می‌کنند) چه با
    SQLite و چه با Postgres، بدون هیچ تغییری کار کنند.
    """
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as e:
            raise AttributeError(name) from e


class DBCursor:
    """پوششی روی cursor خام (sqlite3 یا pg8000) با رفتار یکسان برای هر دو."""

    def __init__(self, raw_cursor):
        self._cur = raw_cursor

    def execute(self, sql, params=()):
        if USE_POSTGRES:
            # SQLite از ? برای پارامتر استفاده می‌کند، Postgres از %s
            sql = sql.replace("?", "%s")
        self._cur.execute(sql, params)
        return self

    def fetchone(self):
        raw = self._cur.fetchone()
        return self._make_row(raw)

    def fetchall(self):
        raws = self._cur.fetchall()
        return [self._make_row(r) for r in raws]

    def _make_row(self, raw):
        if raw is None:
            return None
        cols = [d[0] for d in self._cur.description]
        return Row(zip(cols, raw))

    @property
    def rowcount(self):
        return self._cur.rowcount


class DBConn:
    """پوششی روی connection خام (sqlite3 یا pg8000) با رفتار یکسان برای هر دو."""

    def __init__(self, raw_conn):
        self._conn = raw_conn

    def execute(self, sql, params=()):
        cur = DBCursor(self._conn.cursor())
        return cur.execute(sql, params)

    def commit(self):
        self._conn.commit()

    def close(self):
        self._conn.close()


def get_conn() -> DBConn:
    if USE_POSTGRES:
        # ایمپورت تنبل: فقط وقتی واقعاً از Postgres استفاده می‌کنیم به
        # pg8000 نیاز داریم؛ کسانی که فقط روی Pydroid با SQLite کار
        # می‌کنند مجبور نیستند این کتابخانه را نصب کنند.
        import pg8000.dbapi as pg8000_dbapi
        from urllib.parse import urlparse

        parsed = urlparse(DATABASE_URL)
        raw_conn = pg8000_dbapi.connect(
            user=parsed.username,
            password=parsed.password,
            host=parsed.hostname,
            port=parsed.port or 5432,
            database=(parsed.path or "/postgres").lstrip("/"),
        )
    else:
        raw_conn = sqlite3.connect(DB_PATH)
    return DBConn(raw_conn)


def init_db():
    conn = get_conn()
    # Postgres و SQLite سینتکس متفاوتی برای ستون شناسه‌ی خودافزا دارند
    id_column = "id SERIAL PRIMARY KEY" if USE_POSTGRES else "id INTEGER PRIMARY KEY AUTOINCREMENT"

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS businesses (
            {id_column},
            user_id TEXT NOT NULL,
            province TEXT NOT NULL,
            city TEXT NOT NULL,
            title TEXT,
            link TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_states (
            chat_id TEXT PRIMARY KEY,
            step TEXT NOT NULL,
            data TEXT NOT NULL DEFAULT '{}'
        )
    """)
    # گروه‌هایی که مالک‌شان مالکیت/ادمین بودن ربات در آن‌ها را تایید کرده
    conn.execute("""
        CREATE TABLE IF NOT EXISTS verified_groups (
            group_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            group_title TEXT,
            verified_at TEXT NOT NULL
        )
    """)
    # کدهای یکبارمصرف برای پل زدن بین چت خصوصی و گروه (چون فرمت آیدی
    # فرستنده در گروه با آیدی چت خصوصی یکسان نیست)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_verify_codes (
            code TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


# ---------------------- توابع مدیریت وضعیت ----------------------
def set_state(chat_id: str, step: str, data: dict = None):
    data = data or {}
    conn = get_conn()
    conn.execute(
        "INSERT INTO user_states (chat_id, step, data) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id) DO UPDATE SET step=excluded.step, data=excluded.data",
        (chat_id, step, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def get_state(chat_id: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT step, data FROM user_states WHERE chat_id = ?", (chat_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None, {}
    return row["step"], json.loads(row["data"])


def clear_state(chat_id: str):
    conn = get_conn()
    conn.execute("DELETE FROM user_states WHERE chat_id = ?", (chat_id,))
    conn.commit()
    conn.close()


# ---------------------- توابع مربوط به تایید گروه‌ها ----------------------
def add_verified_group(group_id: str, owner_id: str, group_title: str = None):
    """گروه را به‌عنوان تاییدشده توسط owner_id ثبت/به‌روزرسانی می‌کند."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO verified_groups (group_id, owner_id, group_title, verified_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(group_id) DO UPDATE SET "
        "owner_id=excluded.owner_id, group_title=excluded.group_title, verified_at=excluded.verified_at",
        (group_id, owner_id, group_title, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    conn.close()


def owner_has_verified_group(owner_id: str) -> bool:
    """آیا این کاربر حداقل یک گروه تاییدشده دارد؟"""
    conn = get_conn()
    row = conn.execute(
        "SELECT group_id FROM verified_groups WHERE owner_id = ? LIMIT 1", (owner_id,)
    ).fetchone()
    conn.close()
    return row is not None


def get_all_verified_groups():
    conn = get_conn()
    rows = conn.execute("SELECT group_id, owner_id, group_title FROM verified_groups").fetchall()
    conn.close()
    return rows


def looks_like_group_chat(chat_id: str) -> bool:
    """
    تشخیص ساده‌ی این‌که آیا chat_id مربوط به یک گروه است یا یک چت خصوصی.
    در روبیکا معمولاً guid گروه‌ها با 'g0' و guid کاربران با 'u0' شروع می‌شود.
    اگر در نسخه‌ی کتابخانه‌ی شما این الگو فرق دارد، این تابع را با مقدار
    واقعی که از پیام‌های داخل گروه خودتان می‌بینید تنظیم کنید.
    """
    return str(chat_id).lower().startswith("g0")


# ---------------- توابع کد یکبارمصرف تایید گروه ----------------
def generate_verify_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def create_pending_code(owner_id: str) -> str:
    """
    یک کد ۶ رقمی جدید برای owner_id (آیدی چت خصوصی کاربر) می‌سازد.
    کدهای قبلی همان کاربر پاک می‌شوند تا فقط آخرین کد معتبر باشد.
    """
    conn = get_conn()
    conn.execute("DELETE FROM pending_verify_codes WHERE owner_id = ?", (owner_id,))
    code = generate_verify_code()
    conn.execute(
        "INSERT INTO pending_verify_codes (code, owner_id, created_at) VALUES (?, ?, ?)",
        (code, owner_id, datetime.now().strftime("%Y-%m-%d %H:%M")),
    )
    conn.commit()
    conn.close()
    return code


def get_pending_owner_by_code(code: str):
    conn = get_conn()
    row = conn.execute(
        "SELECT owner_id FROM pending_verify_codes WHERE code = ?", (code.strip(),)
    ).fetchone()
    conn.close()
    return row["owner_id"] if row else None


def delete_pending_code(code: str):
    conn = get_conn()
    conn.execute("DELETE FROM pending_verify_codes WHERE code = ?", (code.strip(),))
    conn.commit()
    conn.close()


# ---------------------- توابع مربوط به لینک‌ها ----------------------
def link_exists(link: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT id FROM businesses WHERE link = ?", (link.strip(),)
    ).fetchone()
    conn.close()
    return row is not None


def insert_business(user_id, province, city, title, link):
    conn = get_conn()
    conn.execute(
        """INSERT INTO businesses
           (user_id, province, city, title, link, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            user_id, province, city, title, link.strip(),
            datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    conn.commit()
    conn.close()


def get_links_by_city(province, city):
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, title, link, created_at
           FROM businesses WHERE province = ? AND city = ?
           ORDER BY created_at DESC""",
        (province, city),
    ).fetchall()
    conn.close()
    return rows


def get_all_links():
    conn = get_conn()
    rows = conn.execute(
        """SELECT id, title, province, city, link, created_at
           FROM businesses ORDER BY id DESC"""
    ).fetchall()
    conn.close()
    return rows


def get_recent_links(hours: int):
    """لینک‌هایی که در N ساعت اخیر ثبت شده‌اند (برای پیام خلاصه دوره‌ای)."""
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    rows = conn.execute(
        """SELECT title, province, city, link FROM businesses
           WHERE created_at >= ? ORDER BY created_at DESC""",
        (since,),
    ).fetchall()
    conn.close()
    return rows


def delete_link_by_id(link_id: int) -> bool:
    conn = get_conn()
    cur = conn.execute("DELETE FROM businesses WHERE id = ?", (link_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def remove_duplicate_links() -> int:
    """
    لینک‌های تکراری (با آدرس یکسان پس از نرمال‌سازی) را حذف می‌کند
    و فقط قدیمی‌ترین رکورد هر لینک را نگه می‌دارد.
    در حالت عادی چون ستون link با UNIQUE تعریف شده تکراری ایجاد
    نمی‌شود، اما این تابع برای اطمینان و پاک‌سازی دستی ادمین است.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, link FROM businesses ORDER BY id ASC"
    ).fetchall()

    seen = {}
    to_delete = []
    for row in rows:
        norm = normalize_link(row["link"]).rstrip("/").lower()
        if norm in seen:
            to_delete.append(row["id"])
        else:
            seen[norm] = row["id"]

    for link_id in to_delete:
        conn.execute("DELETE FROM businesses WHERE id = ?", (link_id,))
    conn.commit()
    conn.close()
    return len(to_delete)


def is_valid_link(text: str) -> bool:
    pattern = r"^(https?://)?([\w\-]+\.)+[\w\-]+(/[\w\-./?%&=]*)?$"
    return bool(re.match(pattern, text.strip()))


def normalize_link(text: str) -> str:
    text = text.strip()
    if not text.startswith("http://") and not text.startswith("https://"):
        text = "https://" + text
    return text


def normalize_id(value) -> str:
    """
    آیدی را از فاصله‌ها و کاراکترهای نامرئی (مثل کاراکترهای جهت متن که
    گاهی هنگام کپی/پیست از داخل چت وارد می‌شوند) پاک می‌کند تا مقایسه
    آیدی‌ها همیشه درست انجام شود.
    """
    text = str(value)
    # حذف هر کاراکتری که حرف/عدد/زیرخط نیست (فاصله، کاراکترهای کنترلی و ...)
    return re.sub(r"[^\w]", "", text)


ADMIN_IDS_NORMALIZED = {normalize_id(a) for a in ADMIN_IDS}


def is_admin(chat_id: str) -> bool:
    return normalize_id(chat_id) in ADMIN_IDS_NORMALIZED


# ===========================================================
#                  توابع کمکی برای ساخت کیبورد
# ===========================================================
def chunk_list(items, per_row=2):
    return [items[i:i + per_row] for i in range(0, len(items), per_row)]


def build_keypad(buttons_2d, extra_row=None):
    builder = ChatKeypadBuilder()
    for row in buttons_2d:
        btns = [builder.button(id=text, text=text) for text in row]
        builder.row(*btns)
    if extra_row:
        btns = [builder.button(id=text, text=text) for text in extra_row]
        builder.row(*btns)
    return builder.build()


def main_menu_keypad(chat_id: str):
    rows = [[MAIN_MENU_REGISTER], [MAIN_MENU_BROWSE]]
    if is_admin(chat_id):
        rows.append([MAIN_MENU_ADMIN])
    return build_keypad(rows)


def admin_menu_keypad():
    return build_keypad(
        [[ADMIN_LIST_ALL], [ADMIN_DELETE_BY_ID], [ADMIN_DEDUP], [ADMIN_TEST_DIGEST]],
        extra_row=[ADMIN_BACK],
    )


def provinces_keypad():
    provinces = list(PROVINCES_CITIES.keys())
    return build_keypad(chunk_list(provinces, 2), extra_row=[BTN_CANCEL])


def cities_keypad(province):
    cities = PROVINCES_CITIES.get(province, [])
    return build_keypad(chunk_list(cities, 2), extra_row=[BTN_CANCEL])


# ===========================================================
#     تابع کمکی مقاوم برای ارسال پیام (سازگار با نسخه‌های مختلف rubka)
# ===========================================================
async def safe_reply(message: Message, text: str, keypad=None):
    """
    چون نام دقیق پارامتر کیبورد ممکن است بین نسخه‌های مختلف کتابخانه
    rubka فرق کند، این تابع چند حالت را امتحان می‌کند تا خطا نگیریم.

    نکته مهم: طبق API روبیکا، chat_keypad/inline_keypad فقط در چت
    خصوصی با کاربر مجاز است، نه در گروه‌ها. دو لایه محافظت داریم:
      1) حدس اولیه بر اساس پیشوند chat_id (looks_like_group_chat)
      2) حتی اگر آن حدس اشتباه باشد، اگر خودِ سرور روبیکا خطای
         "فقط در چت خصوصی مجاز است" برگرداند، همینجا آن را می‌گیریم
         و بدون کیبورد دوباره تلاش می‌کنیم؛ در نتیجه ربات هرگز به
         خاطر این مورد کرش نمی‌کند.
    """
    chat_id = getattr(message, "chat_id", None)
    if keypad is not None and chat_id is not None and looks_like_group_chat(chat_id):
        keypad = None

    if keypad is None:
        return await message.reply(text)

    def _is_keypad_not_allowed_error(exc: Exception) -> bool:
        msg = str(exc)
        return ("chat_keypad" in msg or "inline_keypad" in msg) and (
            "only valid" in msg or "must also fill" in msg or "INVALID_INPUT" in msg
        )

    try:
        # حالت رایج در بیشتر کتابخانه‌های Bot API روبیکا
        return await message.reply(text, chat_keypad=keypad, chat_keypad_type="New")
    except TypeError:
        pass
    except Exception as e:
        if _is_keypad_not_allowed_error(e):
            return await message.reply(text)
        raise

    try:
        return await message.reply(text, chat_keypad=keypad)
    except TypeError:
        pass
    except Exception as e:
        if _is_keypad_not_allowed_error(e):
            return await message.reply(text)
        raise

    try:
        return await message.reply(text, keypad=keypad)
    except TypeError:
        pass
    except Exception as e:
        if _is_keypad_not_allowed_error(e):
            return await message.reply(text)
        raise

    # اگر هیچ‌کدام کار نکرد، حداقل خود پیام متنی ارسال شود
    return await message.reply(text)


async def safe_send(chat_id: str, text: str):
    """
    ارسال مستقیم پیام به یک chat_id مشخص، بدون داشتن یک پیام ورودی.
    (این تابع فقط برای فراخوانی از داخل هندلرهای async خودِ ربات است؛
    برای پیام‌های خودکار/دوره‌ای از ترد جدا، از send_message_sync
    استفاده می‌شود، نه از این تابع - چون این یکی به همان event loop
    ربات وابسته است.)
    """
    return await bot.send_message(chat_id, text)


# ===========================================================
#         ارسال خودکار خلاصه‌ی لینک‌های تازه به گروه‌های تاییدشده
# ===========================================================
# آدرس رسمی API روبیکا برای فراخوانی مستقیم و همزمان (sync)، کاملاً
# مستقل از event loop داخلی کتابخانه‌ی rubka. این را عمداً با
# کتابخانه‌ی ساده و همزمان requests پیاده کرده‌ایم، نه با خود آبجکت
# bot، چون فراخوانی bot از یک ترد/حلقه‌ی جداگانه باعث تداخل با اتصال
# شبکه‌ی حلقه‌ی اصلی ربات و کرش کل ربات می‌شد (Timeout context manager
# should be used inside a task).
RUBIKA_API_BASE = f"https://botapi.rubika.ir/v3/{TOKEN}"


def send_message_sync(chat_id: str, text: str) -> bool:
    """
    ارسال همزمان (sync) و کاملاً مستقل از حلقه‌ی رویداد ربات اصلی.
    امن است که از یک ترد جداگانه صدا زده شود.
    """
    url = f"{RUBIKA_API_BASE}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=15)
        try:
            data = resp.json()
        except ValueError:
            data = {}
        ok = resp.status_code == 200 and (not data or data.get("status") in (None, "OK", "ok"))
        if not ok:
            print(f"⚠️ ارسال به {chat_id} با وضعیت غیرمنتظره: {resp.status_code} {resp.text[:200]}")
        return ok
    except Exception as e:
        print(f"⚠️ خطا در ارسال مستقیم به {chat_id}: {e}")
        return False


def send_digest_to_groups(force: bool = False):
    """
    برای هر گروه تاییدشده، یک پیام می‌فرستد:
      - اگر لینک تازه‌ای در بازه‌ی اخیر ثبت شده باشد، خلاصه‌ی همان
        لینک‌های تازه را می‌فرستد.
      - اگر هیچ لینک تازه‌ای نبود، به‌جای سکوت، یک پیام صادقانه می‌فرستد
        که از اعضای گروه دعوت می‌کند خودشان لینکشان را در ربات ثبت کنند
        (نه یک پیام فریبنده - کاملاً شفاف می‌گوید موضوع چیست).
    این تابع کاملاً sync است و به عمد از asyncio استفاده نمی‌کند.

    force=True: برای تست دستی توسط ادمین - حتی اگر لینک «تازه» (در بازه‌ی
    BROADCAST_INTERVAL_HOURS) نباشد، آخرین لینک‌های ثبت‌شده را می‌فرستد
    تا بدون نیاز به صبر کردن بشود مطمئن شد ارسال کار می‌کند.

    خروجی: دیکشنری با تعداد گروه‌های تاییدشده، تعداد ارسال موفق و ناموفق،
    تعداد لینک‌هایی که در پیام گنجانده شد، و این‌که آیا پیام از نوع
    «دعوت به ثبت» بوده یا خلاصه‌ی واقعی (برای گزارش به ادمین).
    """
    groups = get_all_verified_groups()
    result = {"total_groups": len(groups), "sent": 0, "failed": 0, "links_count": 0, "type": None}

    if not groups:
        return result

    recent = get_recent_links(BROADCAST_INTERVAL_HOURS)
    if not recent and force:
        # حالت تست: اگر لینک تازه‌ای نبود، آخرین لینک‌های موجود را بفرست
        recent = get_all_links()[:10]

    if recent:
        result["type"] = "digest"
        result["links_count"] = len(recent[:10])
        text = "🔔 لینک‌های تازه ثبت‌شده در لینک‌دونی:\n\n"
        for r in recent[:10]:
            title = r["title"] or "(بدون نام)"
            text += f"🔤 {title}\n📍 {r['province']} - {r['city']}\n🔗 {r['link']}\n\n"
        text += "برای دیدن همه‌ی لینک‌ها یا ثبت لینک خودتان، به ربات لینک‌دونی مراجعه کنید."
    else:
        # هیچ لینک تازه‌ای نیست - به‌جای سکوت، دعوت صادقانه به ثبت لینک
        result["type"] = "invite"
        text = (
            "📭 در حال حاضر لینک تازه‌ای برای نمایش نیست.\n\n"
            "اگر هنوز لینک خودتان را ثبت نکرده‌اید، همین حالا به چت خصوصی "
            "ربات لینک‌دونی بروید و اولین نفری باشید که لینکش دیده می‌شود!"
        )

    for g in groups:
        ok = send_message_sync(g["group_id"], text)
        if ok:
            result["sent"] += 1
        else:
            result["failed"] += 1

    return result


def broadcast_loop():
    """
    این تابع در یک ترد جداگانه (مستقل از حلقه‌ی اصلی ربات) اجرا می‌شود
    و هر BROADCAST_INTERVAL_HOURS ساعت یک‌بار خلاصه‌ی لینک‌های تازه را
    می‌فرستد. چون send_digest_to_groups کاملاً sync است و از requests
    استفاده می‌کند (نه از آبجکت bot یا asyncio)، هیچ تداخلی با حلقه‌ی
    اصلی ربات ندارد.
    """
    while True:
        threading.Event().wait(BROADCAST_INTERVAL_HOURS * 3600)
        try:
            send_digest_to_groups()
        except Exception as e:
            print(f"⚠️ خطا در چرخه‌ی ارسال خودکار خلاصه: {e}")


# ===========================================================
#                       هندلرهای ربات
# ===========================================================
@bot.on_message(commands=["start"])
async def start(bot: Robot, message: Message):
    clear_state(message.chat_id)
    await safe_reply(
        message,
        "🌐 به ربات لینک‌دونی خوش آمدید!\n\n"
        "📝 با «ثبت لینک» می‌توانید لینک خودتان را "
        "به تفکیک استان و شهر ثبت کنید.\n"
        "📂 با «نمایش لینک‌ها» می‌توانید لینک‌های ثبت‌شده در استان و "
        "شهر مورد نظرتان را ببینید.",
        keypad=main_menu_keypad(message.chat_id),
    )


@bot.on_message(commands=["myid"])
async def my_id(bot: Robot, message: Message):
    """برای پیدا کردن آیدی خودتان جهت افزودن به ADMIN_IDS."""
    await safe_reply(message, f"آیدی چت شما:\n{message.chat_id}")


@bot.on_message(commands=["admin"])
async def admin_entry(bot: Robot, message: Message):
    """
    راه ورود مستقیم و مطمئن به پنل ادمین، مستقل از دکمه‌های منو.
    اگر آیدی شما در ADMIN_IDS باشد، همیشه کار می‌کند حتی اگر دکمه
    «پنل ادمین» به هر دلیلی در کیبورد نمایش داده نشده باشد.
    """
    chat_id = message.chat_id
    if not is_admin(chat_id):
        await safe_reply(
            message,
            f"⛔ شما دسترسی ادمین ندارید.\nآیدی چت شما: {chat_id}\n"
            "اگر فکر می‌کنید باید دسترسی داشته باشید، همین آیدی بالا را "
            "دقیقاً داخل ADMIN_IDS در کد قرار دهید و ربات را دوباره اجرا کنید.",
        )
        return
    set_state(chat_id, "admin_menu", {})
    await safe_reply(message, "به پنل ادمین خوش آمدید 🛠", keypad=admin_menu_keypad())


@bot.on_message(commands=["verify"])
async def verify_group(bot: Robot, message: Message):
    """
    این دستور باید داخل خودِ گروه فرستاده شود (نه در چت خصوصی ربات)،
    به همراه کدی که از چت خصوصی ربات گرفته‌اید:
        /verify 123456

    چرا با کد؟ چون آیدی فرستنده‌ی پیام داخل گروه با آیدی چت خصوصی
    کاربر با ربات لزوماً یک فرمت نیستند، پس نمی‌شود مستقیم مقایسه‌شان
    کرد. کد یکبارمصرف، چت خصوصی و گروه را به‌طور مطمئن به هم وصل می‌کند.
    """
    chat_id = message.chat_id
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else None

    if not looks_like_group_chat(chat_id):
        await safe_reply(
            message,
            "این دستور باید داخل گروه خودتان فرستاده شود، نه در چت خصوصی ربات.",
        )
        return

    if not code:
        await safe_reply(
            message,
            "برای تایید این گروه، ابتدا در چت خصوصی ربات از منو «📝 ثبت لینک» "
            "را بزنید تا یک کد ۶ رقمی بگیرید، سپس همینجا داخل گروه بنویسید:\n"
            "/verify کد_دریافتی",
        )
        return

    owner_id = get_pending_owner_by_code(code)
    if not owner_id:
        await safe_reply(
            message,
            "⚠️ این کد معتبر نیست یا منقضی شده. لطفاً دوباره از چت خصوصی ربات "
            "«📝 ثبت لینک» را بزنید تا یک کد جدید بگیرید.",
        )
        return

    group_title = getattr(message, "chat_title", None)

    # تلاش اختیاری برای بررسی خودکار ادمین بودن ربات در گروه.
    # اگر کتابخانه‌ی نصب‌شده‌ی شما این متدها را نداشته باشد (بسته به نسخه
    # ممکن است نداشته باشد)، این بخش بی‌صدا رد می‌شود و کار متوقف نمی‌شود.
    try:
        me = await bot.get_me()
        bot_guid = me.get("bot_guid") or me.get("id") or me.get("guid")
        admins = await bot.get_chat_admins(chat_id)
        admin_ids = {a.get("user_id") or a.get("id") for a in admins}
        if bot_guid and bot_guid not in admin_ids:
            await safe_reply(
                message,
                "⚠️ ربات هنوز در این گروه ادمین نشده است. لطفاً ابتدا از "
                "تنظیمات گروه، ربات را به عنوان ادمین اضافه کنید و دوباره "
                "همین دستور را با همان کد بفرستید.",
            )
            return
    except Exception:
        # کتابخانه این قابلیت را ندارد یا خطا داد؛ فقط بر اساس عضویت
        # ربات در گروه ادامه می‌دهیم.
        pass

    add_verified_group(group_id=chat_id, owner_id=owner_id, group_title=group_title)
    delete_pending_code(code)

    await safe_reply(
        message,
        "✅ این گروه ثبت و تایید شد.\n\n"
        "⚠️ لطفاً خودتان هم مطمئن شوید ربات را از تنظیمات گروه به عنوان "
        "ادمین انتخاب کرده‌اید؛ در غیر این صورت بعداً نمی‌تواند در گروه "
        "پیام بفرستد.\n\n"
        "حالا به چت خصوصی ربات برگردید و دوباره «📝 ثبت لینک» را بزنید.",
    )


@bot.on_message()
async def handle_message(bot: Robot, message: Message):
    chat_id = message.chat_id
    text = (message.text or "").strip()

    if not text:
        return

    # پیام‌های داخل گروه‌ها اینجا پردازش نمی‌شوند (چون کل منطق منو/ثبت
    # لینک برای چت خصوصی طراحی شده و کیبورد هم در گروه مجاز نیست).
    # دستور /verify هندلر جداگانه‌ی خودش را دارد و از این‌جا رد نمی‌شود.
    if looks_like_group_chat(chat_id):
        return

    # ---------------- دستورهای عمومی هر زمان قابل استفاده ----------------
    if text == BTN_CANCEL or text == BTN_BACK or text == ADMIN_BACK:
        clear_state(chat_id)
        await safe_reply(message, "به منوی اصلی بازگشتید.", keypad=main_menu_keypad(chat_id))
        return

    step, data = get_state(chat_id)

    # ---------------- حالت اولیه: کاربر در منوی اصلی است ----------------
    if step is None:
        if text == MAIN_MENU_REGISTER:
            if not owner_has_verified_group(chat_id):
                code = create_pending_code(chat_id)
                await safe_reply(
                    message,
                    "برای ثبت لینک، ابتدا باید مالکیت یک گروه را تایید کنید:\n\n"
                    "1️⃣ ربات را داخل گروه خودتان اضافه کنید.\n"
                    "2️⃣ از تنظیمات گروه، ربات را «ادمین» کنید.\n"
                    "3️⃣ داخل همان گروه دقیقاً همین را بفرستید:\n"
                    f"/verify {code}\n\n"
                    "بعد از تایید، به همین چت برگردید و دوباره «📝 ثبت لینک» را بزنید.\n"
                    "(این کد فقط چند دقیقه معتبر است؛ اگر منقضی شد، دوباره روی "
                    "«📝 ثبت لینک» بزنید تا کد تازه بگیرید.)",
                    keypad=main_menu_keypad(chat_id),
                )
                return
            set_state(chat_id, "register_province", {})
            await safe_reply(message, "استان خود را انتخاب کنید:", keypad=provinces_keypad())
        elif text == MAIN_MENU_BROWSE:
            set_state(chat_id, "browse_province", {})
            await safe_reply(message, "لطفاً استان مورد نظر را انتخاب کنید:", keypad=provinces_keypad())
        elif text == MAIN_MENU_ADMIN and is_admin(chat_id):
            set_state(chat_id, "admin_menu", {})
            await safe_reply(message, "به پنل ادمین خوش آمدید 🛠", keypad=admin_menu_keypad())
        else:
            await safe_reply(
                message,
                "لطفاً یکی از گزینه‌های منو را انتخاب کنید 👇",
                keypad=main_menu_keypad(chat_id),
            )
        return

    # =====================================================
    #                    پنل ادمین
    # =====================================================
    if step == "admin_menu":
        if not is_admin(chat_id):
            clear_state(chat_id)
            await safe_reply(message, "شما دسترسی ادمین ندارید.", keypad=main_menu_keypad(chat_id))
            return

        if text == ADMIN_LIST_ALL:
            rows = get_all_links()
            if not rows:
                await safe_reply(message, "هیچ لینکی در دیتابیس ثبت نشده است.", keypad=admin_menu_keypad())
                return
            out = "📋 لیست همه لینک‌های ثبت‌شده:\n\n"
            for r in rows:
                title = r["title"] or "(بدون نام)"
                out += (
                    f"🔹 شناسه: {r['id']}\n"
                    f"   نام: {title}\n"
                    f"   محل: {r['province']} - {r['city']}\n"
                    f"   لینک: {r['link']}\n"
                    f"   تاریخ: {r['created_at']}\n\n"
                )
            MAX_LEN = 3500
            while len(out) > 0:
                chunk = out[:MAX_LEN]
                out = out[MAX_LEN:]
                await safe_reply(message, chunk)
            await safe_reply(message, "برای حذف یک لینک، از گزینه «حذف لینک با شناسه» استفاده کنید.", keypad=admin_menu_keypad())
            return

        if text == ADMIN_DELETE_BY_ID:
            set_state(chat_id, "admin_delete_id", {})
            await safe_reply(message, "شناسه (ID) لینکی که می‌خواهید حذف شود را وارد کنید:")
            return

        if text == ADMIN_DEDUP:
            removed = remove_duplicate_links()
            await safe_reply(message, f"🧹 عملیات پاک‌سازی انجام شد. تعداد لینک تکراری حذف‌شده: {removed}", keypad=admin_menu_keypad())
            return

        if text == ADMIN_TEST_DIGEST:
            await safe_reply(message, "⏳ در حال ارسال آزمایشی به گروه‌های تاییدشده...")
            result = send_digest_to_groups(force=True)
            if result["total_groups"] == 0:
                await safe_reply(
                    message,
                    "⚠️ هیچ گروه تاییدشده‌ای وجود ندارد. ابتدا باید حداقل یک گروه با /verify تایید شود.",
                    keypad=admin_menu_keypad(),
                )
                return

            type_label = {
                "digest": "🔔 خلاصه‌ی لینک‌های موجود",
                "invite": "📭 پیام دعوت به ثبت لینک (چون هیچ لینکی در دیتابیس نبود)",
            }.get(result["type"], "نامشخص")

            await safe_reply(
                message,
                "📨 نتیجه‌ی ارسال آزمایشی:\n\n"
                f"نوع پیام فرستاده‌شده: {type_label}\n"
                f"👥 تعداد گروه‌های تاییدشده: {result['total_groups']}\n"
                f"✅ ارسال موفق: {result['sent']}\n"
                f"❌ ارسال ناموفق: {result['failed']}\n"
                + (f"🔗 تعداد لینک‌های گنجانده‌شده: {result['links_count']}\n" if result["type"] == "digest" else "")
                + "\nاگر «ارسال ناموفق» بیشتر از صفر بود، برای جزئیات خطا به لاگ "
                "ترمینال Pydroid نگاه کنید.",
                keypad=admin_menu_keypad(),
            )
            return

        await safe_reply(message, "لطفاً یکی از گزینه‌های پنل ادمین را انتخاب کنید:", keypad=admin_menu_keypad())
        return

    if step == "admin_delete_id":
        if not is_admin(chat_id):
            clear_state(chat_id)
            await safe_reply(message, "شما دسترسی ادمین ندارید.", keypad=main_menu_keypad(chat_id))
            return
        if not text.isdigit():
            await safe_reply(message, "لطفاً فقط عدد شناسه را وارد کنید:")
            return
        deleted = delete_link_by_id(int(text))
        set_state(chat_id, "admin_menu", {})
        if deleted:
            await safe_reply(message, f"✅ لینک با شناسه {text} حذف شد.", keypad=admin_menu_keypad())
        else:
            await safe_reply(message, f"⚠️ لینکی با شناسه {text} پیدا نشد.", keypad=admin_menu_keypad())
        return

    # =====================================================
    #                       مسیر «ثبت لینک»
    # =====================================================
    if step == "register_province":
        if text not in PROVINCES_CITIES:
            await safe_reply(message, "لطفاً یکی از استان‌های نمایش داده شده را انتخاب کنید.", keypad=provinces_keypad())
            return
        data["province"] = text
        set_state(chat_id, "register_city", data)
        await safe_reply(message, f"شهر مورد نظر در استان «{text}» را انتخاب کنید:", keypad=cities_keypad(text))
        return

    if step == "register_city":
        province = data.get("province")
        if text not in PROVINCES_CITIES.get(province, []):
            await safe_reply(message, "لطفاً یکی از شهرهای نمایش داده شده را انتخاب کنید.", keypad=cities_keypad(province))
            return
        data["city"] = text
        set_state(chat_id, "register_title", data)
        await safe_reply(
            message,
            "✍️ اگر می‌خواهید، یک نام کوتاه برای لینک خود بنویسید (مثلاً: فروشگاه آرمان)، "
            "یا اگر لازم نیست دکمه زیر را بزنید:",
            keypad=build_keypad([[BTN_SKIP_TITLE]], extra_row=[BTN_CANCEL]),
        )
        return

    if step == "register_title":
        title = "" if text == BTN_SKIP_TITLE else text[:60]
        data["title"] = title
        set_state(chat_id, "register_link", data)
        await safe_reply(message, "🔗 لینک خود را وارد کنید (اینستاگرام، سایت، کانال یا گروه روبیکا و غیره):")
        return

    if step == "register_link":
        if not is_valid_link(text):
            await safe_reply(message, "لینک وارد شده معتبر نیست. لطفاً یک لینک صحیح وارد کنید (مثلاً: instagram.com/mypage):")
            return
        normalized = normalize_link(text)
        if link_exists(normalized):
            await safe_reply(
                message,
                "⚠️ این لینک قبلاً در دیتابیس ثبت شده است و امکان ثبت دوباره‌ی آن وجود ندارد.\n"
                "لطفاً لینک دیگری وارد کنید یا با «❌ انصراف» عملیات را لغو کنید.",
            )
            return

        try:
            insert_business(
                user_id=chat_id,
                province=data["province"],
                city=data["city"],
                title=data.get("title") or None,
                link=normalized,
            )
            clear_state(chat_id)
            await safe_reply(
                message,
                "✅ لینک شما با موفقیت ثبت شد!\n\n"
                f"📍 محل: {data['province']} - {data['city']}\n"
                f"🔤 نام: {data.get('title') or '(بدون نام)'}\n"
                f"🔗 لینک: {normalized}",
                keypad=main_menu_keypad(chat_id),
            )
        except Exception as e:
            # هر دو درایور (sqlite3 و pg8000) وقتی UNIQUE نقض شود پیامی
            # حاوی "unique" برمی‌گردانند؛ به‌جای وابستگی به کلاس دقیق
            # خطا (که بین SQLite و Postgres فرق دارد)، از روی متن خطا
            # تشخیص می‌دهیم.
            if "unique" in str(e).lower():
                clear_state(chat_id)
                await safe_reply(
                    message,
                    "⚠️ این لینک هم‌اکنون توسط شخص دیگری ثبت شد و امکان ثبت دوباره وجود ندارد.",
                    keypad=main_menu_keypad(chat_id),
                )
            else:
                raise
        return

    # =====================================================
    #                   مسیر «نمایش لینک‌ها»
    # =====================================================
    if step == "browse_province":
        if text not in PROVINCES_CITIES:
            await safe_reply(message, "لطفاً یکی از استان‌های نمایش داده شده را انتخاب کنید.", keypad=provinces_keypad())
            return
        data["province"] = text
        set_state(chat_id, "browse_city", data)
        await safe_reply(message, f"شهر مورد نظر در استان «{text}» را انتخاب کنید:", keypad=cities_keypad(text))
        return

    if step == "browse_city":
        province = data.get("province")
        if text not in PROVINCES_CITIES.get(province, []):
            await safe_reply(message, "لطفاً یکی از شهرهای نمایش داده شده را انتخاب کنید.", keypad=cities_keypad(province))
            return
        city = text
        rows = get_links_by_city(province, city)
        clear_state(chat_id)

        if not rows:
            await safe_reply(
                message,
                f"در حال حاضر هیچ لینکی برای «{city}، {province}» ثبت نشده است.",
                keypad=main_menu_keypad(chat_id),
            )
            return

        result_text = f"📂 لینک‌های ثبت‌شده در {city} ({province}):\n\n"
        for i, r in enumerate(rows, start=1):
            title = r["title"] or "(بدون نام)"
            result_text += (
                f"{i}. 🔤 {title}\n"
                f"   🔗 {r['link']}\n\n"
            )

        MAX_LEN = 3500
        while len(result_text) > 0:
            chunk = result_text[:MAX_LEN]
            result_text = result_text[MAX_LEN:]
            await safe_reply(message, chunk)

        await safe_reply(message, "برای بازگشت به منوی اصلی از دکمه زیر استفاده کنید:", keypad=main_menu_keypad(chat_id))
        return

    # اگر به هر دلیلی مرحله ناشناخته بود
    clear_state(chat_id)
    await safe_reply(message, "متوجه نشدم. به منوی اصلی بازگشتید.", keypad=main_menu_keypad(chat_id))


# ===========================================================
#      وب‌سرور سبک برای Health Check (مخصوص هاست‌هایی مثل Render)
# ===========================================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    """
    فقط به درخواست‌های GET با یک صفحه‌ی متنی ساده جواب می‌دهد تا
    سرویس‌هایی مثل Render (که برای Web Service انتظار دارند برنامه
    روی یک پورت HTTP گوش بدهد) سرویس را «سالم» تشخیص بدهند.
    این وب‌سرور هیچ ربطی به منطق ربات ندارد و فقط برای زنده نگه
    داشتن سرویس روی هاست است.
    """

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("ربات لینک‌دونی فعال است ✅".encode("utf-8"))

    def log_message(self, format, *args):
        # جلوگیری از شلوغ شدن لاگ ترمینال با هر درخواست health check
        pass


def start_health_server():
    """
    فقط وقتی اجرا می‌شود که متغیر محیطی PORT تنظیم شده باشد (یعنی روی
    هاستی مثل Render اجرا می‌شویم). روی Pydroid این متغیر معمولاً
    وجود ندارد، پس این وب‌سرور آنجا اصلاً بالا نمی‌آید و مزاحم نیست.
    """
    port_str = os.environ.get("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)
    except ValueError:
        print(f"⚠️ مقدار PORT نامعتبر است: {port_str}")
        return

    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"🌐 وب‌سرور health check روی پورت {port} در حال اجراست...")
    server.serve_forever()


# ===========================================================
#                          اجرای ربات
# ===========================================================
if __name__ == "__main__":
    init_db()
    # ترد پخش خودکار خلاصه‌ی لینک‌های تازه به گروه‌های تاییدشده
    threading.Thread(target=broadcast_loop, daemon=True).start()
    # ترد وب‌سرور health check (فقط وقتی روی هاستی مثل Render اجرا می‌شویم)
    threading.Thread(target=start_health_server, daemon=True).start()
    print("ربات لینک‌دونی در حال اجراست... (برای توقف Ctrl+C را بزنید)")
    bot.run()