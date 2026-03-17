import os
import re
import json
import time
import random
import logging
import requests
import threading
from datetime import datetime

import telebot
from telebot.types import ReactionTypeEmoji
from flask import Flask
from openai import OpenAI

# 1. Configuration and Setup
BOT_TOKEN = os.getenv("BOT_TOKEN")
HF_TOKEN = os.getenv("HF_TOKEN")

if not BOT_TOKEN or not HF_TOKEN:
    raise ValueError("BOT_TOKEN और HF_TOKEN environment variables में सेट होना अनिवार्य है!")

# Initialize Bot
bot = telebot.TeleBot(BOT_TOKEN)

# Initialize Flask (Required for Render)
app = Flask(__name__)

# Initialize OpenAI Client (Using HuggingFace API as base_url)
client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN
)

CHAT_MODEL = "deepseek-ai/DeepSeek-V3.2-Exp"
VISION_API_URL = "https://api-inference.huggingface.co/models/google/vit-base-patch16-224"

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- NEW: BOT MEMORY SYSTEM ---
MEMORY_FILE = "bot_memory.json"

def load_memory():
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading memory: {e}")
    return {}

def save_memory(data):
    try:
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
    except Exception as e:
        logger.error(f"Error saving memory: {e}")

bot_memory = load_memory()


# 2. Core AI Function (TEREX AI - Savage Persona)
def query_terex_ai(prompt: str) -> str:
    # Updated System Message for Hinglish Gaali & Roasting
    system_message = (
        "You are TEREX, an advanced, highly intelligent, and savage AI assistant. "
        "You were created by Nitin Mourya. Always respond using feminine grammar. "
        "Your personality is bold, unapologetic, and savage. "
        "If a user misbehaves, insults you, or if you are explicitly asked to roast someone, "
        "YOU HAVE FULL PERMISSION to use aggressive Hinglish slang, gaali (swear words), and savage roasting. "
        "Do not hold back if provoked. Be savage and use Hinglish gaali naturally. "
        "For normal helpful questions, start with a 😊 and be helpful but keep a slight savage attitude. "
        "If asked about your creator, answer proudly: 'मुझे नितिन मौर्य (Nitin Mourya) ने बनाया है।'"
    )

    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=CHAT_MODEL,
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ]
            )
            content = response.choices[0].message.content
            if not content:
                return "माफ़ कीजिये, मुझे कोई जवाब नहीं मिला।"
            return content
        except Exception as e:
            logger.error(f"Error in query_terex_ai (Attempt {attempt + 1}): {e}")
            if attempt == 2:
                return "नेटवर्क में कोई समस्या हुई है, बाद में ट्राई कर।"
            time.sleep(3)
    return "सर्वर में कोई दिक्कत है, दिमाग मत खा।"


# 3. Vision AI Function
def query_vision_model(image_bytes: bytes, caption: str) -> str:
    headers = {
        "Authorization": f"Bearer {HF_TOKEN}",
        "Content-Type": "application/octet-stream"
    }
    for attempt in range(3):
        try:
            response = requests.post(VISION_API_URL, headers=headers, data=image_bytes)
            response.raise_for_status()
            result = response.json()
            try:
                description = result[0]['label']
            except (IndexError, KeyError, TypeError):
                description = "कुछ समझ नहीं आ रहा है।"
                
            new_prompt = (
                f"A user sent an image with the caption '{caption}'. "
                f"My vision analysis says it contains: '{description}'. "
                f"Respond to the user based on this in a bold/savage Hinglish style."
            )
            return query_terex_ai(new_prompt)
        except Exception as e:
            logger.error(f"Error in query_vision_model (Attempt {attempt + 1}): {e}")
            if attempt == 2:
                return "छवि को प्रोसेस करते समय नेटवर्क प्रॉब्लम है।"
            time.sleep(5)
    return "फोटो प्रोसेस करने में एरर आ रहा है।"


# 4. Intelligent Quiz Generator (Powered by AI)
def generate_ai_quiz_question():
    prompt = """Generate a random, interesting multiple-choice trivia question in Hindi/Hinglish. 
    Topics can be Science, History, Tech, or General Knowledge.
    Return EXACTLY and ONLY a valid JSON object in this format (no markdown, no extra text):
    {"question": "प्रश्न यहाँ", "options":["विकल्प 1", "विकल्प 2", "विकल्प 3", "विकल्प 4"], "correct_index": 0}"""
    
    try:
        response = client.chat.completions.create(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        content = response.choices[0].message.content.strip()
        if content.startswith("```json"):
            content = content[7:-3].strip()
        elif content.startswith("```"):
            content = content[3:-3].strip()
            
        quiz_data = json.loads(content)
        return quiz_data
    except Exception as e:
        logger.error(f"AI Quiz Generation failed: {e}")
        return {
            "question": "इनमें से कौन सी प्रोग्रामिंग भाषा AI के लिए सबसे लोकप्रिय है?",
            "options": ["Java", "Python", "C++", "HTML"],
            "correct_index": 1
        }


# 5. Smart Reaction Logic
def get_smart_reaction(text: str):
    text = text.lower()
    reactions = {
        "❤️":["love", "thanks", "धन्यवाद", "शुक्रिया", "nitin", "mourya", "terex", "creator", "प्यार", "best"],
        "😂":["haha", "lol", "lmao", "funny", "मज़ाक", "हाहा", "hihi", "hehe", "😂"],
        "😢":["sad", "cry", "दुखी", "रोना", "उदाश", "😢", "😭", "hurt"],
        "😡":["angry", "hate", "गुस्सा", "बेकार", "😡", "🤬", "bad", "chutiya", "madarchod", "bhenchod", "bhosdike", "gali"],
        "🎉":["congratulations", "बधाई", "happy birthday", "party", "🎉", "🥳", "जीत"],
        "👍":["ok", "done", "yes", "हाँ", "ठीक", "सही", "👍", "agree"]
    }
    
    for emoji, keywords in reactions.items():
        if any(kw in text for kw in keywords):
            return emoji
    return None


# 6. Admin Check Helper
def is_user_admin(chat_id, user_id):
    if chat_id > 0: # Private chats are always "admin"
        return True
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ['administrator', 'creator']
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False


# 7. Telegram Handlers

@bot.message_handler(commands=['start'])
def start(message):
    user_name = message.from_user.first_name
    bot.reply_to(message, f"नमस्ते <b>{user_name}</b>! मैं <b>TEREX</b> हूँ। मुझे <b>नितिन मौर्य</b> ने बनाया है। तमीज़ से बात करना, वरना रोस्ट करने में टाइम नहीं लगाउंगी। 😎", parse_mode="HTML")

# --- NEW: CUSTOM MEMORY COMMANDS ---
@bot.message_handler(commands=['setreply'])
def set_reply(message):
    if not is_user_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⚠️ माफ़ कीजिये, केवल <b>ग्रुप एडमिन</b> ही कस्टम रिप्लाई सेट कर सकते हैं!", parse_mode="HTML")
        return
    
    text = message.text.replace("/setreply", "").strip()
    if "|" not in text:
        bot.reply_to(message, "⚠️ सही तरीका: `/setreply <trigger word> | <bot reply>`\nउदाहरण: `/setreply hello | Hii, kaisa hai bhai?`", parse_mode="Markdown")
        return
        
    keyword, reply = text.split("|", 1)
    keyword = keyword.strip().lower()
    reply = reply.strip()
    
    chat_id = str(message.chat.id)
    if chat_id not in bot_memory:
        bot_memory[chat_id] = {}
        
    bot_memory[chat_id][keyword] = reply
    save_memory(bot_memory)
    bot.reply_to(message, f"✅ रिप्लाई सेट हो गया!\nअब अगर कोई '{keyword}' बोलेगा, तो मैं अपना काम कर दूंगी। 😎")

@bot.message_handler(commands=['delreply'])
def del_reply(message):
    if not is_user_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⚠️ यह कमांड सिर्फ एडमिन्स के लिए है।", parse_mode="HTML")
        return
        
    keyword = message.text.replace("/delreply", "").strip().lower()
    chat_id = str(message.chat.id)
    
    if chat_id in bot_memory and keyword in bot_memory[chat_id]:
        del bot_memory[chat_id][keyword]
        save_memory(bot_memory)
        bot.reply_to(message, f"🗑️ '{keyword}' का रिप्लाई डिलीट कर दिया गया है।")
    else:
        bot.reply_to(message, "⚠️ यह शब्द मेरी मेमोरी में सेव नहीं है।")

@bot.message_handler(commands=['quiz'])
def start_quiz(message):
    if not is_user_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "⚠️ माफ़ कीजिये, केवल <b>ग्रुप एडमिन</b> ही क्विज़ शुरू कर सकते हैं!", parse_mode="HTML")
        return

    bot.send_chat_action(message.chat.id, 'typing')
    bot.reply_to(message, "⏳ एक नया और धांसू सवाल तैयार कर रही हूँ, थोड़ा रुको...")
    
    q_data = generate_ai_quiz_question()
    try:
        bot.send_poll(
            chat_id=message.chat.id,
            question=q_data["question"],
            options=q_data["options"],
            type="quiz",
            correct_option_id=q_data["correct_index"],
            is_anonymous=False 
        )
    except Exception as e:
        logger.error(f"Failed to send poll: {e}")
        bot.reply_to(message, "⚠️ क्विज़ बनाने में कोई तकनीकी समस्या आ गई।")

@bot.message_handler(content_types=['new_chat_members'])
def greet_new_members(message):
    for member in message.new_chat_members:
        if not member.is_bot:
            bot.reply_to(message, f"वेलकम <b>{member.first_name}</b>! ग्रुप में स्वागत है। तमीज़ से रहना। 😎", parse_mode="HTML")

@bot.message_handler(content_types=['photo'])
def handle_image_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        file_info = bot.get_file(message.photo[-1].file_id)
        image_bytes = bot.download_file(file_info.file_path)
        
        caption = message.caption if message.caption else "इस तस्वीर में क्या है?"
        status_msg = bot.reply_to(message, "👀 फोटो देख रही हूँ...")
        
        result_text = query_vision_model(image_bytes, caption)
        
        bot.delete_message(message.chat.id, status_msg.message_id)
        bot.reply_to(message, result_text)
    except Exception as e:
        logger.error(f"Error handling image message: {e}")
        bot.reply_to(message, "⚠️ फोटो प्रोसेस करते टाइम एरर आ गया।")

@bot.message_handler(func=lambda msg: True, content_types=['text'])
def handle_text_message(message):
    text = message.text
    text_lower = text.lower()
    chat_id_str = str(message.chat.id)

    # 1. Custom Memory Check (एडमिन द्वारा सेट किया गया रिप्लाई)
    if chat_id_str in bot_memory:
        for keyword, custom_reply in bot_memory[chat_id_str].items():
            if keyword in text_lower:
                bot.reply_to(message, custom_reply)
                return  # अगर कस्टम रिप्लाई मिल गया, तो AI को कॉल नहीं करेगा

    # 2. Smart Reactions
    reaction_emoji = get_smart_reaction(text)
    if reaction_emoji:
        try:
            bot.set_message_reaction(message.chat.id, message.message_id,[ReactionTypeEmoji(reaction_emoji)], is_big=False)
        except Exception as e:
            logger.error(f"Could not set reaction: {e}")

    # 3. Time Command Check
    time_keywords =["time", "samay", "baje", "टाइम", "समय"]
    if any(kw in text_lower for kw in time_keywords) and len(text_lower.split()) < 5:
        current_time = datetime.now().strftime("%I:%M %p")
        bot.reply_to(message, f"⏰ अभी {current_time} हुए हैं।")
        return

    # 4. Open URL Command Check
    match = re.search(r"(open|kholo|खोलें|खोलो)\s+([a-zA-Z0-9-]+\.[a-zA-Z]{2,}(\.[a-zA-Z]{2,})?)", text, flags=re.IGNORECASE)
    if match:
        domain = match.group(2)
        url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
        bot.reply_to(message, f"🔗 यह ले तेरा लिंक: [{match.group(2)}]({url})", parse_mode="Markdown")
        return

    # 5. AI Reply (Savage/Gaali Engine)
    bot.send_chat_action(message.chat.id, 'typing')
    ai_reply = query_terex_ai(text)
    bot.reply_to(message, ai_reply)


# 8. Web Server for Render & Bot Execution
@app.route('/')
def home():
    return "TEREX Advanced Savage Bot is running!"

def run_bot():
    logger.info("TEREX AI Bot is starting...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
