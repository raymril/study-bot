# -*- coding: utf-8 -*-
import requests, os
import json
from datetime import date, datetime

# ======= الإعدادات من env =======
NOTION_TOKEN   = os.environ["NOTION_TOKEN"]
NOTION_DB_ID   = os.environ["NOTION_DB_ID"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT  = os.environ["CHAT_ID"]

# تاريخ بداية الخطة (اليوم الأول من الدراسة)
START_DATE = date(2026, 5, 20)

# ======= حساب رقم اليوم =======
today       = date.today()
day_number  = (today - START_DATE).days + 1

notion_headers = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json"
}

def get_todays_lesson():
    body = {
        "filter": {
            "property": "اليوم",
            "number": {"equals": day_number}
        }
    }
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=notion_headers,
        data=json.dumps(body).encode("utf-8")
    )
    results = r.json().get("results", [])
    if not results:
        return None
    page = results[0]
    props = page["properties"]

    name       = props["اسم الدرس"]["title"][0]["plain_text"] if props["اسم الدرس"]["title"] else "—"
    course     = props["الكورس"]["select"]["name"] if props["الكورس"]["select"] else "—"
    module     = props["الوحدة"]["rich_text"][0]["plain_text"] if props["الوحدة"]["rich_text"] else "—"
    lesson     = props["رقم الدرس"]["number"] if props["رقم الدرس"]["number"] else 0
    week       = props["الأسبوع"]["number"] if props["الأسبوع"]["number"] else 0
    url        = props["رابط الفيديو"]["url"] if props["رابط الفيديو"]["url"] else ""
    assignment = props.get("رابط التكليف", {}).get("url", "") or ""
    page_id    = page["id"]

    return {
        "name": name, "course": course, "module": module,
        "lesson": lesson, "week": week, "url": url,
        "assignment": assignment, "page_id": page_id
    }

def mark_as_in_progress(page_id):
    body = {"properties": {"الحالة": {"select": {"name": "جاري"}}}}
    requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=notion_headers,
        data=json.dumps(body).encode("utf-8")
    )

def send_telegram(message):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT, "text": message, "parse_mode": "HTML", "disable_web_page_preview": False}
    )

# ======= التنفيذ =======
lesson = get_todays_lesson()

if day_number < 1:
    send_telegram("⏳ الخطة تبدأ غداً! استعد يا أيمن 💪")

elif lesson is None:
    msg = (
        f"🎉 <b>أحسنت يا أيمن!</b>\n\n"
        f"لا يوجد درس مجدول لليوم {day_number}.\n"
        f"إما أنك أكملت الخطة أو هذا يوم راحة مستحق 🏖️"
    )
    send_telegram(msg)

else:
    msg = (
        f"📚 <b>درسك اليوم - {today.strftime('%A %d/%m/%Y')}</b>\n"
        f"{'─' * 30}\n\n"
        f"📖 <b>الدرس #{lesson['lesson']}</b>: {lesson['name']}\n"
        f"🗂 الوحدة: {lesson['module']}\n"
        f"🎓 الكورس: {lesson['course']}\n"
        f"📅 الأسبوع {lesson['week']} | اليوم {day_number}\n\n"
    )
    if lesson["url"]:
        msg += f"▶️ <a href=\"{lesson['url']}\">شاهد الفيديو هنا</a>\n"
    if lesson["assignment"]:
        msg += f"📝 <a href=\"{lesson['assignment']}\">تكليفات الدرس على Elzero</a>\n"
    msg += (
        f"\n💡 <b>خطوات اليوم:</b>\n"
        f"1️⃣ شاهد الفيديو\n"
        f"2️⃣ طبّق الكود بنفسك\n"
        f"3️⃣ حل التكليفات على الموقع\n"
        f"4️⃣ اضغط الزر أدناه بعد الانتهاء ⬇️"
    )

    keyboard = {
        "inline_keyboard": [[
            {"text": "✅ أكملت الدرس", "callback_data": f"done_{lesson['page_id']}"}
        ]]
    }

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={
            "chat_id": TELEGRAM_CHAT,
            "text": msg,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
            "reply_markup": keyboard
        }
    )
    print(f"✅ تم إرسال إشعار الدرس {lesson['lesson']}: {lesson['name']}")
