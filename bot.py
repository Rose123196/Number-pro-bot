import telebot
from telebot import types
import json
import os
import requests
import re
import pycountry
import random
import time

# ---------------- CONFIGURATION ---------------- #
BOT_TOKEN = "8785193678:AAGCYG4fepLijX7K8vc1D7Aw9HxVMeYJULI"
LOGO_PATH = "logo.png"

ADMIN_ID = 8927512671
AUTHORIZED_USERS = [str(8927512671)]

APIS_FILE = "apis.json"
USERS_FILE = "users.json"

REQUIRED_CHANNELS = [
    {"name": "@zeronumbars", "id": -1003999772745}
]

bot = telebot.TeleBot(BOT_TOKEN)

# ---------------- DATABASE & GLOBAL STATES ---------------- #
def safe_load_json(filename, default_val):
    if os.path.exists(filename):
        try:
            with open(filename, "r") as f:
                return json.load(f)
        except:
            return default_val
    return default_val

def safe_save_json(filename, data):
    with open(filename, "w") as f:
        json.dump(data, f, indent=4)

SERVER_CONFIG = safe_load_json(APIS_FILE, [])
total_users = set(safe_load_json(USERS_FILE, []))
KNOWN_COUNTRIES_FILE = "known_countries.json"
_known_countries_first_run = not os.path.exists(KNOWN_COUNTRIES_FILE)
known_countries = set(safe_load_json(KNOWN_COUNTRIES_FILE, []))

user_selections = {}
admin_temp_data = {}
user_last_msg = {}  # chat_id -> message_id

BOT_STATS = {
    "total_users": total_users,
    "numbers_fetched": 0,
    "otps_delivered": 0
}

# ---------------- MESSAGE TRACKER ---------------- #
def delete_last_msg(chat_id):
    if chat_id in user_last_msg:
        try:
            bot.delete_message(chat_id, user_last_msg[chat_id])
        except:
            pass
        del user_last_msg[chat_id]

def track_msg(chat_id, message_id):
    user_last_msg[chat_id] = message_id

# ---------------- DATABASE HISTORY ENGINE ---------------- #
def get_history_filename(server_idx):
    return f"history_server_{server_idx}.json"

def load_history(server_idx):
    filename = get_history_filename(server_idx)
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                return set(json.load(f))
        except:
            return set()
    return set()

def save_history(server_idx, history_set):
    filename = get_history_filename(server_idx)
    try:
        with open(filename, 'w') as f:
            json.dump(list(history_set), f)
    except Exception as e:
        print(f"❌ [DB Error] Could not save history: {e}")

def create_message_signature(number, message):
    return f"{str(number).strip()}|{str(message).strip()}"

def initialize_server_history():
    for idx, server in enumerate(SERVER_CONFIG):
        if not server.get("active", True): continue
        try:
            data, error = fetch_api_data(server['api_sms'])
            current_history = set()
            if data and "aaData" in data:
                for item in data['aaData']:
                    try:
                        first_col = str(item[0])
                        if "<input" in first_col or "checkbox" in first_col:
                            num, msg = str(item[3]), str(item[5])
                        else:
                            num, msg = str(item[2]), str(item[4])
                        if msg and len(msg) > 1:
                            current_history.add(create_message_signature(num, msg))
                    except:
                        continue
            save_history(idx, current_history)
        except:
            pass

def delete_server_history(server_idx):
    filename = get_history_filename(server_idx)
    if os.path.exists(filename):
        os.remove(filename)

# ---------------- UTILITY CORE FUNCTIONS ---------------- #
def fetch_api_data(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json(), None
        else:
            return None, f"⚠️ Error: {response.status_code}"
    except:
        return None, "TIMEOUT"

def get_flag_from_name(clean_name):
    try:
        search = pycountry.countries.search_fuzzy(clean_name)
        if search:
            code = search[0].alpha_2
            return "".join([chr(ord(c) + 127397) for c in code])
    except:
        pass
    return "🏳️"

def fast_clean_name(raw_name):
    """Clean country name — numbers/dates/junk filter karo"""
    if "<" in raw_name:
        raw_name = re.sub('<[^<]+?>', '', raw_name)
    for d in ["-", "_", "/"]:
        raw_name = raw_name.replace(d, " ")
    parts = raw_name.strip().split()
    if not parts:
        return ""
    # Sirf letters wala part nikalo — digits wale parts skip
    clean_parts = []
    for p in parts:
        letters_only = ''.join([c for c in p if c.isalpha()])
        if len(letters_only) >= 2:
            clean_parts.append(letters_only)
    if not clean_parts:
        return ""
    result = clean_parts[0]
    if len(result) < 3 and len(clean_parts) > 1:
        result = clean_parts[0] + " " + clean_parts[1]
    return result.strip()

def is_valid_country_name(name):
    """
    Junk/date/number wale names filter karo.
    Sirf wahi names allow karo jo real country names lagein.
    """
    if not name or len(name) < 2:
        return False
    # Agar pure digits hain ya mostly digits
    if re.match(r'^\d+$', name):
        return False
    # Agar NaN ya junk
    if "NAN" in name.upper() or "NULL" in name.upper() or "NONE" in name.upper():
        return False
    # Agar 4 digit year jaisa (2024, 2025, 2026...)
    if re.match(r'^20\d{2}', name):
        return False
    # Agar sirf numbers aur spaces
    if re.match(r'^[\d\s]+$', name):
        return False
    # Minimum 2 letters hone chahiye
    letters = re.sub(r'[^a-zA-Z]', '', name)
    if len(letters) < 2:
        return False
    return True

def check_subscription(user_id):
    """Saare required channels check — sab mein hona zaroori"""
    if not REQUIRED_CHANNELS:
        return True
    for channel in REQUIRED_CHANNELS:
        chat_ref = channel.get("name") or channel.get("id")
        if not chat_ref:
            continue
        try:
            status = bot.get_chat_member(chat_ref, user_id).status
            if status not in ['member', 'administrator', 'creator']:
                return False
        except Exception as e:
            print(f"[Sub Check Error] {e}")
            return True  # Bot admin nahi — bypass
    return True

def is_admin(user_id):
    return str(user_id) in AUTHORIZED_USERS

# ---------------- USER DASHBOARD ---------------- #
@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_id = message.from_user.id

    if chat_id not in BOT_STATS["total_users"]:
        BOT_STATS["total_users"].add(chat_id)
        safe_save_json(USERS_FILE, list(BOT_STATS["total_users"]))

    if not check_subscription(user_id):
        markup = types.InlineKeyboardMarkup(row_width=1)
        for channel in REQUIRED_CHANNELS:
            clean_username = channel['name'].replace('@', '')
            markup.add(types.InlineKeyboardButton(
                text=f"⚜️ Join {channel['name']}",
                url=f"https://t.me/{clean_username}"
            ))
        markup.add(types.InlineKeyboardButton(
            text="⚡ VERIFY & START ✅",
            callback_data="check_join"
        ))
        text = "⚠️ *Access Denied!*\n\nBot ko use karne ke liye aapko hamare official channels ko join karna lazmi hai. Join karke neeche button par click karein."
        delete_last_msg(chat_id)
        try:
            with open(LOGO_PATH, 'rb') as photo:
                sent = bot.send_photo(chat_id, photo, caption=text, parse_mode="Markdown", reply_markup=markup)
        except:
            sent = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        track_msg(chat_id, sent.message_id)
        return

    show_user_dashboard(message)


def show_user_dashboard(message):
    chat_id = message.chat.id if hasattr(message, 'chat') else message.from_user.id

    welcome_text = (
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
        "  🔥𝙙𝙚𝙫𝙚𝙡𝙤𝙥𝙚𝙧 𝙗𝙤𝙮 𝘼𝙡𝙞 𝙎𝙞𝙣𝙙𝙝𝙞🔥\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
        "  🤖 WELCOME TO MY BOT 🤖\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
        "🔥 UNLIMITED FREE NUMBERS CLIENT\n"
        "📊 Status: 🟢 Connected Live\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )

    active_servers = [s for s in SERVER_CONFIG if s.get("active", True)]
    if not active_servers:
        text_off = "❌ *System Offline:* Is waqt backend par koi active server ya stock on nahi hai."
        delete_last_msg(chat_id)
        sent = bot.send_message(chat_id, text_off, parse_mode="Markdown")
        track_msg(chat_id, sent.message_id)
        return

    delete_last_msg(chat_id)

    try:
        with open(LOGO_PATH, 'rb') as photo:
            sent = bot.send_photo(chat_id, photo, caption=welcome_text, parse_mode="Markdown")
    except:
        sent = bot.send_message(chat_id, welcome_text, parse_mode="Markdown")

    track_msg(chat_id, sent.message_id)
    get_countries_menu(sent, page=0)


# ---------------- COUNTRIES MENU — ALL SERVERS + PAGINATION ---------------- #
def get_countries_menu(message, page=0):
    chat_id = message.chat.id

    active_servers = [(i, s) for i, s in enumerate(SERVER_CONFIG) if s.get("active", True)]
    if not active_servers:
        bot.send_message(chat_id, "❌ Koi active server nahi hai.")
        return

    # Saare servers se countries collect — country_map = { clean_name: server_idx }
    country_map = {}
    for s_idx, server in active_servers:
        data, _ = fetch_api_data(server.get('api_numbers', ''))
        if not data or "aaData" not in data:
            continue
        for item in data['aaData']:
            try:
                first_col = str(item[0])
                raw_name = str(item[1]) if ("<input" in first_col or "checkbox" in first_col) else str(item[0])
                c_name = fast_clean_name(raw_name)
                # Junk/date filter
                if is_valid_country_name(c_name) and c_name not in country_map:
                    country_map[c_name] = s_idx
            except:
                continue

    if not country_map:
        bot.send_message(chat_id, "❌ Filhal koi country available nahi hai.")
        return

    # Naye countries detect karo (jo pehle kabhi nahi dekhe) aur users ko notify karo
    new_found = [c for c in country_map.keys() if c not in known_countries]
    if new_found:
        for c in new_found:
            known_countries.add(c)
            if not _known_countries_first_run:
                broadcast_new_country(c)
        safe_save_json(KNOWN_COUNTRIES_FILE, list(known_countries))
        globals()['_known_countries_first_run'] = False

    sorted_countries = sorted(country_map.keys())

    items_per_page = 10
    total_pages = (len(sorted_countries) + items_per_page - 1) // items_per_page
    page = max(0, min(page, total_pages - 1))
    start = page * items_per_page
    page_countries = sorted_countries[start:start + items_per_page]

    markup = types.InlineKeyboardMarkup(row_width=2)

    buttons = []
    for c in page_countries:
        flag = get_flag_from_name(c)
        s_idx = country_map[c]
        buttons.append(types.InlineKeyboardButton(
            f"{flag} {c}",
            callback_data=f"order_{s_idx}|{c}"
        ))

    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.row(buttons[i], buttons[i + 1])
        else:
            markup.row(buttons[i])

    nav = []
    if page > 0:
        nav.append(types.InlineKeyboardButton("⬅️ Back", callback_data=f"page_nav|{page - 1}"))
    nav.append(types.InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="ignore"))
    if page < total_pages - 1:
        nav.append(types.InlineKeyboardButton("Next ➡️", callback_data=f"page_nav|{page + 1}"))
    if nav:
        markup.row(*nav)

    if is_admin(chat_id):
        markup.add(types.InlineKeyboardButton("👑 Owner Control Panel", callback_data="open_owner_panel"))

    caption = (
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
        "  🔥𝙙𝙚𝙫𝙚𝙡𝙤𝙥𝙚𝙧 𝙗𝙤𝙮 𝘼𝙡𝙞 𝙎𝙞𝙣𝙙𝙝𝙞🔥\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
        "  🤖 WELCOME TO MY BOT 🤖\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
        "🔥 UNLIMITED FREE NUMBERS CLIENT\n"
        "📊 Status: 🟢 Connected Live\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🌍 *Select Country — Page {page + 1}/{total_pages}*"
    )

    try:
        bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message.message_id,
            caption=caption,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        track_msg(chat_id, message.message_id)
    except:
        delete_last_msg(chat_id)
        sent = bot.send_message(chat_id, caption, reply_markup=markup, parse_mode="Markdown")
        track_msg(chat_id, sent.message_id)


# ---------------- NUMBER SCREEN — SAME MESSAGE EDIT ---------------- #
def show_number_screen(message, chat_id, server_idx, sel_country, chosen1, chosen2):
    flag = get_flag_from_name(sel_country)

    markup = types.InlineKeyboardMarkup(row_width=1)

    markup.add(types.InlineKeyboardButton(
        f"🌍 {flag} {sel_country}",
        callback_data="ignore"
    ))

    markup.add(types.InlineKeyboardButton(
        "📱 Status: Online ✅",
        callback_data="ignore"
    ))

    markup.row(
        types.InlineKeyboardButton("📋 Copy", callback_data="copy_num_1"),
        types.InlineKeyboardButton(f"1️⃣ +{chosen1}", callback_data="copy_num_1")
    )

    markup.row(
        types.InlineKeyboardButton("📋 Copy", callback_data="copy_num_2"),
        types.InlineKeyboardButton(f"2️⃣ +{chosen2}", callback_data="copy_num_2")
    )

    markup.add(types.InlineKeyboardButton(
        "📨 GET OTP CODE 📥",
        callback_data="check_otp"
    ))

    markup.add(types.InlineKeyboardButton(
        "🔄 Change Number",
        callback_data=f"change_number_{server_idx}|{sel_country}"
    ))

    markup.add(types.InlineKeyboardButton(
        "🔙 Back to Dashboard",
        callback_data="main_menu"
    ))

    caption = (
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
        "  🔥𝙙𝙚𝙫𝙚𝙡𝙤𝙥𝙚𝙧 𝙗𝙤𝙮 𝘼𝙡𝙞 𝙎𝙞𝙣𝙙𝙝𝙞🔥\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
        "  🤖 WELCOME TO MY BOT 🤖\n"
        "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
        "🔥 UNLIMITED FREE NUMBERS CLIENT\n"
        "📊 Status: 🟢 Connected Live\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"1️⃣ `+{chosen1}`\n"
        f"2️⃣ `+{chosen2}`\n"
        "_(Tap the number above to copy)_\n\n"
    )

    try:
        bot.edit_message_caption(
            chat_id=chat_id,
            message_id=message.message_id,
            caption=caption,
            reply_markup=markup,
            parse_mode="Markdown"
        )
        track_msg(chat_id, message.message_id)

    except:
        delete_last_msg(chat_id)

        sent = bot.send_message(
            chat_id,
            caption,
            reply_markup=markup,
            parse_mode="Markdown"
        )

        track_msg(chat_id, sent.message_id)


# ---------------- GLOBAL CENTRAL CALLBACK CONTROLLER ---------------- #
@bot.callback_query_handler(func=lambda call: True)
def central_callback_router(call):
    chat_id = call.message.chat.id
    user_id = call.from_user.id

    # IGNORE
    if call.data == "ignore":
        bot.answer_callback_query(call.id)
        return

    if call.data == "copy_num_1":
        if user_id in user_selections:
            bot.answer_callback_query(
                call.id,
                text=f"+{user_selections[user_id]['num1']}",
                show_alert=True
            )
        return

    if call.data == "copy_num_2":
        if user_id in user_selections:
            bot.answer_callback_query(
                call.id,
                text=f"+{user_selections[user_id]['num2']}",
                show_alert=True
            )
        return

    # PAGINATION
    if call.data.startswith("page_nav|"):
        p_num = int(call.data.split("|")[1])
        bot.answer_callback_query(call.id)
        get_countries_menu(call.message, page=p_num)
        return

    # CHECK JOIN — channel verification
    if call.data == "check_join":
        if check_subscription(user_id):
            bot.answer_callback_query(call.id, "✅ Verified! Welcome 🎉", show_alert=True)
            delete_last_msg(chat_id)
            show_user_dashboard(call.message)
        else:
            bot.answer_callback_query(call.id, "❌ Pehle channel join karein!", show_alert=True)
        return

    # MAIN MENU
    if call.data == "main_menu":
        bot.answer_callback_query(call.id)
        show_user_dashboard(call.message)
        return

    # ADMIN ROUTING — forward to admin_callback (handles auth + dispatch)
    if call.data.startswith("admin_") or call.data == "open_owner_panel":
        admin_callback(call)
        return
    # ORDER / CHANGE NUMBER
    if call.data.startswith("order_") or call.data.startswith("change_number_"):
        bot.answer_callback_query(call.id, "⏳ Fetching...")
        prefix = "order_" if call.data.startswith("order_") else "change_number_"
        raw_payload = call.data.split(prefix)[1]
        parts = raw_payload.split("|")
        server_idx = int(parts[0])
        sel_country = parts[1]

        server = SERVER_CONFIG[server_idx]
        data, error = fetch_api_data(server['api_numbers'])

        if error or not data or "aaData" not in data:
            bot.answer_callback_query(call.id, "❌ Stock Error!", show_alert=True)
            return

        valid_nums = []
        for item in data['aaData']:
            try:
                first_col = str(item[0])
                raw, num = (str(item[1]), str(item[3])) if ("<input" in first_col or "checkbox" in first_col) else (str(item[0]), str(item[2]))
                c_name = fast_clean_name(raw)
                # Exact match — sel_country se compare
                if sel_country.lower() == c_name.lower():
                    valid_nums.append(num)
            except:
                continue

        if valid_nums:
            if len(valid_nums) >= 2:
                chosen1, chosen2 = random.sample(valid_nums, 2)
            else:
                chosen1 = valid_nums[0]
                chosen2 = valid_nums[0]

            BOT_STATS["numbers_fetched"] += 1

            user_selections[user_id] = {
                "server_idx": server_idx,
                "num": chosen1,
                "num1": chosen1,
                "num2": chosen2,
                "country": sel_country
            }

            show_number_screen(
                call.message,
                chat_id,
                server_idx,
                sel_country,
                chosen1,
                chosen2
            )
        else:
            bot.answer_callback_query(
                call.id,
                f"❌ {sel_country} Out of Stock!",
                show_alert=True
            )
        return

    # CHECK OTP
    if call.data == "check_otp":
        if user_id not in user_selections:
            return
        curr_num = user_selections[user_id]["num"]
        srv_idx = user_selections[user_id]["server_idx"]
        sel_country = user_selections[user_id]["country"]

        bot.answer_callback_query(call.id, "🔍 Searching OTP...")
        data, error = fetch_api_data(SERVER_CONFIG[srv_idx]["api_sms"])

        if error or not data or "aaData" not in data:
            bot.send_message(chat_id, "⚠️ Gateway timeout.")
            return

        history_set = load_history(srv_idx)
        found_otp = None
        for item in data['aaData']:
            try:
                num, msg = (str(item[3]), str(item[5])) if ("<input" in str(item[0]) or "checkbox" in str(item[0])) else (str(item[2]), str(item[4]))
                if "".join(filter(str.isdigit, str(num))) == "".join(filter(str.isdigit, str(curr_num))):
                    if create_message_signature(num, msg) not in history_set:
                        found_otp = msg
                        history_set.add(create_message_signature(num, msg))
                        break
            except:
                continue

        if found_otp:
            save_history(srv_idx, history_set)
            BOT_STATS["otps_delivered"] += 1

            # OTP popup alert
            bot.answer_callback_query(call.id, f"✅ OTP: {found_otp}", show_alert=True)

            markup = types.InlineKeyboardMarkup(row_width=1)
            markup.add(types.InlineKeyboardButton("🔙 Back to Dashboard", callback_data="main_menu"))

            otp_caption = (
                "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
                "  🔥𝙙𝙚𝙫𝙚𝙡𝙤𝙥𝙚𝙧 𝙗𝙤𝙮 𝘼𝙡𝙞 𝙎𝙞𝙣𝙙𝙝𝙞🔥\n"
                "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
                "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n"
                "  🤖 WELCOME TO MY BOT 🤖\n"
                "⚡━━━━━━━━━━━━━━━━━━━━━━━━⚡\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "✅ *SUCCESS: OTP RECEIVED*\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🔑 *OTP CODE:* `{found_otp}`\n"
                f"📱 *FOR NUMBER:* `+{curr_num}`\n\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n"
                "*Click the code above to copy.*"
            )

            try:
                bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    caption=otp_caption,
                    reply_markup=markup,
                    parse_mode="Markdown"
                )
                track_msg(chat_id, call.message.message_id)
            except:
                delete_last_msg(chat_id)
                sent = bot.send_message(chat_id, otp_caption, parse_mode="Markdown", reply_markup=markup)
                track_msg(chat_id, sent.message_id)
        else:
            bot.answer_callback_query(call.id, "📥 OTP abhi nahi aaya. Dobara try karein.", show_alert=False)
            bot.send_message(chat_id, "📥 Inbox khali hai. Thodi der mein phir try karein.")
        return

    # ADMIN ACCESS DENIED
    if call.data.startswith("admin_") or call.data == "open_owner_panel":
        if not is_admin(user_id):
            bot.answer_callback_query(call.id, "❌ Access Denied!", show_alert=True)
        return


# ----------------- ADMIN UI ROUTINES ----------------- #
def show_admin_menu_logic(chat_id, message_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton("➕ Add API", callback_data="admin_add_api"))
    markup.add(types.InlineKeyboardButton("📋 Manage APIs", callback_data="admin_list_apis"))
    markup.add(types.InlineKeyboardButton("📊 System Status", callback_data="admin_stats"))
    markup.add(types.InlineKeyboardButton("🔄 Sync Data", callback_data="admin_sync_history"))
    markup.add(types.InlineKeyboardButton("🔙 Close", callback_data="admin_close"))

    text = "🔒 *OWNER DASHBOARD*\nSelect an option below:"

    try:
        if message_id:
            bot.edit_message_caption(
                chat_id=chat_id, message_id=message_id,
                caption=text, parse_mode="Markdown", reply_markup=markup
            )
        else:
            with open(LOGO_PATH, 'rb') as photo:
                sent = bot.send_photo(chat_id, photo, caption=text, parse_mode="Markdown", reply_markup=markup)
                track_msg(chat_id, sent.message_id)
    except:
        sent = bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=markup)
        track_msg(chat_id, sent.message_id)


@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not is_admin(message.from_user.id): return
    show_admin_menu_logic(message.chat.id)


def show_statistics(chat_id, message_id=None):
    try:
        bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id,
            caption="⏳ *Calculating Data...*\n_Checking live APIs for total numbers._",
            parse_mode="Markdown"
        )
    except:
        pass

    total_users_count = len(BOT_STATS["total_users"])
    total_otps = BOT_STATS["otps_delivered"]
    server_stats = ""
    grand_total_numbers = 0

    for idx, server in enumerate(SERVER_CONFIG):
        status_icon = "🟢" if server.get("active", True) else "🔴"
        try:
            data, _ = fetch_api_data(server['api_numbers'])
            count = len(data['aaData']) if data and "aaData" in data else 0
        except:
            count = 0
        grand_total_numbers += count
        server_stats += f"📍 *{server['name']}:* `{count}` {status_icon}\n"

    stats_text = (
        "📊 *ADVANCED SYSTEM ANALYTICS*\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 *Total Users:* `{total_users_count}`\n\n"
        "💾 *Database Capacity (Live Numbers):*\n"
        f"{server_stats}"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📉 *Grand Total Numbers:* `{grand_total_numbers}`\n"
        f"📨 *Total OTPs Delivered:* `{total_otps}`\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🟢 *System Status:* Online & Running"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔄 Refresh Data", callback_data="admin_stats"))
    markup.add(types.InlineKeyboardButton("🔙 Owner Panel", callback_data="open_owner_panel"))

    try:
        bot.edit_message_caption(
            chat_id=chat_id, message_id=message_id,
            caption=stats_text, parse_mode="Markdown", reply_markup=markup
        )
    except:
        with open(LOGO_PATH, 'rb') as photo:
            bot.send_photo(chat_id, photo, caption=stats_text, parse_mode="Markdown", reply_markup=markup)


def show_admin_api_list(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    if not SERVER_CONFIG:
        markup.add(types.InlineKeyboardButton("➕ Add New API", callback_data="admin_add_api"))
        text = "📂 *No APIs Configured.*"
    else:
        for idx, server in enumerate(SERVER_CONFIG):
            status = "🟢" if server.get("active", True) else "🔴"
            markup.add(types.InlineKeyboardButton(
                f"{server['name']} {status}",
                callback_data=f"admin_view_server_{idx}"
            ))
        text = "📋 *Server Management*\nSelect a server to view details or edit:"

    markup.add(types.InlineKeyboardButton("🔙 Back", callback_data="open_owner_panel"))
    try:
        bot.edit_message_caption(
            chat_id=message.chat.id, message_id=message.message_id,
            caption=text, reply_markup=markup, parse_mode="Markdown"
        )
    except:
        bot.send_message(message.chat.id, text, reply_markup=markup, parse_mode="Markdown")


def view_single_server(message, idx):
    if idx >= len(SERVER_CONFIG):
        show_admin_api_list(message)
        return
    server = SERVER_CONFIG[idx]
    status_text = "Active ✅" if server.get("active", True) else "Disabled ❌"
    btn_text = "🛑 Stop Server" if server.get("active", True) else "▶️ Start Server"

    num_api_disp = server['api_numbers'][:100] + "📞"
    sms_api_disp = server['api_sms'][:100] + "💌"

    details = (
        f"⚙️ *Server Configuration: {idx + 1}*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ *Name:* `{server['name']}`\n"
        f"📡 *Status:* {status_text}\n\n"
        f"🔗 *Numbers API:*\n`{num_api_disp}`\n\n"
        f"🔗 *SMS API:*\n`{sms_api_disp}`\n"
        "━━━━━━━━━━━━━━━━━━"
    )
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(types.InlineKeyboardButton(btn_text, callback_data=f"admin_toggle_{idx}"))
    markup.add(types.InlineKeyboardButton("🗑️ Delete Server", callback_data=f"admin_delete_{idx}"))
    markup.add(types.InlineKeyboardButton("🔙 Back to List", callback_data="admin_list_apis"))

    try:
        bot.edit_message_caption(
            chat_id=message.chat.id, message_id=message.message_id,
            caption=details, parse_mode="Markdown", reply_markup=markup
        )
    except:
        bot.send_message(message.chat.id, details, parse_mode="Markdown", reply_markup=markup)


def process_auto_detect_apis(message):
    if message.text.lower() == 'cancel':
        bot.send_message(message.chat.id, "❌ Cancelled.")
        return
    raw = message.text.replace("\n", " ").split(" ")
    num_api, sms_api = None, None
    for link in raw:
        link = link.strip()
        if not link.startswith("http"):
            continue
        if "sms" in link or "type=sms" in link:
            sms_api = link
        elif "numbers" in link or "type=numbers" in link:
            num_api = link
        else:
            if num_api is None:
                num_api = link
            elif sms_api is None:
                sms_api = link

    if num_api and sms_api:
        admin_temp_data[message.from_user.id] = {'api_numbers': num_api, 'api_sms': sms_api}
        msg = bot.send_message(message.chat.id, "📝 *Enter Server Name:*", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_name_api)
    else:
        bot.send_message(
            message.chat.id,
            "❌ 2 links nahi mile.\nFormat: `Numbers_URL SMS_URL` (space se alag)",
            parse_mode="Markdown"
        )


def broadcast_new_country(country_name):
    flag = get_flag_from_name(country_name)
    text = (
        "━━━━━━━━━━━━━━━━\n"
        "New County add 🔥\n"
        "━━━━━━━━━━━━━━━━\n"
        f"{flag} {country_name}\n"
        "━━━━━━━━━━━━━━━━\n"
        "Enjoy ✅"
    )
    for uid in list(BOT_STATS["total_users"]):
        try:
            bot.send_message(uid, text)
        except Exception:
            pass


def process_name_api(message):
    user_id = message.from_user.id
    if user_id not in admin_temp_data: return
    new_server = {
        "name": message.text.strip(),
        "api_numbers": admin_temp_data[user_id]['api_numbers'],
        "api_sms": admin_temp_data[user_id]['api_sms'],
        "active": True
    }
    SERVER_CONFIG.append(new_server)
    safe_save_json(APIS_FILE, SERVER_CONFIG)
    del admin_temp_data[user_id]

    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("📋 Manage APIs", callback_data="admin_list_apis"))
    bot.send_message(
        message.chat.id,
        f"✅ *Server Added!*\n`{new_server['name']}` — Total: {len(SERVER_CONFIG)} servers",
        parse_mode="Markdown",
        reply_markup=markup
    )


# ----------------- ADMIN CALLBACK HANDLER ----------------- #
@bot.callback_query_handler(func=lambda call: call.data.startswith("admin_") or call.data == "open_owner_panel")
def admin_callback(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    if not is_admin(user_id):
        bot.answer_callback_query(call.id, "❌ Access Denied!", show_alert=True)
        return

    if call.data == "open_owner_panel":
        show_admin_menu_logic(chat_id, call.message.message_id)
    elif call.data == "admin_stats":
        show_statistics(chat_id, call.message.message_id)
    elif call.data == "admin_sync_history":
        bot.answer_callback_query(call.id, "🔄 Syncing...")
        initialize_server_history()
        bot.send_message(chat_id, "✅ Sync Complete!")
    elif call.data == "admin_list_apis":
        show_admin_api_list(call.message)
    elif call.data == "admin_close":
        show_user_dashboard(call.message)
    elif call.data == "admin_add_api":
        bot.answer_callback_query(call.id)
        msg = bot.send_message(
            chat_id,
            '📝 *Do links bhejo (space se alag):*\n`Numbers_URL SMS_URL`\n\nCancel ke liye `cancel` likho.',
            parse_mode="Markdown"
        )
        bot.register_next_step_handler(msg, process_auto_detect_apis)
    elif call.data.startswith("admin_view_server_"):
        idx = int(call.data.split("_")[3])
        view_single_server(call.message, idx)
    elif call.data.startswith("admin_toggle_"):
        idx = int(call.data.split("_")[2])
        if 0 <= idx < len(SERVER_CONFIG):
            SERVER_CONFIG[idx]["active"] = not SERVER_CONFIG[idx].get("active", True)
            safe_save_json(APIS_FILE, SERVER_CONFIG)
            bot.answer_callback_query(call.id, "✅ Status Updated!")
            view_single_server(call.message, idx)
    elif call.data.startswith("admin_delete_"):
        idx = int(call.data.split("_")[2])
        if 0 <= idx < len(SERVER_CONFIG):
            delete_server_history(idx)
            del SERVER_CONFIG[idx]
            safe_save_json(APIS_FILE, SERVER_CONFIG)
            bot.answer_callback_query(call.id, "🗑️ Deleted!")
            show_admin_api_list(call.message)


# ----------------- INITIATOR RUNTIME ----------------- #
if __name__ == "__main__":
    initialize_server_history()
    print("🚀 Fixed Split Delimiter Core Running Flawlessly...")
    bot.infinity_polling()
