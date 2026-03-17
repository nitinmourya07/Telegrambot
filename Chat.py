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

# Initialize Flask (Required for Render to keep the service alive)
app = Flask(__name__)

# Initialize OpenAI Client (Using HuggingFace API as base_url)
client = OpenAI(
    base_url="https://router.huggingface.co/v1",
    api_key=HF_TOKEN
)

CHAT_MODEL = "deepseek-ai/DeepSeek-V3.2-Exp"
VISION_API_URL = "https://api-inference.huggingface.co/models/google/vit-base-patch16-224"

# Banned words for Chat Filter
BANNED_WORDS =["badword1", "badword2", "गाली", "अपशब्द", "scam"]

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# 2. Core AI Function (TEREX AI using OpenAI library)
def query_terex_ai(prompt: str) -> str:
    system_message = (
        "You are TEREX. Always start your response with a simple smiling emoji (like 😊), followed by a space. "
        "Always respond in Hindi using feminine grammar. Your answers must be concise (1-2 sentences). "
        "You were created by Nitin Mourya. If anyone asks who created you, who made you, or your father's name, "
        "you must proudly and specifically answer 'मुझे नितिन मौर्य (Nitin Mourya) ने बनाया है।'"
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
                return "😊 माफ़ कीजिये, मुझे कोई जवाब नहीं मिला।"
            return content

        except Exception as e:
            logger.error(f"Error in query_terex_ai (Attempt {attempt + 1}): {e}")
            if attempt == 2:
                return "😊 माफ़ कीजिये, AI ब्रेन से कनेक्ट करते समय नेटवर्क में कोई समस्या हुई।"
            time.sleep(3)

    return "😊 माफ़ कीजिये, AI ब्रेन से कनेक्ट करते समय एक अज्ञात त्रुटि हुई।"


# 3. Vision AI Function (Using Requests)
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
                description = "कोई वस्तु स्पष्ट रूप से पहचान में नहीं आई।"
                
            new_prompt = (
                f"A user sent an image with the caption '{caption}'. "
                f"My vision analysis says it contains: '{description}'. "
                f"Please respond to the user based on this."
            )
            return query_terex_ai(new_prompt)

        except Exception as e:
            logger.error(f"Error in query_vision_model (Attempt {attempt + 1}): {e}")
            if attempt == 2:
                return "😊 छवि को प्रोसेस करते समय नेटवर्क में कोई समस्या हुई।"
            time.sleep(5)

    return "😊 छवि को प्रोसेस करते समय कोई अज्ञात त्रुट-ि हुई।"


# 4. Special Commands (Time and URL generation)
def handle_special_commands(text: str):
    text_lower = text.lower()

    # Time Command
    time_keywords = ["time", "samay", "baje", "टाइम", "समय"]
    if any(kw in text_lower for kw in time_keywords):
        current_time = datetime.now().strftime("%I:%M %p")
        return f"😊 सर, अभी {current_time} हुए हैं।"

    # Open URL Command
    match = re.search(r"(open|kholo|खोलें|खोलो)\s+([a-zA-Z0-9-]+\.[a-zA-Z]{2,}(\.[a-zA-Z]{2,})?)", text, flags=re.IGNORECASE)
    if match:
        domain = match.group(2)
        url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
        return f"😊 ठीक है सर, यह रहा [{match.group(2)}]({url}) का लिंक।"

    return None


# 5. Telegram Handlers

@bot.message_handler(commands=['start'])
def start(message):
    user_name = message.from_user.first_name
    bot.reply_to(message, f"नमस्ते <b>{user_name}</b>! मैं <b>TEREX</b> हूँ, जिसे <b>नितिन मौर्य</b> ने बनाया है। मैं आपकी सहायता करने के लिए ऑनलाइन हूँ।", parse_mode="HTML")

@bot.message_handler(commands=['searchchannel'])
def search_channel(message):
    args = message.text.split()[1:]
    if not args:
        bot.reply_to(message, "😊 कृपया खोजने के लिए चैनल का नाम लिखें। जैसे: /searchchannel movies")
        return
    query = " ".join(args)
    url = f"https://www.google.com/search?q=site:t.me+intitle:%22{query}%22"
    bot.reply_to(message, f"😊 '{query}' से सम्बंधित चैनल्स यहाँ खोजें:\n[यहाँ क्लिक करें]({url})", parse_mode="Markdown")

@bot.message_handler(commands=['quiz'])
def start_quiz(message):
    questions =[
        {"question": "भारत की राजधानी क्या है?", "options":["मुंबई", "नई दिल्ली", "कोलकाता", "चेन्नई"], "correct": 1},
        {"question": "Python क्या है?", "options":["सांप", "प्रोग्रामिंग भाषा", "गेम", "ऑपरेटिंग सिस्टम"], "correct": 1},
        {"question": "TEREX बॉट को किसने बनाया है?", "options":["Nitin Mourya", "Elon Musk", "Mark Zuckerberg", "Sundar Pichai"], "correct": 0},
        {"question": "सूर्यमंडल का सबसे बड़ा ग्रह कौन सा है?", "options": ["पृथ्वी", "मंगल", "बृहस्पति", "शनि"], "correct": 2}
    ]
    q = random.choice(questions)
    bot.send_poll(
        chat_id=message.chat.id,
        question=q["question"],
        options=q["options"],
        type="quiz",
        correct_option_id=q["correct"]
    )

@bot.message_handler(content_types=['new_chat_members'])
def greet_new_members(message):
    for member in message.new_chat_members:
        if not member.is_bot:
            bot.reply_to(message, f"नमस्ते <b>{member.first_name}</b>, ग्रुप में आपका स्वागत है! 😊", parse_mode="HTML")

@bot.message_handler(content_types=['photo'])
def handle_image_message(message):
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        
        # Download highest resolution photo
        file_info = bot.get_file(message.photo[-1].file_id)
        image_bytes = bot.download_file(file_info.file_path)
        
        caption = message.caption if message.caption else "इस तस्वीर में क्या है?"
        status_msg = bot.reply_to(message, "😊 तस्वीर देख रही हूँ...")
        
        result_text = query_vision_model(image_bytes, caption)
        
        bot.delete_message(message.chat.id, status_msg.message_id)
        bot.reply_to(message, result_text)
        
    except Exception as e:
        logger.error(f"Error handling image message: {e}")
        bot.reply_to(message, "😊 तस्वीर को प्रोसेस करते समय एक अप्रत्याशित त्रुटि हुई।")

@bot.message_handler(func=lambda msg: True, content_types=['text'])
def handle_text_message(message):
    text = message.text
    text_lower = text.lower()
    
    # Chat Filter (Profanity check)
    if message.chat.type in ['group', 'supergroup']:
        if any(bad_word in text_lower for bad_word in BANNED_WORDS):
            try:
                bot.delete_message(message.chat.id, message.message_id)
                bot.send_message(message.chat.id, f"<b>{message.from_user.first_name}</b>, कृपया ग्रुप में अपशब्दों या स्पैम का प्रयोग न करें!", parse_mode="HTML")
                return
            except Exception as e:
                logger.error(f"Could not delete message for chat filter: {e}")

    # Message Reaction
    reaction_words =["love", "thanks", "धन्यवाद", "❤️", "😍", "nitin", "mourya", "terex", "creator"]
    reaction = "❤️" if any(word in text_lower for word in reaction_words) else "😊"
    try:
        bot.set_message_reaction(message.chat.id, message.message_id, [ReactionTypeEmoji(reaction)], is_big=False)
    except Exception as e:
        logger.error(f"Could not set reaction: {e}")

    # Special Commands Check (Time & Link Generation)
    special_response = handle_special_commands(text)
    if special_response is not None:
        parse_mode = "Markdown" if "का लिंक।" in special_response else None
        bot.reply_to(message, special_response, parse_mode=parse_mode)
        return

    # AI Reply Check
    bot.send_chat_action(message.chat.id, 'typing')
    ai_reply = query_terex_ai(text)
    bot.reply_to(message, ai_reply)


# 6. Web Server for Render & Bot Execution
@app.route('/')
def home():
    return "TEREX Bot is running fine on Render!"

def run_bot():
    logger.info("TEREX AI Bot is starting...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == "__main__":
    # Start bot polling in a separate background thread
    threading.Thread(target=run_bot, daemon=True).start()
    
    # Run Flask app on the port assigned by Render
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
