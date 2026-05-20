# -*- coding: utf-8 -*-
import requests, json, time, re, os
from google import genai

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
NOTION_TOKEN   = os.environ["NOTION_TOKEN"]
NOTION_DB_ID   = os.environ["NOTION_DB_ID"]
GEMINI_KEY     = os.environ["GEMINI_KEY"]
CHAT_ID        = os.environ["CHAT_ID"]
STATE_FILE     = "bot_state.json"

gemini = genai.Client(api_key=GEMINI_KEY)

def ask_gemini(prompt):
    r = gemini.models.generate_content(model="gemini-2.5-flash", contents=prompt)
    return r.text

NH = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}

ACHIEVEMENTS = {
    1:  ("🌱", "البداية",    "أكملت أول درس!"),
    10: ("⚡", "المتسارع",   "أكملت 10 دروس!"),
    25: ("🔥", "المتقد",     "أكملت ربع الكورس!"),
    50: ("💎", "المتميز",    "أكملت نصف الكورس!"),
    77: ("👑", "الخبير",     "أكملت الكورس كاملاً!"),
}

# حالة المحادثة لكل مستخدم - تُحفظ في ملف
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except: pass
    return {"offset": 0, "sessions": {}}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)

STATE = load_state()
SESSIONS = STATE.get("sessions", {})

# ===== Telegram Helpers =====
def tg(method, data):
    return requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/{method}", json=data)

def send(text, markup=None, preview=True):
    d = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": not preview}
    if markup:
        d["reply_markup"] = markup
    tg("sendMessage", d)

def answer_cb(cb_id, text=""):
    tg("answerCallbackQuery", {"callback_query_id": cb_id, "text": text})

def remove_buttons(chat_id, msg_id):
    tg("editMessageReplyMarkup", {"chat_id": chat_id, "message_id": msg_id, "reply_markup": {"inline_keyboard": []}})

# ===== Notion Helpers =====
def notion_patch(page_id, props):
    requests.patch(f"https://api.notion.com/v1/pages/{page_id}", headers=NH,
                   data=json.dumps({"properties": props}, ensure_ascii=False).encode())

def get_page(page_id):
    r = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=NH)
    return r.json()

def count_completed():
    body = {"filter": {"property": "الحالة", "select": {"equals": "مكتمل"}}, "page_size": 100}
    r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                      headers=NH, data=json.dumps(body).encode())
    return len(r.json().get("results", []))

# ===== Quiz Generation =====
def generate_quiz(lesson_name, module):
    prompt = f"""أنت مساعد تعليمي لكورس أساسيات البرمجة بـ C++ من Elzero Web School.

الدرس: {lesson_name}
الوحدة: {module}

اكتب 3 أسئلة اختيار من متعدد باللغة العربية عن هذا الدرس.

القواعد:
- الأسئلة تغطي المفاهيم الأساسية للدرس
- كل سؤال له 4 خيارات (أ، ب، ج، د)
- إجابة واحدة صحيحة فقط
- الأسئلة عملية وتطبيقية

اكتب الناتج بهذا التنسيق بالضبط:
س1: [نص السؤال]
أ) [خيار أ]
ب) [خيار ب]
ج) [خيار ج]
د) [خيار د]
الإجابة: [الحرف]

س2: [نص السؤال]
أ) [خيار أ]
ب) [خيار ب]
ج) [خيار ج]
د) [خيار د]
الإجابة: [الحرف]

س3: [نص السؤال]
أ) [خيار أ]
ب) [خيار ب]
ج) [خيار ج]
د) [خيار د]
الإجابة: [الحرف]"""

    return ask_gemini(prompt)

def parse_quiz(quiz_text):
    """تحليل نص الاختبار واستخراج الأسئلة والإجابات"""
    questions = []
    blocks = re.split(r'س\d+:', quiz_text)[1:]
    answer_pattern = re.compile(r'الإجابة:\s*([أبجد])', re.MULTILINE)
    answers = answer_pattern.findall(quiz_text)

    for i, (block, ans) in enumerate(zip(blocks, answers)):
        lines = [l.strip() for l in block.strip().split('\n') if l.strip()]
        q_text = lines[0] if lines else ""
        choices = {}
        for line in lines[1:]:
            for letter in ['أ', 'ب', 'ج', 'د']:
                if line.startswith(f'{letter})'):
                    choices[letter] = line[2:].strip()
        questions.append({"q": q_text, "choices": choices, "answer": ans, "index": i+1})
    return questions

def evaluate_answer(lesson_name, question, user_answer, correct_answer, choices):
    """تصحيح إجابة المستخدم وشرح"""
    is_correct = user_answer.strip() == correct_answer
    if is_correct:
        return True, f"✅ <b>صح!</b> الإجابة الصحيحة هي ({correct_answer})"

    prompt = f"""الدرس: {lesson_name}
السؤال: {question}
الخيارات: {choices}
الإجابة الصحيحة: ({correct_answer}) {choices.get(correct_answer, '')}
إجابة الطالب: ({user_answer}) {choices.get(user_answer, '')}

اشرح بالعربية في جملتين لماذا الإجابة الصحيحة هي ({correct_answer}) وليس ({user_answer}). كن موجزاً."""

    return False, f"❌ <b>خطأ!</b> الصحيح ({correct_answer})\n\n💡 {ask_gemini(prompt)}"

def solve_problem(code_or_question, lesson_context="C++"):
    """حل مشكلة برمجية وشرحها"""
    prompt = f"""أنت مساعد تعليمي متخصص في C++ من Elzero Web School.
المستخدم يدرس: {lesson_context}

المشكلة أو الكود:
{code_or_question}

الواجب:
1. اشرح المشكلة بالعربية
2. أعطه الحل الصحيح مع شرح
3. أضف نصيحة تعليمية
كن موجزاً وعملياً."""
    return ask_gemini(prompt)

# ===== Achievement Check =====
def check_achievement(completed_count):
    if completed_count in ACHIEVEMENTS:
        emoji, title, desc = ACHIEVEMENTS[completed_count]
        send(
            f"🏆 <b>إنجاز جديد يا أيمن!</b>\n\n"
            f"{emoji} <b>{title}</b>\n"
            f"{desc}\n\n"
            f"📊 إجمالي الدروس المكتملة: {completed_count}"
        )

# ===== Main Handlers =====
def handle_complete(page_id, cb_id, chat_id, msg_id):
    """عند الضغط على ✅ أكملت الدرس"""
    # تحديث Notion
    notion_patch(page_id, {"الحالة": {"select": {"name": "مكتمل"}}})
    answer_cb(cb_id, "🎉 رائع! جاري إعداد الاختبار...")
    remove_buttons(chat_id, msg_id)

    # جلب تفاصيل الدرس
    page = get_page(page_id)
    props = page["properties"]
    lesson_name = props["اسم الدرس"]["title"][0]["plain_text"] if props["اسم الدرس"]["title"] else "الدرس"
    module = props["الوحدة"]["rich_text"][0]["plain_text"] if props["الوحدة"]["rich_text"] else ""

    # فحص الإنجازات
    completed = count_completed()
    check_achievement(completed)

    # رسالة إنجاز
    send(
        f"✅ <b>أحسنت يا أيمن!</b>\n\n"
        f"📖 {lesson_name}\n"
        f"تم تسجيله مكتملاً في Notion 🎯\n\n"
        f"⏳ جاري تحضير اختبار سريع..."
    )

    time.sleep(2)

    # توليد الاختبار
    quiz_text = generate_quiz(lesson_name, module)
    questions = parse_quiz(quiz_text)

    if not questions:
        send("⚠️ تعذّر إنشاء الاختبار الآن. يمكنك إرسال 'مشكلة' + سؤالك للمساعدة.")
        return

    # حفظ الاختبار في الجلسة
    SESSIONS[CHAT_ID] = {
        "type": "quiz",
        "questions": questions,
        "current": 0,
        "score": 0,
        "lesson": lesson_name
    }

    send_question(0, questions, lesson_name)

def send_question(idx, questions, lesson_name):
    """إرسال سؤال من الاختبار"""
    q = questions[idx]
    choices_text = "\n".join([f"  {k}) {v}" for k, v in q["choices"].items()])

    keyboard = {"inline_keyboard": [
        [{"text": f"أ) {q['choices'].get('أ','')[:30]}", "callback_data": f"ans_أ"}],
        [{"text": f"ب) {q['choices'].get('ب','')[:30]}", "callback_data": f"ans_ب"}],
        [{"text": f"ج) {q['choices'].get('ج','')[:30]}", "callback_data": f"ans_ج"}],
        [{"text": f"د) {q['choices'].get('د','')[:30]}", "callback_data": f"ans_د"}],
    ]}

    send(
        f"🧪 <b>اختبار الدرس - سؤال {idx+1}/{len(questions)}</b>\n\n"
        f"❓ {q['q']}",
        markup=keyboard
    )

def handle_answer(answer_letter, cb_id, msg_id):
    """معالجة إجابة الاختبار"""
    session = SESSIONS.get(CHAT_ID)
    if not session or session["type"] != "quiz":
        answer_cb(cb_id, "لا يوجد اختبار نشط")
        return

    remove_buttons(CHAT_ID, msg_id)
    answer_cb(cb_id)

    questions = session["questions"]
    idx = session["current"]
    q = questions[idx]

    is_correct, feedback = evaluate_answer(
        session["lesson"], q["q"], answer_letter, q["answer"], q["choices"]
    )
    if is_correct:
        session["score"] += 1

    send(feedback)
    time.sleep(1.5)

    # السؤال التالي أو النتيجة النهائية
    session["current"] += 1
    if session["current"] < len(questions):
        send_question(session["current"], questions, session["lesson"])
    else:
        score = session["score"]
        total = len(questions)
        emoji = "🏆" if score == total else "💪" if score >= total//2 else "📚"
        send(
            f"{emoji} <b>نتيجة الاختبار</b>\n\n"
            f"درجتك: <b>{score}/{total}</b>\n\n"
            f"{'ممتاز! أتقنت الدرس 🎉' if score==total else 'جيد! راجع النقاط الضعيفة 📖' if score>0 else 'لا بأس! أعد مشاهدة الدرس 🔄'}\n\n"
            f"💡 إذا عندك سؤال أو مشكلة في الكود، أرسل:\n<code>مشكلة [كودك أو سؤالك هنا]</code>"
        )
        del SESSIONS[CHAT_ID]

def handle_problem(text):
    """معالجة طلب حل مشكلة"""
    problem = text.replace("مشكلة", "", 1).strip()
    if len(problem) < 3:
        send("📝 أرسل المشكلة أو الكود بعد كلمة 'مشكلة'\nمثال:\n<code>مشكلة int x = \"hello\";</code>")
        return

    send("⏳ جاري تحليل المشكلة...")
    solution = solve_problem(problem)
    send(f"🔧 <b>الحل والشرح:</b>\n\n{solution}")

# ===== Main: تشغيل واحد (GitHub Actions) =====
def run():
    offset = STATE.get("offset", 0)
    print(f"🤖 فحص التحديثات (offset={offset})")

    try:
        params = {"timeout": 0, "allowed_updates": ["callback_query", "message"]}
        if offset:
            params["offset"] = offset
        r = requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates", params=params, timeout=20)
        updates = r.json().get("result", [])
        print(f"📥 {len(updates)} تحديث")

        for update in updates:
            offset = update["update_id"] + 1

            if "callback_query" in update:
                cb = update["callback_query"]
                data    = cb.get("data", "")
                cb_id   = cb["id"]
                chat_id = cb["message"]["chat"]["id"]
                msg_id  = cb["message"]["message_id"]

                if data.startswith("done_"):
                    handle_complete(data[5:], cb_id, chat_id, msg_id)
                elif data.startswith("ans_"):
                    handle_answer(data[4:], cb_id, msg_id)

            elif "message" in update:
                text = update["message"].get("text", "").strip()
                if text.startswith("مشكلة"):
                    handle_problem(text)
                elif text.lower() in ["/start", "مرحبا", "مرحباً"]:
                    send(
                        "👋 <b>أهلاً يا أيمن!</b>\n\n"
                        "📚 كل يوم 9م تصلك محاضرة اليوم\n"
                        "✅ اضغط 'أكملت الدرس' لتسجيل التقدم\n"
                        "🧪 بعد الإكمال يأتيك اختبار سريع\n"
                        "🔧 أرسل <code>مشكلة [كودك]</code> للمساعدة"
                    )

        # حفظ الحالة
        STATE["offset"] = offset
        STATE["sessions"] = SESSIONS
        save_state(STATE)
        print(f"✅ تم حفظ الحالة - offset={offset}")

    except Exception as e:
        print(f"خطأ: {e}")

if __name__ == "__main__":
    run()
