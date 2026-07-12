"""
ربات روبیکا - توزیع امن محتوا
=================================
پیش‌نیازها (در Pydroid 3):
  1) از منوی Pip، پکیج‌های زیر رو نصب کن:
        pip install rubka
        pip install Pillow
  2) با @BotFather در روبیکا یک بات بساز و توکن رو کپی کن.
  3) بات رو اجرا کن، توی PV بات بزن /myid و آیدی خودت رو در ADMIN_IDS بذار.

  توجه: فعلاً بررسی «اجباری بودن عضویت کانال» از این نسخه حذف شده چون
  با خطای INVALID_INPUT مواجه می‌شد (احتمالاً به‌خاطر مشکل در GUID/دسترسی
  بات به کانال). اگه بعداً خواستی دوباره اضافه‌ش کنیم، باید /chatid رو
  داخل خود کانال بزنیم و مطمئن بشیم بات واقعاً ادمین کاناله.

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

from rubka import Robot
from rubka.context import Message

# ---------------- تنظیمات ----------------
TOKEN = "BJDGGF0BLZEAJLPMSQSSBFGRESVVTORVRJZPFHLWJJMJZOHCSESJLZDFKWUFYDTC"
ADMIN_IDS = {"u0Icszk0030f58b09449973d0cccd5e0"}           # آیدی عددی خودت (با /myid بگیر)
DELETE_AFTER_SECONDS = 60
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "items.json")

bot = Robot(TOKEN)

# --- هندلر موقت برای عیب‌یابی: هر پیام دریافتی رو توی کنسول چاپ می‌کنه ---
# بعد از اینکه مطمئن شدی همه‌چیز درست کار می‌کنه، می‌تونی این بخش رو حذف کنی
@bot.on_message()
async def debug_logger(bot_: Robot, message: Message):
    print("=== پیام دریافت شد ===")
    print("sender_id:", message.sender_id)
    print("chat_id:", message.chat_id)
    print("text:", message.text)
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


def is_admin(user_id):
    return user_id in ADMIN_IDS


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
    caption = item.get("caption", "")
    result = None

    if itype == "text":
        result = await bot.send_message(chat_id, item["content"])
    elif itype == "image":
        result = await bot.send_image(chat_id, file_id=item["content"], text=caption)
    elif itype == "file":
        result = await bot.send_document(chat_id, file_id=item["content"], text=caption)
    elif itype == "music":
        result = await bot.send_music(chat_id, file_id=item["content"], text=caption)
    elif itype == "voice":
        result = await bot.send_voice(chat_id, file_id=item["content"], text=caption)
    elif itype == "gif":
        result = await bot.send_gif(chat_id, file_id=item["content"], text=caption)

    try:
        msg_id = result["data"]["message_id"]
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

    await deliver_item(message.chat_id, code)


@bot.on_message(commands=["myid"])
async def myid_handler(bot_: Robot, message: Message):
    await message.reply(f"آیدی عددی شما: {message.sender_id}")


# این دستور رو توی هر چتی که بات توش باشه (PV، گروه یا کانال) بزن
# تا chat_id/GUID همون‌جا رو بهت بده.
@bot.on_message(commands=["chatid"])
async def chatid_handler(bot_: Robot, message: Message):
    if not is_admin(message.sender_id):
        return
    await message.reply(f"chat_id این چت: {message.chat_id}")


# ---------------- پنل مدیریت (فقط ادمین‌ها) ----------------

VALID_TYPES = ("text", "image", "file", "music", "voice", "gif")


@bot.on_message(commands=["additem"])
async def additem_handler(bot_: Robot, message: Message):
    if not is_admin(message.sender_id):
        return
    parts = message.text.strip().split()
    if len(parts) != 3 or parts[2] not in VALID_TYPES:
        await message.reply(
            "فرمت درست:\n/additem کد نوع\n"
            "مثال: /additem promo1 image\n"
            f"انواع مجاز: {', '.join(VALID_TYPES)}"
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
        file_id = message.file.get("file_id")
        items[code] = {"type": itype, "content": file_id, "caption": message.text or ""}

    save_db(items)
    admin_state.pop(message.sender_id, None)
    await message.reply(
        f"✅ آیتم «{code}» ذخیره شد.\n"
        f"برای دریافتش، کاربر باید توی بات بفرسته: /start {code}"
    )


if __name__ == "__main__":
    print("ربات در حال اجراست... (برای توقف Ctrl+C)")
    bot.run()
