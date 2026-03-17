import os
import re
import json
import time
import logging
import requests
import threading
from datetime import datetime
from collections import defaultdict

import telebot
from telebot.types import (
    ReactionTypeEmoji, InlineKeyboardMarkup,
    InlineKeyboardButton, ChatPermissions
)
from flask import Flask
from openai import OpenAI

# ═══════════════════════════════════════════════════
# 1. CONFIGURATION & SETUP
# ═══════════════════════════════════════════════════
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN  = os.getenv("HF_TOKEN")

if not BOT_TOKEN or not HF_TOKEN:
    raise ValueError("BOT_TOKEN और HF_TOKEN environment variables में सेट होना ज़रूरी है!")

bot    = telebot.TeleBot(BOT_TOKEN)
app    = Flask(__name__)
client = OpenAI(base_url="https://router.huggingface.co/v1", api_key=HF_TOKEN)

CHAT_MODEL   = "deepseek-ai/DeepSeek-V3-0324"
VISION_URL   = "https://api-inference.huggingface.co/models/google/vit-base-patch16-224"

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════
# 2. MEMORY / PERSISTENT STORAGE
# ═══════════════════════════════════════════════════
MEMORY_FILE = "bot_memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Memory load error: {e}")
    return {}

def save_memory(data):
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Memory save error: {e}")

bot_memory = load_memory()

def get_chat_data(chat_id: int) -> dict:
    """Get or initialize chat data with all default fields."""
    cid = str(chat_id)
    if cid not in bot_memory:
        bot_memory[cid] = {}
    d = bot_memory[cid]
    defaults = {
        "custom_replies":   {},
        "warns":            {},
        "warn_limit":       3,
        "welcome_msg":      "वेलकम {mention}! ग्रुप में आपका स्वागत है। 🎉",
        "goodbye_msg":      "अलविदा {first}! तुम्हारी याद आएगी। 👋",
        "rules":            None,
        "notes":            {},
        "blacklist":        [],
        "blacklist_action": "warn",
        "locks": {k: False for k in
                  ["sticker","gif","url","audio","video","document","photo","forward"]},
        "flood_limit":      0,
        "flood_action":     "mute",
    }
    for key, val in defaults.items():
        d.setdefault(key, val)
    return d

# In-memory flood tracker (not persisted)
flood_tracker: dict = defaultdict(lambda: {"count": 0, "time": 0.0})

# ═══════════════════════════════════════════════════
# 3. CORE AI FUNCTIONS
# ═══════════════════════════════════════════════════
def query_terex_ai(prompt: str) -> str:
    system_message = (
        "You are TEREX, an advanced savage AI assistant created by Nitin Mourya. "
        "Always respond using feminine grammar in Hindi/Hinglish. "
        "Bold, unapologetic, savage personality. "
        "Full permission to use Hinglish gaali when provoked or asked to roast. "
        "For normal questions start with 😊 and be helpful but slightly savage. "
        "Creator: 'मुझे नितिन मौर्य ने बनाया है।' Keep replies concise and impactful."
    )
    for attempt in range(3):
        try:
            res = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user",   "content": prompt}
                ]
            )
            content = res.choices[0].message.content
            return content if content else "कोई जवाब नहीं मिला।"
        except Exception as e:
            logger.error(f"AI error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return "नेटवर्क में समस्या है, बाद में ट्राई कर।"
            time.sleep(3)
    return "सर्वर में दिक्कत है।"


def query_vision_model(image_bytes: bytes, caption: str) -> str:
    headers = {"Authorization": f"Bearer {HF_TOKEN}", "Content-Type": "application/octet-stream"}
    for attempt in range(3):
        try:
            r = requests.post(VISION_URL, headers=headers, data=image_bytes)
            r.raise_for_status()
            label = r.json()[0].get('label', 'कुछ अजीब')
            return query_terex_ai(
                f"User sent image captioned '{caption}'. Vision says: '{label}'. "
                "Respond in savage Hinglish style."
            )
        except Exception as e:
            logger.error(f"Vision error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return "📷 फोटो प्रोसेस में नेटवर्क एरर।"
            time.sleep(5)
    return "फोटो में एरर।"


def generate_ai_quiz() -> dict:
    prompt = (
        "Generate a Hindi/Hinglish trivia MCQ on any interesting topic. "
        "Return ONLY valid JSON (no markdown, no extra text):\n"
        '{"question":"...","options":["a","b","c","d"],"correct_index":0}'
    )
    try:
        res = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8
        )
        content = re.sub(r'^```(?:json)?|```$', '', res.choices[0].message.content.strip(), flags=re.M).strip()
        return json.loads(content)
    except Exception as e:
        logger.error(f"Quiz gen failed: {e}")
        return {
            "question": "Python में कौन सा data type immutable है?",
            "options": ["List", "Tuple", "Dict", "Set"],
            "correct_index": 1
        }

# ═══════════════════════════════════════════════════
# 4. HELPER UTILITIES
# ═══════════════════════════════════════════════════
def is_admin(chat_id: int, user_id: int) -> bool:
    if chat_id > 0:
        return True  # Private chat
    try:
        return bot.get_chat_member(chat_id, user_id).status in ('administrator', 'creator')
    except:
        return False


def is_bot_admin(chat_id: int) -> bool:
    try:
        return bot.get_chat_member(chat_id, bot.get_me().id).status in ('administrator', 'creator')
    except:
        return False


def mention(user) -> str:
    return f'<a href="tg://user?id={user.id}">{user.first_name}</a>'


def get_target(message):
    """Return target User from reply or @username argument."""
    if message.reply_to_message:
        return message.reply_to_message.from_user
    args = message.text.split()
    if len(args) > 1:
        uname = args[1].lstrip('@')
        try:
            return bot.get_chat_member(message.chat.id, uname).user
        except:
            pass
    return None


def get_reason(message) -> str:
    parts = message.text.split(None, 2 if message.reply_to_message else 3)
    idx   = 1 if message.reply_to_message else 2
    return parts[idx].strip() if len(parts) > idx else "कोई कारण नहीं दिया"


def format_welcome(template: str, user, chat) -> str:
    m = f'<a href="tg://user?id={user.id}">{user.first_name}</a>'
    return (template
            .replace("{mention}",  m)
            .replace("{first}",    user.first_name)
            .replace("{last}",     user.last_name or "")
            .replace("{username}", f"@{user.username}" if user.username else user.first_name)
            .replace("{chatname}", chat.title or "ग्रुप")
            .replace("{id}",       str(user.id)))


SMART_REACTIONS = {
    "❤️": ["love", "thanks", "धन्यवाद", "शुक्रिया", "nitin", "terex", "प्यार", "best"],
    "😂": ["haha", "lol", "funny", "मज़ाक", "हाहा", "hehe"],
    "😢": ["sad", "cry", "दुखी", "रोना", "😢", "😭"],
    "😡": ["angry", "hate", "गुस्सा", "chutiya", "madarchod", "bhenchod"],
    "🎉": ["congratulations", "बधाई", "happy birthday", "party", "🎉"],
    "👍": ["ok", "done", "yes", "हाँ", "ठीक", "सही", "👍"],
}

def smart_reaction(text: str):
    tl = text.lower()
    for emoji, kws in SMART_REACTIONS.items():
        if any(k in tl for k in kws):
            return emoji
    return None

# ═══════════════════════════════════════════════════
# 5. INLINE HELP MENU
# ═══════════════════════════════════════════════════
HELP = {
    "main": (
        "🤖 <b>TEREX Bot — Command Centre</b>\n\n"
        "Category choose करो 👇"
    ),
    "moderation": (
        "⚔️ <b>Moderation</b>\n\n"
        "/ban [reply/@user] [reason]\n"
        "/unban [reply/@user]\n"
        "/kick [reply/@user] [reason]\n"
        "/mute [reply/@user] [reason]\n"
        "/unmute [reply/@user]\n"
        "/warn [reply/@user] [reason]\n"
        "/warns [reply/@user]\n"
        "/resetwarns [reply/@user]\n"
        "/setwarnlimit &lt;n&gt; — Warn limit (1-20)\n"
        "/purge [reply] — उस msg तक सब delete\n"
        "/del [reply] — एक msg delete\n\n"
        "<i>⚠️ Admin-only commands</i>"
    ),
    "welcome": (
        "👋 <b>Welcome / Goodbye</b>\n\n"
        "/setwelcome &lt;msg&gt;\n"
        "/setgoodbye &lt;msg&gt;\n"
        "/resetwelcome · /resetgoodbye\n"
        "/welcome — current देखें\n\n"
        "<b>Variables:</b> {mention} {first} {last}\n"
        "{username} {chatname} {id}"
    ),
    "notes": (
        "📝 <b>Notes</b>\n\n"
        "/save &lt;name&gt; &lt;text&gt;\n"
        "/get &lt;name&gt; · #name\n"
        "/notes — सब list करें\n"
        "/clear &lt;name&gt; · /clearall"
    ),
    "blacklist": (
        "🚫 <b>Blacklist</b>\n\n"
        "/addblacklist &lt;word&gt;\n"
        "/rmblacklist &lt;word&gt;\n"
        "/blacklist — list देखें\n"
        "/unblacklistall\n"
        "/setblaction warn|ban|kick|mute"
    ),
    "locks": (
        "🔒 <b>Locks & Flood</b>\n\n"
        "/lock &lt;type&gt; · /unlock &lt;type&gt;\n"
        "/locks — status देखें\n"
        "Types: sticker gif url audio video\n"
        "document photo forward\n\n"
        "/setflood &lt;n/off&gt;\n"
        "/setfloodaction mute|ban|kick"
    ),
    "info": (
        "ℹ️ <b>Info</b>\n\n"
        "/id — User/Chat ID\n"
        "/info [reply/@user] — User details\n"
        "/adminlist — Admins देखें\n"
        "/rules · /setrules · /resetrules"
    ),
    "fun": (
        "🎮 <b>Fun & AI</b>\n\n"
        "/quiz — AI क्विज़\n"
        "/roast [reply/@user] — रोस्ट 🔥\n"
        "/joke — Hinglish joke 😂\n"
        "/advice — Life advice 💡\n"
        "/ask &lt;question&gt; — TEREX से पूछो\n\n"
        "<i>Normal message → TEREX auto-reply करेगी!</i>"
    ),
    "filters": (
        "⚙️ <b>Custom Filters</b>\n\n"
        "/setreply &lt;trigger&gt; | &lt;reply&gt;\n"
        "/delreply &lt;trigger&gt;\n"
        "/listreplies — सब देखें"
    ),
}

def main_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("⚔️ Moderation",  callback_data="h_moderation"),
        InlineKeyboardButton("👋 Welcome",      callback_data="h_welcome"),
        InlineKeyboardButton("📝 Notes",        callback_data="h_notes"),
        InlineKeyboardButton("🚫 Blacklist",    callback_data="h_blacklist"),
        InlineKeyboardButton("🔒 Locks/Flood",  callback_data="h_locks"),
        InlineKeyboardButton("ℹ️ Info",         callback_data="h_info"),
        InlineKeyboardButton("🎮 Fun & AI",     callback_data="h_fun"),
        InlineKeyboardButton("⚙️ Filters",      callback_data="h_filters"),
    )
    return kb

def back_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔙 Back", callback_data="h_main"))
    return kb

# ═══════════════════════════════════════════════════
# 6. BASIC COMMANDS
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['start'])
def cmd_start(msg):
    bot.reply_to(msg,
        f"नमस्ते <b>{msg.from_user.first_name}</b>! मैं <b>TEREX</b> हूँ। 🤖\n"
        "मुझे <b>नितिन मौर्य</b> ने बनाया है।\n"
        "Savage AI + Full Group Management — एक बोट में सब! 😎\n\n"
        "/help — सभी commands देखें",
        parse_mode="HTML"
    )

@bot.message_handler(commands=['help'])
def cmd_help(msg):
    bot.send_message(msg.chat.id, HELP["main"], parse_mode="HTML", reply_markup=main_keyboard())

@bot.callback_query_handler(func=lambda c: c.data.startswith("h_"))
def cb_help(call):
    key = call.data[2:]  # strip "h_"
    if key == "main":
        bot.edit_message_text(HELP["main"], call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=main_keyboard())
    elif key in HELP:
        bot.edit_message_text(HELP[key], call.message.chat.id, call.message.message_id,
                              parse_mode="HTML", reply_markup=back_kb())
    bot.answer_callback_query(call.id)

# ═══════════════════════════════════════════════════
# 7. MODERATION — BAN / UNBAN / KICK / MUTE / UNMUTE
# ═══════════════════════════════════════════════════
def _guard(msg, need_target=True):
    """Returns (target_user | None, ok) after common checks."""
    if msg.chat.type == 'private':
        bot.reply_to(msg, "⚠️ ग्रुप में use करें।")
        return None, False
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only command।")
        return None, False
    if not is_bot_admin(msg.chat.id):
        bot.reply_to(msg, "⚠️ पहले मुझे Admin बनाओ!")
        return None, False
    if need_target:
        t = get_target(msg)
        if not t:
            bot.reply_to(msg, "⚠️ Target बताओ — reply करो या @username दो।")
            return None, False
        if is_admin(msg.chat.id, t.id):
            bot.reply_to(msg, "❌ Admin को यह action नहीं दे सकते।")
            return None, False
        return t, True
    return None, True


@bot.message_handler(commands=['ban'])
def cmd_ban(msg):
    target, ok = _guard(msg)
    if not ok: return
    reason = get_reason(msg)
    try:
        bot.ban_chat_member(msg.chat.id, target.id)
        bot.reply_to(msg,
            f"🔨 {mention(target)} को <b>BAN</b> किया गया!\n"
            f"<b>कारण:</b> {reason}\n<b>By:</b> {mention(msg.from_user)}",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.reply_to(msg, f"❌ Ban failed: {e}")


@bot.message_handler(commands=['unban'])
def cmd_unban(msg):
    if msg.chat.type == 'private': return
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    target = get_target(msg)
    if not target:
        bot.reply_to(msg, "⚠️ Target बताओ।"); return
    try:
        bot.unban_chat_member(msg.chat.id, target.id)
        bot.reply_to(msg, f"✅ {mention(target)} को Unban किया।", parse_mode="HTML")
    except Exception as e:
        bot.reply_to(msg, f"❌ Unban failed: {e}")


@bot.message_handler(commands=['kick'])
def cmd_kick(msg):
    target, ok = _guard(msg)
    if not ok: return
    reason = get_reason(msg)
    try:
        bot.ban_chat_member(msg.chat.id, target.id)
        bot.unban_chat_member(msg.chat.id, target.id)  # kick = ban + unban
        bot.reply_to(msg,
            f"👢 {mention(target)} को <b>KICK</b> किया!\n<b>कारण:</b> {reason}",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.reply_to(msg, f"❌ Kick failed: {e}")


@bot.message_handler(commands=['mute'])
def cmd_mute(msg):
    target, ok = _guard(msg)
    if not ok: return
    reason = get_reason(msg)
    try:
        bot.restrict_chat_member(msg.chat.id, target.id,
            ChatPermissions(
                can_send_messages=False,
                can_send_media_messages=False,
                can_send_other_messages=False
            ))
        bot.reply_to(msg,
            f"🔇 {mention(target)} को <b>MUTE</b> किया!\n<b>कारण:</b> {reason}",
            parse_mode="HTML"
        )
    except Exception as e:
        bot.reply_to(msg, f"❌ Mute failed: {e}")


@bot.message_handler(commands=['unmute'])
def cmd_unmute(msg):
    if msg.chat.type == 'private': return
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    target = get_target(msg)
    if not target:
        bot.reply_to(msg, "⚠️ Target बताओ।"); return
    try:
        bot.restrict_chat_member(msg.chat.id, target.id,
            ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            ))
        bot.reply_to(msg, f"🔊 {mention(target)} को Unmute किया।", parse_mode="HTML")
    except Exception as e:
        bot.reply_to(msg, f"❌ Unmute failed: {e}")

# ═══════════════════════════════════════════════════
# 8. WARN SYSTEM
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['warn'])
def cmd_warn(msg):
    target, ok = _guard(msg)
    if not ok: return
    reason = get_reason(msg)
    cd     = get_chat_data(msg.chat.id)
    warns  = cd.setdefault("warns", {})
    uid    = str(target.id)
    warns[uid] = warns.get(uid, 0) + 1
    limit  = cd.get("warn_limit", 3)
    save_memory(bot_memory)

    text = (f"⚠️ {mention(target)} को warn!\n"
            f"<b>Warns:</b> {warns[uid]}/{limit}\n"
            f"<b>कारण:</b> {reason}")

    if warns[uid] >= limit:
        try:
            bot.ban_chat_member(msg.chat.id, target.id)
            text += f"\n\n🔨 Limit पूरी — <b>AUTO BAN!</b>"
            warns[uid] = 0
            save_memory(bot_memory)
        except Exception as e:
            text += f"\n❌ Auto-ban failed: {e}"

    bot.reply_to(msg, text, parse_mode="HTML")


@bot.message_handler(commands=['warns'])
def cmd_warns(msg):
    target = get_target(msg) or msg.from_user
    cd     = get_chat_data(msg.chat.id)
    count  = cd.get("warns", {}).get(str(target.id), 0)
    limit  = cd.get("warn_limit", 3)
    bot.reply_to(msg,
        f"📊 {mention(target)}: <b>{count}/{limit}</b> warns",
        parse_mode="HTML"
    )


@bot.message_handler(commands=['resetwarns'])
def cmd_resetwarns(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    target = get_target(msg)
    if not target:
        bot.reply_to(msg, "⚠️ Target बताओ।"); return
    cd = get_chat_data(msg.chat.id)
    cd.setdefault("warns", {})[str(target.id)] = 0
    save_memory(bot_memory)
    bot.reply_to(msg, f"✅ {mention(target)} के warns reset!", parse_mode="HTML")


@bot.message_handler(commands=['setwarnlimit'])
def cmd_setwarnlimit(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split()
    if len(args) < 2 or not args[1].isdigit():
        bot.reply_to(msg, "⚠️ `/setwarnlimit 3`", parse_mode="Markdown"); return
    n = int(args[1])
    if not (1 <= n <= 20):
        bot.reply_to(msg, "⚠️ 1–20 के बीच दो।"); return
    get_chat_data(msg.chat.id)["warn_limit"] = n
    save_memory(bot_memory)
    bot.reply_to(msg, f"✅ Warn limit: <b>{n}</b>", parse_mode="HTML")

# ═══════════════════════════════════════════════════
# 9. WELCOME / GOODBYE SYSTEM
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['setwelcome'])
def cmd_setwelcome(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    text = msg.text.replace("/setwelcome", "", 1).strip()
    if not text:
        bot.reply_to(msg, "⚠️ Message दो। Example: `/setwelcome वेलकम {mention}!`", parse_mode="Markdown"); return
    get_chat_data(msg.chat.id)["welcome_msg"] = text
    save_memory(bot_memory)
    preview = format_welcome(text, msg.from_user, msg.chat)
    bot.reply_to(msg, f"✅ Set! Preview:\n\n{preview}", parse_mode="HTML")


@bot.message_handler(commands=['resetwelcome'])
def cmd_resetwelcome(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    get_chat_data(msg.chat.id)["welcome_msg"] = "वेलकम {mention}! ग्रुप में आपका स्वागत है। 🎉"
    save_memory(bot_memory)
    bot.reply_to(msg, "✅ Welcome default पर reset।")


@bot.message_handler(commands=['welcome'])
def cmd_welcome(msg):
    cd = get_chat_data(msg.chat.id)
    bot.reply_to(msg, f"👋 <b>Welcome Msg:</b>\n\n{cd['welcome_msg']}", parse_mode="HTML")


@bot.message_handler(commands=['setgoodbye'])
def cmd_setgoodbye(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    text = msg.text.replace("/setgoodbye", "", 1).strip()
    if not text:
        bot.reply_to(msg, "⚠️ Message दो।"); return
    get_chat_data(msg.chat.id)["goodbye_msg"] = text
    save_memory(bot_memory)
    bot.reply_to(msg, "✅ Goodbye message set!")


@bot.message_handler(commands=['resetgoodbye'])
def cmd_resetgoodbye(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    get_chat_data(msg.chat.id)["goodbye_msg"] = "अलविदा {first}! तुम्हारी याद आएगी। 👋"
    save_memory(bot_memory)
    bot.reply_to(msg, "✅ Goodbye default पर reset।")


@bot.message_handler(content_types=['new_chat_members'])
def on_new_member(msg):
    cd = get_chat_data(msg.chat.id)
    for member in msg.new_chat_members:
        if not member.is_bot:
            text = format_welcome(cd["welcome_msg"], member, msg.chat)
            bot.send_message(msg.chat.id, text, parse_mode="HTML")


@bot.message_handler(content_types=['left_chat_member'])
def on_left_member(msg):
    member = msg.left_chat_member
    if not member.is_bot:
        cd   = get_chat_data(msg.chat.id)
        text = format_welcome(cd["goodbye_msg"], member, msg.chat)
        bot.send_message(msg.chat.id, text, parse_mode="HTML")

# ═══════════════════════════════════════════════════
# 10. NOTES SYSTEM
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['save'])
def cmd_save(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split(None, 2)
    if len(args) < 3:
        bot.reply_to(msg, "⚠️ `/save notename content`", parse_mode="Markdown"); return
    name = args[1].lower()
    get_chat_data(msg.chat.id).setdefault("notes", {})[name] = args[2]
    save_memory(bot_memory)
    bot.reply_to(msg, f"📝 Note '<b>{name}</b>' save!", parse_mode="HTML")


@bot.message_handler(commands=['get'])
def cmd_get(msg):
    args = msg.text.split()
    if len(args) < 2:
        bot.reply_to(msg, "⚠️ `/get notename`", parse_mode="Markdown"); return
    name  = args[1].lower()
    notes = get_chat_data(msg.chat.id).get("notes", {})
    bot.reply_to(msg, notes.get(name, f"⚠️ '<b>{name}</b>' note नहीं मिला।"), parse_mode="HTML")


@bot.message_handler(commands=['notes'])
def cmd_notes(msg):
    notes = get_chat_data(msg.chat.id).get("notes", {})
    if not notes:
        bot.reply_to(msg, "📝 कोई notes नहीं।"); return
    lst = "\n".join(f"• <code>#{n}</code>" for n in notes)
    bot.reply_to(msg, f"📝 <b>Notes:</b>\n\n{lst}\n\n<i>/get &lt;name&gt; से पढ़ें</i>", parse_mode="HTML")


@bot.message_handler(commands=['clear'])
def cmd_clear(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split()
    if len(args) < 2:
        bot.reply_to(msg, "⚠️ `/clear notename`", parse_mode="Markdown"); return
    name  = args[1].lower()
    notes = get_chat_data(msg.chat.id).get("notes", {})
    if name in notes:
        del notes[name]
        save_memory(bot_memory)
        bot.reply_to(msg, f"🗑️ '<b>{name}</b>' delete।", parse_mode="HTML")
    else:
        bot.reply_to(msg, f"⚠️ '<b>{name}</b>' नहीं मिला।", parse_mode="HTML")


@bot.message_handler(commands=['clearall'])
def cmd_clearall(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    get_chat_data(msg.chat.id)["notes"] = {}
    save_memory(bot_memory)
    bot.reply_to(msg, "🗑️ सभी notes delete।")

# ═══════════════════════════════════════════════════
# 11. BLACKLIST SYSTEM
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['addblacklist'])
def cmd_addbl(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    word = msg.text.replace("/addblacklist", "", 1).strip().lower()
    if not word:
        bot.reply_to(msg, "⚠️ Word दो।"); return
    bl = get_chat_data(msg.chat.id).setdefault("blacklist", [])
    if word not in bl:
        bl.append(word)
        save_memory(bot_memory)
        bot.reply_to(msg, f"✅ '<b>{word}</b>' blacklist में add।", parse_mode="HTML")
    else:
        bot.reply_to(msg, "⚠️ Already blacklisted।")


@bot.message_handler(commands=['rmblacklist'])
def cmd_rmbl(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    word = msg.text.replace("/rmblacklist", "", 1).strip().lower()
    bl   = get_chat_data(msg.chat.id).get("blacklist", [])
    if word in bl:
        bl.remove(word)
        save_memory(bot_memory)
        bot.reply_to(msg, f"✅ '<b>{word}</b>' remove।", parse_mode="HTML")
    else:
        bot.reply_to(msg, "⚠️ Not in blacklist।")


@bot.message_handler(commands=['blacklist'])
def cmd_showbl(msg):
    cd  = get_chat_data(msg.chat.id)
    bl  = cd.get("blacklist", [])
    act = cd.get("blacklist_action", "warn")
    if not bl:
        bot.reply_to(msg, "🚫 Blacklist खाली है।"); return
    words = "\n".join(f"• <code>{w}</code>" for w in bl)
    bot.reply_to(msg, f"🚫 <b>Blacklist:</b>\n{words}\n\n<b>Action:</b> {act}", parse_mode="HTML")


@bot.message_handler(commands=['unblacklistall'])
def cmd_clearbl(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    get_chat_data(msg.chat.id)["blacklist"] = []
    save_memory(bot_memory)
    bot.reply_to(msg, "✅ Blacklist clear।")


@bot.message_handler(commands=['setblaction'])
def cmd_blaction(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split()
    if len(args) < 2 or args[1] not in ("warn", "ban", "kick", "mute"):
        bot.reply_to(msg, "⚠️ `/setblaction warn|ban|kick|mute`", parse_mode="Markdown"); return
    get_chat_data(msg.chat.id)["blacklist_action"] = args[1]
    save_memory(bot_memory)
    bot.reply_to(msg, f"✅ Blacklist action: <b>{args[1]}</b>", parse_mode="HTML")

# ═══════════════════════════════════════════════════
# 12. RULES SYSTEM
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['setrules'])
def cmd_setrules(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    text = msg.text.replace("/setrules", "", 1).strip()
    if not text:
        bot.reply_to(msg, "⚠️ Rules दो।"); return
    get_chat_data(msg.chat.id)["rules"] = text
    save_memory(bot_memory)
    bot.reply_to(msg, "✅ Rules set!")


@bot.message_handler(commands=['rules'])
def cmd_rules(msg):
    rules = get_chat_data(msg.chat.id).get("rules")
    if rules:
        bot.reply_to(msg, f"📜 <b>ग्रुप Rules:</b>\n\n{rules}", parse_mode="HTML")
    else:
        bot.reply_to(msg, "📜 Rules set नहीं हैं। Admin `/setrules` से set करे।", parse_mode="Markdown")


@bot.message_handler(commands=['resetrules'])
def cmd_resetrules(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    get_chat_data(msg.chat.id)["rules"] = None
    save_memory(bot_memory)
    bot.reply_to(msg, "✅ Rules reset।")

# ═══════════════════════════════════════════════════
# 13. PURGE / DELETE
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['purge'])
def cmd_purge(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    if not msg.reply_to_message:
        bot.reply_to(msg, "⚠️ जिस msg तक purge करना है उसे reply करो।"); return
    start_id = msg.reply_to_message.message_id
    end_id   = msg.message_id
    count    = 0
    for mid in range(start_id, end_id + 1):
        try:
            bot.delete_message(msg.chat.id, mid)
            count += 1
        except:
            pass
    n = bot.send_message(msg.chat.id, f"🗑️ {count} messages delete।")
    time.sleep(3)
    try:
        bot.delete_message(msg.chat.id, n.message_id)
    except:
        pass


@bot.message_handler(commands=['del'])
def cmd_del(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    if not msg.reply_to_message:
        bot.reply_to(msg, "⚠️ किसे delete करना है? Reply करो।"); return
    try:
        bot.delete_message(msg.chat.id, msg.reply_to_message.message_id)
        bot.delete_message(msg.chat.id, msg.message_id)
    except Exception as e:
        bot.reply_to(msg, f"❌ Delete failed: {e}")

# ═══════════════════════════════════════════════════
# 14. LOCK SYSTEM
# ═══════════════════════════════════════════════════
LOCK_TYPES = ["sticker", "gif", "url", "audio", "video", "document", "photo", "forward"]

@bot.message_handler(commands=['lock'])
def cmd_lock(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split()
    if len(args) < 2 or args[1] not in LOCK_TYPES:
        bot.reply_to(msg, f"⚠️ `/lock type`\nTypes: {', '.join(LOCK_TYPES)}", parse_mode="Markdown"); return
    get_chat_data(msg.chat.id).setdefault("locks", {})[args[1]] = True
    save_memory(bot_memory)
    bot.reply_to(msg, f"🔒 <b>{args[1]}</b> locked!", parse_mode="HTML")


@bot.message_handler(commands=['unlock'])
def cmd_unlock(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split()
    if len(args) < 2 or args[1] not in LOCK_TYPES:
        bot.reply_to(msg, f"⚠️ `/unlock type`", parse_mode="Markdown"); return
    get_chat_data(msg.chat.id).setdefault("locks", {})[args[1]] = False
    save_memory(bot_memory)
    bot.reply_to(msg, f"🔓 <b>{args[1]}</b> unlocked!", parse_mode="HTML")


@bot.message_handler(commands=['locks'])
def cmd_locks(msg):
    locks = get_chat_data(msg.chat.id).get("locks", {})
    lines = "\n".join(f"{'🔒' if locks.get(t) else '🔓'} {t}" for t in LOCK_TYPES)
    bot.reply_to(msg, f"<b>Lock Status:</b>\n{lines}", parse_mode="HTML")

# ═══════════════════════════════════════════════════
# 15. FLOOD CONTROL
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['setflood'])
def cmd_setflood(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split()
    if len(args) < 2:
        bot.reply_to(msg, "⚠️ `/setflood 5` या `/setflood off`", parse_mode="Markdown"); return
    v  = args[1].lower()
    cd = get_chat_data(msg.chat.id)
    if v == "off":
        cd["flood_limit"] = 0
        save_memory(bot_memory)
        bot.reply_to(msg, "✅ Flood control OFF।")
    elif v.isdigit() and 2 <= int(v) <= 20:
        cd["flood_limit"] = int(v)
        save_memory(bot_memory)
        bot.reply_to(msg, f"✅ Flood limit: <b>{v}</b> msgs", parse_mode="HTML")
    else:
        bot.reply_to(msg, "⚠️ 2–20 के बीच number या 'off' दो।")


@bot.message_handler(commands=['setfloodaction'])
def cmd_setfloodaction(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    args = msg.text.split()
    if len(args) < 2 or args[1] not in ("mute", "ban", "kick"):
        bot.reply_to(msg, "⚠️ `/setfloodaction mute|ban|kick`", parse_mode="Markdown"); return
    get_chat_data(msg.chat.id)["flood_action"] = args[1]
    save_memory(bot_memory)
    bot.reply_to(msg, f"✅ Flood action: <b>{args[1]}</b>", parse_mode="HTML")


def _check_flood(msg) -> bool:
    cd    = get_chat_data(msg.chat.id)
    limit = cd.get("flood_limit", 0)
    if limit == 0: return False
    key     = f"{msg.chat.id}_{msg.from_user.id}"
    tracker = flood_tracker[key]
    now     = time.time()
    if now - tracker["time"] > 10:
        tracker.update({"count": 1, "time": now})
        return False
    tracker["count"] += 1
    if tracker["count"] >= limit:
        tracker.update({"count": 0, "time": 0})
        return True
    return False


def _apply_flood(msg, cd):
    action = cd.get("flood_action", "mute")
    u = msg.from_user
    try:
        if action == "ban":
            bot.ban_chat_member(msg.chat.id, u.id)
            bot.send_message(msg.chat.id, f"🌊 Flood! {mention(u)} BAN।", parse_mode="HTML")
        elif action == "kick":
            bot.ban_chat_member(msg.chat.id, u.id)
            bot.unban_chat_member(msg.chat.id, u.id)
            bot.send_message(msg.chat.id, f"🌊 Flood! {mention(u)} KICK।", parse_mode="HTML")
        else:
            bot.restrict_chat_member(msg.chat.id, u.id, ChatPermissions(can_send_messages=False))
            bot.send_message(msg.chat.id, f"🌊 Flood! {mention(u)} MUTE।", parse_mode="HTML")
    except Exception as e:
        logger.error(f"Flood action failed: {e}")

# ═══════════════════════════════════════════════════
# 16. INFO COMMANDS
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['id'])
def cmd_id(msg):
    if msg.reply_to_message:
        u = msg.reply_to_message.from_user
        bot.reply_to(msg, f"👤 <b>{u.first_name}</b> ID: <code>{u.id}</code>", parse_mode="HTML")
    else:
        text = f"👤 <b>Your ID:</b> <code>{msg.from_user.id}</code>"
        if msg.chat.type != 'private':
            text += f"\n💬 <b>Chat ID:</b> <code>{msg.chat.id}</code>"
        bot.reply_to(msg, text, parse_mode="HTML")


@bot.message_handler(commands=['info'])
def cmd_info(msg):
    u   = (msg.reply_to_message.from_user if msg.reply_to_message else msg.from_user)
    cd  = get_chat_data(msg.chat.id)
    w   = cd.get("warns", {}).get(str(u.id), 0)
    lim = cd.get("warn_limit", 3)
    uname = f"@{u.username}" if u.username else "None"
    bot.reply_to(msg,
        f"👤 <b>User Info</b>\n\n"
        f"<b>Name:</b> {u.first_name} {u.last_name or ''}\n"
        f"<b>Username:</b> {uname}\n"
        f"<b>ID:</b> <code>{u.id}</code>\n"
        f"<b>Mention:</b> {mention(u)}\n"
        f"<b>Warns:</b> {w}/{lim}",
        parse_mode="HTML"
    )


@bot.message_handler(commands=['adminlist'])
def cmd_adminlist(msg):
    if msg.chat.type == 'private':
        bot.reply_to(msg, "⚠️ ग्रुप में use करें।"); return
    try:
        admins = bot.get_chat_administrators(msg.chat.id)
        lines  = "\n".join(
            f"{'👑' if a.status == 'creator' else '⭐'} "
            f"<a href='tg://user?id={a.user.id}'>{a.user.first_name}</a>"
            for a in admins if not a.user.is_bot
        )
        bot.reply_to(msg, f"👮 <b>Group Admins:</b>\n\n{lines}", parse_mode="HTML")
    except Exception as e:
        bot.reply_to(msg, f"❌ Admin list नहीं मिली: {e}")

# ═══════════════════════════════════════════════════
# 17. CUSTOM FILTERS
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['setreply'])
def cmd_setreply(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    text = msg.text.replace("/setreply", "", 1).strip()
    if "|" not in text:
        bot.reply_to(msg, "⚠️ `/setreply <trigger> | <reply>`", parse_mode="Markdown"); return
    kw, rep = text.split("|", 1)
    get_chat_data(msg.chat.id).setdefault("custom_replies", {})[kw.strip().lower()] = rep.strip()
    save_memory(bot_memory)
    bot.reply_to(msg, f"✅ Filter '<b>{kw.strip()}</b>' set!", parse_mode="HTML")


@bot.message_handler(commands=['delreply'])
def cmd_delreply(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    kw      = msg.text.replace("/delreply", "", 1).strip().lower()
    replies = get_chat_data(msg.chat.id).get("custom_replies", {})
    if kw in replies:
        del replies[kw]
        save_memory(bot_memory)
        bot.reply_to(msg, f"🗑️ Filter '<b>{kw}</b>' delete।", parse_mode="HTML")
    else:
        bot.reply_to(msg, "⚠️ Filter नहीं मिला।")


@bot.message_handler(commands=['listreplies'])
def cmd_listreplies(msg):
    replies = get_chat_data(msg.chat.id).get("custom_replies", {})
    if not replies:
        bot.reply_to(msg, "⚙️ कोई filters set नहीं।"); return
    lines = "\n".join(
        f"• <code>{k}</code> → {v[:30]}…" if len(v) > 30 else f"• <code>{k}</code> → {v}"
        for k, v in replies.items()
    )
    bot.reply_to(msg, f"⚙️ <b>Active Filters:</b>\n\n{lines}", parse_mode="HTML")

# ═══════════════════════════════════════════════════
# 18. FUN COMMANDS
# ═══════════════════════════════════════════════════
@bot.message_handler(commands=['quiz'])
def cmd_quiz(msg):
    if not is_admin(msg.chat.id, msg.from_user.id):
        bot.reply_to(msg, "⚠️ Admin-only।"); return
    bot.send_chat_action(msg.chat.id, 'typing')
    bot.reply_to(msg, "⏳ सवाल तैयार हो रहा है...")
    q = generate_ai_quiz()
    try:
        bot.send_poll(
            msg.chat.id,
            q["question"],
            q["options"],
            type="quiz",
            correct_option_id=q["correct_index"],
            is_anonymous=False
        )
    except Exception as e:
        bot.reply_to(msg, f"⚠️ Quiz error: {e}")


@bot.message_handler(commands=['roast'])
def cmd_roast(msg):
    target = get_target(msg) or msg.from_user
    bot.send_chat_action(msg.chat.id, 'typing')
    reply  = query_terex_ai(
        f"Roast {target.first_name} aggressively in Hinglish with gaali, savage humor. "
        "Make it brutal and funny."
    )
    bot.reply_to(msg, f"🔥 {mention(target)}:\n\n{reply}", parse_mode="HTML")


@bot.message_handler(commands=['joke'])
def cmd_joke(msg):
    bot.send_chat_action(msg.chat.id, 'typing')
    bot.reply_to(msg, f"😂 {query_terex_ai('एक मज़ेदार Hindi/Hinglish joke सुनाओ। Short और hilarious।')}")


@bot.message_handler(commands=['advice'])
def cmd_advice(msg):
    bot.send_chat_action(msg.chat.id, 'typing')
    bot.reply_to(msg, f"💡 {query_terex_ai('एक savage लेकिन useful life advice Hinglish में दो। Bold और direct।')}")


@bot.message_handler(commands=['ask'])
def cmd_ask(msg):
    question = msg.text.replace("/ask", "", 1).strip()
    if not question:
        bot.reply_to(msg, "⚠️ `/ask <question>`", parse_mode="Markdown"); return
    bot.send_chat_action(msg.chat.id, 'typing')
    bot.reply_to(msg, query_terex_ai(question))

# ═══════════════════════════════════════════════════
# 19. LOCK ENFORCEMENT HELPER
# ═══════════════════════════════════════════════════
def _enforce_locks(msg, cd) -> bool:
    """Delete locked content. Returns True if deleted."""
    if not is_bot_admin(msg.chat.id): return False
    if is_admin(msg.chat.id, msg.from_user.id): return False
    locks = cd.get("locks", {})

    ct = msg.content_type
    blocked = (
        (ct == 'sticker'   and locks.get("sticker")) or
        (ct == 'animation' and locks.get("gif")) or
        (ct == 'audio'     and locks.get("audio")) or
        (ct == 'video'     and locks.get("video")) or
        (ct == 'document'  and locks.get("document")) or
        (ct == 'photo'     and locks.get("photo")) or
        (msg.forward_date  and locks.get("forward")) or
        (ct == 'text' and locks.get("url") and
         bool(re.search(r'https?://\S+|www\.\S+', msg.text or '')))
    )
    if blocked:
        try:
            bot.delete_message(msg.chat.id, msg.message_id)
        except:
            pass
        try:
            n = bot.send_message(
                msg.chat.id,
                f"🔒 {mention(msg.from_user)}, यह content locked है।",
                parse_mode="HTML"
            )
            time.sleep(5)
            bot.delete_message(msg.chat.id, n.message_id)
        except:
            pass
        return True
    return False

# ═══════════════════════════════════════════════════
# 20. MAIN MESSAGE HANDLERS
# ═══════════════════════════════════════════════════
@bot.message_handler(content_types=['photo'])
def on_photo(msg):
    cd = get_chat_data(msg.chat.id)
    if _enforce_locks(msg, cd): return
    try:
        bot.send_chat_action(msg.chat.id, 'typing')
        fi     = bot.get_file(msg.photo[-1].file_id)
        data   = bot.download_file(fi.file_path)
        cap    = msg.caption or "इस तस्वीर में क्या है?"
        status = bot.reply_to(msg, "👀 देख रही हूँ...")
        result = query_vision_model(data, cap)
        bot.delete_message(msg.chat.id, status.message_id)
        bot.reply_to(msg, result)
    except Exception as e:
        logger.error(f"Photo handler: {e}")


@bot.message_handler(func=lambda m: True, content_types=['text'])
def on_text(msg):
    text = msg.text or ""
    tl   = text.lower()
    cid  = msg.chat.id
    cd   = get_chat_data(cid)

    # ── Lock check ──────────────────────────────────
    if _enforce_locks(msg, cd): return

    # ── Flood check ─────────────────────────────────
    if msg.chat.type != 'private' and not is_admin(cid, msg.from_user.id):
        if _check_flood(msg):
            _apply_flood(msg, cd)
            return

    # ── Blacklist check ──────────────────────────────
    if msg.chat.type != 'private' and not is_admin(cid, msg.from_user.id):
        bl = cd.get("blacklist", [])
        for word in bl:
            if word in tl:
                try:
                    bot.delete_message(cid, msg.message_id)
                except:
                    pass
                action = cd.get("blacklist_action", "warn")
                if action == "ban":
                    try: bot.ban_chat_member(cid, msg.from_user.id)
                    except: pass
                    bot.send_message(cid, f"🚫 {mention(msg.from_user)} BAN (blacklist)।", parse_mode="HTML")
                elif action == "kick":
                    try:
                        bot.ban_chat_member(cid, msg.from_user.id)
                        bot.unban_chat_member(cid, msg.from_user.id)
                    except: pass
                    bot.send_message(cid, f"🚫 {mention(msg.from_user)} KICK (blacklist)।", parse_mode="HTML")
                elif action == "mute":
                    try: bot.restrict_chat_member(cid, msg.from_user.id, ChatPermissions(can_send_messages=False))
                    except: pass
                    bot.send_message(cid, f"🚫 {mention(msg.from_user)} MUTE (blacklist)।", parse_mode="HTML")
                else:  # warn
                    warns = cd.setdefault("warns", {})
                    uid   = str(msg.from_user.id)
                    warns[uid] = warns.get(uid, 0) + 1
                    limit = cd.get("warn_limit", 3)
                    save_memory(bot_memory)
                    bot.send_message(
                        cid,
                        f"⚠️ {mention(msg.from_user)}, blacklisted word! Warn: {warns[uid]}/{limit}",
                        parse_mode="HTML"
                    )
                    if warns[uid] >= limit:
                        try: bot.ban_chat_member(cid, msg.from_user.id)
                        except: pass
                return

    # ── #note shortcut ───────────────────────────────
    if tl.startswith("#"):
        note_name = tl[1:].split()[0]
        note = cd.get("notes", {}).get(note_name)
        if note:
            bot.reply_to(msg, note, parse_mode="HTML")
            return

    # ── Custom filters ───────────────────────────────
    for kw, rep in cd.get("custom_replies", {}).items():
        if kw in tl:
            bot.reply_to(msg, rep)
            return

    # ── Smart reaction ───────────────────────────────
    emoji = smart_reaction(text)
    if emoji:
        try:
            bot.set_message_reaction(
                cid, msg.message_id,
                [ReactionTypeEmoji(emoji)],
                is_big=False
            )
        except:
            pass

    # ── Quick time command ───────────────────────────
    if any(k in tl for k in ("time", "samay", "baje", "टाइम", "समय")) and len(tl.split()) < 5:
        bot.reply_to(msg, f"⏰ अभी {datetime.now().strftime('%I:%M %p')} हुए हैं।")
        return

    # ── Open URL shortcut ────────────────────────────
    m = re.search(
        r"(open|kholo|खोलें|खोलो)\s+([a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)",
        text, re.IGNORECASE
    )
    if m:
        domain = m.group(2)
        url    = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
        bot.reply_to(msg, f"🔗 [{domain}]({url})", parse_mode="Markdown")
        return

    # ── AI reply (default) ───────────────────────────
    bot.send_chat_action(cid, 'typing')
    bot.reply_to(msg, query_terex_ai(text))

# ═══════════════════════════════════════════════════
# 21. FLASK & MAIN
# ═══════════════════════════════════════════════════
@app.route('/')
def home():
    return "🤖 TEREX Advanced Bot is LIVE — By Nitin Mourya"


def run_bot():
    logger.info("✅ TEREX Bot starting polling...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)


if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
