"""
ربات روبیکا - توزیع امن محتوا
=================================
پیش‌نیازها (در Pydroid 3):
  1) از منوی Pip، پکیج‌های زیر رو نصب کن:
        pip install rubka
        pip install Pillow
  2) با @BotFather در روبیکا یک بات بساز و توکن رو کپی کن.
  3) بات رو اجرا کن، توی PV بات بزن /myid و آیدی خودت رو در ADMIN_IDS بذار.
  4) بات باید ادمین کانال CHANNEL_GUID باشه تا بتونه عضویت رو چک کنه.

نکته‌ی مهم درباره‌ی async:
  این نسخه از کتابخانه‌ی Rubka کاملاً async هست، یعنی همه‌ی هندلرها باید
  با "async def" تعریف بشن و هر متدی که به سرور روبیکا وصل می‌شه (send_message،
  reply، check_join، delete_message و ...) باید با "await" صدا زده بشه.
  اگه یه هندلر رو async ننویسی، همون خطای:
      TypeError: object NoneType can't be used in 'await' expression
  رو می‌گیری.

نحوه‌ی کار:
  - هر آیتم (فایل/متن/عکس و ...) یک "کد" داره.
  - کاربر باید داخل بات دستور  /start <کد>  رو بفرسته (لینک روبیکا لزوماً
    این دستور رو خودکار نمی‌فرسته، پس اگه لینک کار نکرد از کاربر بخواه
    خودش /start <کد> رو تایپ کنه).
  - محتوای ارسالی بعد از DELETE_AFTER_SECONDS ثانیه خودکار پاک می‌شه
    (با asyncio.create_task روی همون event loop بات، بدون نیاز به Thread).
  - مدیریت محتوا فقط از طریق ادمین‌های تعریف‌شده در ADMIN_IDS انجام می‌شه.

دستورات ادمین:
  /additem <کد> <نوع>     نوع یکی از: text, image, file, music, voice, gif
                          بعدش محتوا (متن یا فایل) رو در پیام بعدی بفرست.
  /delitem <کد>           حذف یک آیتم
  /listitems              لیست همه آیتم‌ها
  /myid                   نمایش آیدی عددی خودت (برای اضافه کردن به ADMIN_IDS)
  /chatid                 نمایش chat_id/GUID همون چت (برای گرفتن GUID کانال)
"""

import json
import os
import asyncio
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from rubka import Robot
from rubka.context import Message
from rubka.button import InlineBuilder

# ---------------- تنظیمات ----------------
TOKEN = "BJDJCJ0SKJTSQEOIKLHSTSJCRCPXDNOFQMHOEXWSIWCRWGHASNBIFXRPOGAPSSPD"
ADMIN_IDS = {"u0IHmfJ0b883007320baa7c0e61fd7b0"}
CHANNEL_GUID = ""
CHANNEL_LINK = ""
DELETE_AFTER_SECONDS = 10
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.json")

bot = Robot(TOKEN)


# ---------------- وب‌سرور مجازی برای پلن رایگان Render (Web Service) ----------------
# Render فقط به سرویس‌هایی که روی یه پورت HTTP گوش می‌دن پلن رایگان می‌ده.
# این وب‌سرور فقط جواب هلث‌چک رو می‌ده؛ کار اصلی بات همچنان polling روبیکاست.
class _HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("ربات روبیکا در حال اجراست ✅".encode("utf-8"))

    def log_message(self, format, *args):
        pass  # لاگ‌های اضافه‌ی HTTP رو خاموش می‌کنیم


def _start_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), _HealthCheckHandler)
    print(f"وب‌سرور هلث‌چک روی پورت {port} بالا اومد.")
    server.serve_forever()


threading.Thread(target=_start_health_server, daemon=True).start()

# --- هندلر موقت برای عیب‌یابی: هر پیام دریافتی رو توی کنسول چاپ می‌کنه ---
# بعد از اینکه مطمئن شدی همه‌چیز درست کار می‌کنه، می‌تونی این بخش رو حذف کنی
@bot.on_message()
async def debug_logger(bot_: Robot, message: Message):
    print("=== پیام دریافت شد ===")
    print("sender_id:", message.sender_id)
    print("chat_id:", message.chat_id)
    print("text:", message.text)
    print("message.file:", getattr(message, "file", None))
    for attr in ("image", "video", "document", "audio", "music", "voice", "gif", "sticker"):
        val = getattr(message, attr, None)
        if val:
            print(f"message.{attr}:", val)
    print("raw_data:", getattr(message, "raw_data", None))
    print("=======================")


# ---------------- ذخیره‌سازی ساده (JSON) ----------------

def load_db():
    if os.path.exists(DB_FILE):
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_db(db):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)


items = load_db()

# حالت موقتِ گفتگو با ادمین هنگام افزودن آیتم: {admin_id: {"action":..., "code":..., "type":...}}
admin_state = {}
# کدی که هر کاربر منتظرشه، برای وقتی روی دکمه‌ی "بررسی عضویت" می‌زنه
pending_user_request = {}


def is_admin(user_id):
    return user_id in ADMIN_IDS


async def is_member(chat_id):
    try:
        return bool(await bot.check_join(CHANNEL_GUID, chat_id))
    except Exception as e:
        print("خطا در بررسی عضویت:", type(e).__name__, str(e))
        print("CHANNEL_GUID استفاده‌شده:", CHANNEL_GUID)
        print("chat_id استفاده‌شده:", chat_id)
        return False


def join_keypad():
    return (
        InlineBuilder()
        .row(InlineBuilder().button_link("join", "عضویت در کانال", CHANNEL_LINK))
        .row(InlineBuilder().button_simple("check_join", "✅ عضو شدم، بررسی کن"))
        .build()
    )


def schedule_delete(chat_id, message_id, delay=DELETE_AFTER_SECONDS):
    async def _delete():
        await asyncio.sleep(delay)
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as e:
            print("خطا در حذف خودکار پیام:", e)
    # چون همیشه از داخل یه هندلر async صدا زده می‌شه، در همون لحظه
    # یه event loop در حال اجراست و create_task مشکلی نداره.
    asyncio.create_task(_delete())


async def deliver_item(chat_id, code):
    item = items.get(code)
    if not item:
        await bot.send_message(chat_id, "❌ این محتوا پیدا نشد یا حذف شده است.")
        return

    await bot.send_message(
        chat_id,
        f"⏳ این محتوا به دلایل امنیتی، {DELETE_AFTER_SECONDS} ثانیه دیگر "
        f"به‌صورت خودکار حذف می‌شود؛ لطفاً سریع آن را ذخیره کنید."
    )

    itype = item.get("type")
    result = None

    if itype == "text":
        result = await bot.send_message(chat_id, item["content"])
    else:
        # به‌جای اتکا به file_id (که سمت سرور روبیکا نامعتبر اعلام می‌شد)،
        # مستقیم پیام اصلی که ادمین فرستاده بود رو فوروارد می‌کنیم.
        from_chat_id = item["content"]["chat_id"]
        from_message_id = item["content"]["message_id"]
        result = await bot.forward_message(from_chat_id, from_message_id, chat_id)

    try:
        print("نتیجه‌ی ارسال/فوروارد:", result)
        data = result.get("data", {})
        msg_id = data.get("message_id") or data.get("new_message_id")
        if not msg_id:
            raise KeyError("message_id/new_message_id پیدا نشد")
        schedule_delete(chat_id, msg_id)
    except Exception as e:
        print("نتونستم message_id رو برای حذف خودکار بگیرم:", e, result)


# ---------------- دستورات عمومی ----------------

@bot.on_message(commands=["start"])
async def start_handler(bot_: Robot, message: Message):
    parts = (message.text or "").strip().split(maxsplit=1)
    code = parts[1].strip() if len(parts) > 1 else None

    if not code:
        await message.reply(
            "سلام 👋\n"
            "خوش اومدی. برای دریافت محتوا از لینک اختصاصی‌ای که در کانال "
            "گذاشته شده استفاده کن (یا مستقیم /start کد رو بفرست)."
        )
        return

    # توجه: بررسی عضویت اجباری فعلاً غیرفعاله چون متد check_join در این
    # نسخه از کتابخونه‌ی Rubka با خطای INVALID_INPUT مواجه می‌شه، حتی با
    # GUID درست و بات ادمین. اگه خواستی دوباره فعالش کنیم، خط زیر رو
    # از کامنت دربیار:
    # if not await is_member(message.chat_id):
    #     pending_user_request[message.sender_id] = code
    #     await message.reply(
    #         "برای دریافت این محتوا، اول باید عضو کانال اصلی ما بشی 🙏",
    #         inline_keypad=join_keypad(),
    #     )
    #     return

    await deliver_item(message.chat_id, code)


@bot.on_callback("check_join")
async def check_join_callback(bot_: Robot, message: Message):
    code = pending_user_request.get(message.sender_id)
    if not code:
        await message.reply("درخواستی برای بررسی پیدا نشد؛ دوباره از لینک محتوا استفاده کن.")
        return
    if await is_member(message.chat_id):
        pending_user_request.pop(message.sender_id, None)
        await message.reply("✅ عضویتت تایید شد.")
        await deliver_item(message.chat_id, code)
    else:
        await message.reply("❌ هنوز عضو کانال نشدی. بعد از عضویت دوباره دکمه رو بزن.")


@bot.on_message(commands=["myid"])
async def myid_handler(bot_: Robot, message: Message):
    await message.reply(f"آیدی عددی شما: {message.sender_id}")


# این دستور رو توی هر چتی که بات توش باشه (PV، گروه یا کانال) بزن
# تا chat_id/GUID همون‌جا رو بهت بده.
@bot.on_message(commands=["chatid"])
async def chatid_handler(bot_: Robot, message: Message):
    await message.reply(f"chat_id این چت: {message.chat_id}")


@bot.on_message(commands=["checkchannel"])
async def checkchannel_handler(bot_: Robot, message: Message):
    if not is_admin(message.sender_id):
        return
    try:
        info = await bot.get_chat(CHANNEL_GUID)
        print("get_chat نتیجه:", info)
        await message.reply(f"✅ بات به کانال دسترسی داره:\n{info}")
    except Exception as e:
        print("get_chat خطا:", type(e).__name__, str(e))
        await message.reply(f"❌ خطا در دسترسی به کانال: {type(e).__name__}: {e}")


# ---------------- پنل مدیریت (فقط ادمین‌ها) ----------------

VALID_TYPES = ("text", "file")


@bot.on_message(commands=["additem"])
async def additem_handler(bot_: Robot, message: Message):
    if not is_admin(message.sender_id):
        return
    parts = message.text.strip().split()
    if len(parts) != 3 or parts[2] not in VALID_TYPES:
        await message.reply(
            "فرمت درست:\n/additem کد نوع\n"
            "مثال: /additem promo1 file\n"
            f"انواع مجاز: {', '.join(VALID_TYPES)} (برای عکس/فیلم/آهنگ هم از file استفاده کن)"
        )
        return
    code, itype = parts[1], parts[2]
    admin_state[message.sender_id] = {"action": "await_content", "code": code, "type": itype}
    if itype == "text":
        await message.reply("متن مورد نظر رو در پیام بعدی بفرست.")
    else:
        await message.reply(f"فایل نوع «{itype}» رو در پیام بعدی بفرست.")


@bot.on_message(commands=["delitem"])
async def delitem_handler(bot_: Robot, message: Message):
    if not is_admin(message.sender_id):
        return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) != 2:
        await message.reply("فرمت درست: /delitem کد")
        return
    code = parts[1].strip()
    if code in items:
        items.pop(code)
        save_db(items)
        await message.reply(f"✅ آیتم «{code}» حذف شد.")
    else:
        await message.reply("❌ همچین کدی پیدا نشد.")


@bot.on_message(commands=["listitems"])
async def listitems_handler(bot_: Robot, message: Message):
    if not is_admin(message.sender_id):
        return
    if not items:
        await message.reply("هنوز هیچ آیتمی ثبت نشده.")
        return
    lines = [f"• {code} ({data['type']})" for code, data in items.items()]
    await message.reply("لیست آیتم‌ها:\n" + "\n".join(lines))


# دریافت محتوای ارسالی ادمین بعد از /additem
@bot.on_message()
async def catch_admin_content(bot_: Robot, message: Message):
    state = admin_state.get(message.sender_id)
    if not state or not is_admin(message.sender_id):
        return
    if state.get("action") != "await_content":
        return
    if message.text and message.text.startswith("/"):
        return  # دستورهای دیگه رو دست نزن

    code, itype = state["code"], state["type"]

    if itype == "text":
        if not message.text:
            await message.reply("این یه پیام متنی نبود؛ دوباره تلاش کن.")
            return
        items[code] = {"type": "text", "content": message.text, "caption": ""}
    else:
        if not message.file:
            await message.reply("فایلی پیدا نشد؛ دوباره تلاش کن.")
            return
        items[code] = {
            "type": itype,
            "content": {"chat_id": message.chat_id, "message_id": message.message_id},
        }

    save_db(items)
    admin_state.pop(message.sender_id, None)
    await message.reply(
        f"✅ آیتم «{code}» ذخیره شد.\n"
        f"برای دریافتش، کاربر باید توی بات بفرسته: /start {code}"
    )


if __name__ == "__main__":
    print("ربات در حال اجراست... (برای توقف Ctrl+C)")
    bot.run()
