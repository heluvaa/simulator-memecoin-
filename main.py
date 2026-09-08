import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
import requests
import threading
import time
import logging
import os
from datetime import datetime

# ================= LOGGING (biar error kelihatan di Railway logs) =================
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
log = logging.getLogger("sniper-bot")

# Konfigurasi Token — WAJIB diset lewat environment variable, jangan hardcode di kode
API_TOKEN = os.environ.get("BOT_TOKEN")
if not API_TOKEN:
    raise RuntimeError(
        "BOT_TOKEN belum diset. Tambahkan environment variable BOT_TOKEN "
        "di Railway (tab Variables) dengan token dari @BotFather."
    )
bot = telebot.TeleBot(API_TOKEN)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "application/json",
}
REQUEST_TIMEOUT = 10

# Multi-User Database
users_db = {}

def get_user(chat_id, username="Unknown"):
    if chat_id not in users_db:
        users_db[chat_id] = {
            'username': username,
            'balance': 1000000.0,
            'tp_on': True,
            'sl_on': True,
            'tp_pct': 50.0,
            'sl_pct': 20.0,
            'scanner_on': False,
            'seen_scanner_tokens': set(),
            'positions': {},
            'history': []
        }
    return users_db[chat_id]

# Inisialisasi Menu Bawaan Telegram
bot.set_my_commands([
    BotCommand("/start", "Buka Menu Utama"),
    BotCommand("/pnl", "Cek Portofolio & Jual Beli"),
    BotCommand("/history", "Riwayat PnL"),
    BotCommand("/scanner", "Auto Scan Token Baru")
])

# ================= HTTP HELPERS (fix utama: header + timeout + logging) =================

def _get_json(url):
    try:
        res = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if res.status_code != 200:
            log.warning(f"GET {url} -> status {res.status_code}: {res.text[:200]}")
            return None
        return res.json()
    except Exception as e:
        log.warning(f"GET {url} failed: {e}")
        return None

def get_dexscreener_data(token_address):
    data = _get_json(f"https://api.dexscreener.com/latest/dex/tokens/{token_address}")
    if data and data.get('pairs'):
        return data['pairs'][0]
    return None

def get_boosted_tokens(limit=10):
    """Dipakai untuk Trending & Scanner (token yang baru di-boost / naik daun)."""
    data = _get_json("https://api.dexscreener.com/token-boosts/top/v1")
    if not isinstance(data, list):
        return []
    return data[:limit]

def format_num(num):
    if num >= 1_000_000_000: return f"${num/1_000_000_000:.2f}B"
    if num >= 1_000_000: return f"${num/1_000_000:.2f}M"
    if num >= 1_000: return f"${num/1_000:.2f}K"
    return f"${num:.4f}"

def get_realtime_metrics_text(data):
    if not data: return "⚠️ Data real-time tidak tersedia."
    price = float(data.get('priceUsd', 0))
    change_5m = data.get('priceChange', {}).get('m5', 0)
    fdv = data.get('fdv', 0)
    vol = data.get('volume', {}).get('h24', 0)
    return f"💵 Price: `${price:.6f}` | 📈 5m: `{change_5m}%`\n💰 FDV: `{format_num(fdv)}` | 📊 Vol 24h: `{format_num(vol)}`"

# ================= PAGINATION & PNL LAYOUT =================

def render_pnl_page(user, page, sort_by="recent"):
    items_per_page = 2
    positions = list(user['positions'].items())

    if not positions:
        return "📭 Portofolio kosong. Paste CA untuk membeli koin.", None

    if sort_by == "profit":
        def get_pnl_pct(item):
            addr, pos = item
            data = get_dexscreener_data(addr)
            cp = float(data.get('priceUsd', 0)) if data else pos['entry_usd']
            return ((cp - pos['entry_usd']) / pos['entry_usd']) * 100 if pos['entry_usd'] > 0 else 0
        positions.sort(key=get_pnl_pct, reverse=True)
    else:
        positions.sort(key=lambda x: x[1]['time'], reverse=True)

    total_pages = (len(positions) + items_per_page - 1) // items_per_page
    start_idx = page * items_per_page
    page_items = positions[start_idx:start_idx + items_per_page]

    text = f"💼 **PRO PORTFOLIO (Hal {page+1}/{total_pages})**\n"
    text += f"Mode Sortir: *{sort_by.upper()}*\n\n"
    markup = InlineKeyboardMarkup()

    markup.row(
        InlineKeyboardButton("🕒 Sort by Recent", callback_data=f"pnlpage_0_recent"),
        InlineKeyboardButton("📈 Sort by Profit", callback_data=f"pnlpage_0_profit")
    )

    for address, pos in page_items:
        data = get_dexscreener_data(address)
        cur_price = float(data.get('priceUsd', 0)) if data else pos['entry_usd']
        mc = data.get('fdv', 0) if data else 0
        pnl_pct = ((cur_price - pos['entry_usd']) / pos['entry_usd']) * 100
        cur_val = pos['tokens'] * cur_price
        net_profit = cur_val - pos['invested']
        emoji = "🟩" if pnl_pct > 0 else "🟥"

        text += f"🌐 **{pos['chain']} | ${pos['symbol']}**\n"
        text += f"💵 Price: `${cur_price:.6f}` | 💰 MC: `{format_num(mc)}`\n"
        text += f"🎯 Avg Entry: `${pos['entry_usd']:.6f}`\n"
        text += f"🪙 Balance: `{pos['tokens']:,.0f} {pos['symbol']}`\n"
        text += f"📥 Buys (Modal): `${pos['invested']:.2f}`\n"
        text += f"📊 PnL: {emoji} `{pnl_pct:+.2f}%` (`{net_profit:+.2f} USDC`)\n\n"

        markup.row(
            InlineKeyboardButton("➕ Buy $100", callback_data=f"dca_100_{address}_{page}_{sort_by}"),
            InlineKeyboardButton("➕ Custom Buy", callback_data=f"buycustom_{address}_{page}_{sort_by}")
        )
        markup.row(
            InlineKeyboardButton("25% Sell", callback_data=f"sell_25_{address}_{page}_{sort_by}"),
            InlineKeyboardButton("50% Sell", callback_data=f"sell_50_{address}_{page}_{sort_by}"),
            InlineKeyboardButton("100% Sell", callback_data=f"sell_100_{address}_{page}_{sort_by}")
        )

    nav_buttons = []
    if page > 0: nav_buttons.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"pnlpage_{page - 1}_{sort_by}"))
    if page < total_pages - 1: nav_buttons.append(InlineKeyboardButton("Next ➡️", callback_data=f"pnlpage_{page + 1}_{sort_by}"))
    if nav_buttons: markup.row(*nav_buttons)

    return text, markup

def render_main_menu(user):
    text = f"🎯 **TRENCH SIMULATOR**\n\nSaldo USDC: `{format_num(user['balance'])}`\nPaste Contract Address (CA) ke chat untuk memulai.\n"
    markup = InlineKeyboardMarkup()
    scanner_label = "📡 Scanner: ON ✅" if user['scanner_on'] else "📡 Scanner: OFF"
    markup.row(InlineKeyboardButton("💼 Portofolio / PnL", callback_data="menu_pnl"), InlineKeyboardButton("📜 History", callback_data="menu_history"))
    markup.row(InlineKeyboardButton(scanner_label, callback_data="toggle_scanner"), InlineKeyboardButton("🔥 Top 10 Trending", callback_data="menu_trending"))
    markup.row(InlineKeyboardButton("🏆 Leaderboard", callback_data="menu_leaderboard"), InlineKeyboardButton("📖 Cara Pakai", callback_data="help_usage"))
    markup.row(InlineKeyboardButton(f"⚙️ Auto TP ({user['tp_pct']}%)", callback_data="menu_settp"), InlineKeyboardButton(f"⚙️ Auto SL ({user['sl_pct']}%)", callback_data="menu_setsl"))
    return text, markup

# ================= COMMANDS =================

@bot.message_handler(commands=['start', 'help'])
def start_menu(message):
    user = get_user(message.chat.id, message.from_user.username)
    text, markup = render_main_menu(user)
    bot.reply_to(message, text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['pnl'])
def cmd_pnl(message):
    user = get_user(message.chat.id)
    text, markup = render_pnl_page(user, 0, "recent")
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(commands=['scanner'])
def cmd_scanner(message):
    user = get_user(message.chat.id)
    user['scanner_on'] = not user['scanner_on']
    status = "AKTIF ✅" if user['scanner_on'] else "NONAKTIF ❌"
    bot.reply_to(message, f"📡 Scanner sekarang: **{status}**", parse_mode='Markdown')

@bot.message_handler(commands=['history'])
def cmd_history(message):
    user = get_user(message.chat.id)
    if not user['history']:
        bot.reply_to(message, "📭 Riwayat kosong.")
        return
    wins = len([t for t in user['history'] if t['net'] > 0])
    wr = (wins / len(user['history'])) * 100
    text = f"📜 **HISTORY TERAKHIR** (WR: {wr:.1f}%)\n\n"
    for t in list(reversed(user['history']))[:10]:
        text += f"{t['status']} **${t['symbol']}** | `{t['pct']:+.2f}%` | 💵 `{t['net']:+.2f}`\n"
    bot.reply_to(message, text, parse_mode='Markdown')

# ================= DIRECT CA PARSER =================

@bot.message_handler(func=lambda m: m.text and not m.text.startswith('/'))
def handle_direct_ca(message):
    text = message.text.strip()
    if len(text) > 30 and " " not in text:
        bot.send_chat_action(message.chat.id, 'typing')
        data = get_dexscreener_data(text)

        if not data:
            bot.reply_to(message, "❌ CA tidak valid, likuiditas kosong, atau Dexscreener sedang tidak merespons. Coba lagi beberapa saat.")
            return

        price = float(data.get('priceUsd', 0))
        fdv = data.get('fdv', 0)
        liquidity = data.get('liquidity', {}).get('usd', 0)
        symbol = data.get('baseToken', {}).get('symbol', 'UNKNOWN')
        chain = data.get('chainId', 'UNKNOWN').upper()

        msg = f"🔍 **SCAN: {chain} | ${symbol}**\n\n"
        msg += f"💵 Price: `${price:.6f}`\n💰 Market Cap: `{format_num(fdv)}`\n💧 Liquidity: `{format_num(liquidity)}`\n\n"
        msg += f"Pilih nominal Buy (USDC):"

        markup = InlineKeyboardMarkup()
        markup.row(InlineKeyboardButton("Buy $10", callback_data=f"buy_10_{text}"), InlineKeyboardButton("Buy $50", callback_data=f"buy_50_{text}"))
        markup.row(InlineKeyboardButton("Buy $100", callback_data=f"buy_100_{text}"), InlineKeyboardButton("Buy $500", callback_data=f"buy_500_{text}"))
        markup.row(InlineKeyboardButton("✏️ Custom Buy", callback_data=f"buycustom_new_{text}"))
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=markup)

# ================= CUSTOM BUY INPUT =================

def process_custom_buy(message, address, page=0, sort_by="recent", is_dca=False):
    user = get_user(message.chat.id)
    try:
        amount = float(message.text)
        if amount <= 0: raise ValueError
    except:
        bot.reply_to(message, "❌ Nominal tidak valid. Transaksi dibatalkan.")
        return

    if user['balance'] < amount:
        bot.reply_to(message, f"❌ Saldo tidak cukup! Sisa: {user['balance']:.2f}")
        return

    data = get_dexscreener_data(address)
    price = float(data.get('priceUsd', 0)) if data else 1.0
    symbol = data.get('baseToken', {}).get('symbol', 'UNKNOWN') if data else "TOKEN"
    chain = data.get('chainId', 'UNKNOWN').upper() if data else "UNKNOWN"
    tokens_bought = amount / price

    msg = f"✅ **BUY FILLED (${amount:.2f})**\n\n"
    msg += f"🏷 **${symbol}** ({chain})\n"
    msg += get_realtime_metrics_text(data) + "\n"

    if address in user['positions']:
        pos = user['positions'][address]
        new_inv = pos['invested'] + amount
        new_tok = pos['tokens'] + tokens_bought
        user['positions'][address].update({'invested': new_inv, 'tokens': new_tok, 'entry_usd': new_inv / new_tok})
        msg += f"\n🪙 Balance Terbaru: `{new_tok:,.0f} {symbol}`"
        bot.reply_to(message, msg, parse_mode='Markdown')
        if is_dca:
            text, markup = render_pnl_page(user, page, sort_by)
            bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)
    else:
        user['positions'][address] = {'symbol': symbol, 'chain': chain, 'entry_usd': price, 'invested': amount, 'tokens': tokens_bought, 'time': datetime.now()}
        msg += f"\n🪙 Balance: `{tokens_bought:,.0f} {symbol}`"
        bot.reply_to(message, msg, parse_mode='Markdown')

    user['balance'] -= amount

# ================= SELL LOGIC (dipakai manual & auto TP/SL) =================

def execute_sell(chat_id, user, address, sell_pct, notify=True):
    if address not in user['positions']:
        return None
    pos = user['positions'][address]
    token_data = get_dexscreener_data(address)
    cur_price = float(token_data.get('priceUsd', 0)) if token_data else pos['entry_usd']

    frac = sell_pct / 100.0
    t_sell, i_sell = pos['tokens'] * frac, pos['invested'] * frac
    profit = (t_sell * cur_price) - i_sell
    pnl_pct = (profit / i_sell) * 100 if i_sell else 0
    emoji = "🟩" if profit > 0 else "🟥"

    user['balance'] += (t_sell * cur_price)
    user['history'].append({'symbol': pos['symbol'], 'status': emoji, 'pct': pnl_pct, 'net': profit, 'date': datetime.now().strftime('%d-%m-%Y')})

    msg = f"🔔 **SELL {sell_pct}% FILLED**\n\n🏷 **${pos['symbol']}**\n"
    msg += get_realtime_metrics_text(token_data) + "\n\n"
    msg += f"📊 Profit/Loss: {emoji} `{pnl_pct:+.2f}%` (`{profit:+.2f} USDC`)\n"

    if sell_pct == 100 or pos['tokens'] - t_sell <= 0.000001:
        del user['positions'][address]
        msg += f"🪙 Sisa Balance: `0 {pos['symbol']}`"
    else:
        pos['tokens'] -= t_sell
        pos['invested'] -= i_sell
        msg += f"🪙 Sisa Balance: `{pos['tokens']:,.0f} {pos['symbol']}`"

    if notify:
        bot.send_message(chat_id, msg, parse_mode='Markdown')
    return pnl_pct

# ================= CALLBACKS =================

@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    user = get_user(call.message.chat.id, call.from_user.username)
    data = call.data

    try:
        if data == "menu_pnl":
            text, markup = render_pnl_page(user, 0, "recent")
            bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

        elif data == "menu_history":
            if not user['history']:
                bot.answer_callback_query(call.id, "📭 Riwayat kosong.", show_alert=True)
                return
            wins = len([t for t in user['history'] if t['net'] > 0])
            wr = (wins / len(user['history'])) * 100
            text = f"📜 **HISTORY TERAKHIR** (WR: {wr:.1f}%)\n\n"
            for t in list(reversed(user['history']))[:10]:
                text += f"{t['status']} **${t['symbol']}** | `{t['pct']:+.2f}%` | 💵 `{t['net']:+.2f}`\n"
            bot.send_message(call.message.chat.id, text, parse_mode='Markdown')

        elif data == "help_usage":
            text = ("📖 **Cara Pakai**\n\n"
                    "1️⃣ Paste Contract Address (CA) langsung ke chat untuk lihat harga & beli.\n"
                    "2️⃣ Gunakan /pnl untuk lihat & kelola posisi terbuka.\n"
                    "3️⃣ Aktifkan Scanner untuk dapat notifikasi token baru otomatis.\n"
                    "4️⃣ Atur Auto TP/SL supaya posisi otomatis terjual saat target tercapai.")
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, text, parse_mode='Markdown')

        elif data == "toggle_scanner":
            user['scanner_on'] = not user['scanner_on']
            status = "AKTIF ✅" if user['scanner_on'] else "NONAKTIF ❌"
            bot.answer_callback_query(call.id, f"Scanner {status}")
            text, markup = render_main_menu(user)
            try:
                bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
            except Exception:
                bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

        elif data == "menu_trending":
            bot.answer_callback_query(call.id)
            bot.send_chat_action(call.message.chat.id, 'typing')
            boosted = get_boosted_tokens(10)
            if not boosted:
                bot.send_message(call.message.chat.id, "⚠️ Gagal mengambil data trending dari Dexscreener. Coba lagi sebentar lagi.")
                return
            text = "🔥 **TOP 10 TRENDING (Boosted)**\n\n"
            markup = InlineKeyboardMarkup()
            for item in boosted:
                addr = item.get('tokenAddress', '')
                chain = item.get('chainId', 'unknown').upper()
                pdata = get_dexscreener_data(addr) if addr else None
                symbol = pdata.get('baseToken', {}).get('symbol', '???') if pdata else '???'
                price = float(pdata.get('priceUsd', 0)) if pdata else 0
                text += f"🌐 {chain} | **${symbol}**\n💵 `${price:.6f}`\n`{addr}`\n\n"
                if addr:
                    markup.add(InlineKeyboardButton(f"Buy ${symbol}", callback_data=f"buy_50_{addr}"))
            bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

        elif data == "menu_leaderboard":
            bot.answer_callback_query(call.id)
            ranking = []
            for uid, u in users_db.items():
                total_net = sum(t['net'] for t in u['history'])
                if u['history']:
                    ranking.append((u.get('username') or str(uid), total_net, len(u['history'])))
            if not ranking:
                bot.send_message(call.message.chat.id, "🏆 Belum ada transaksi tercatat dari user manapun.")
                return
            ranking.sort(key=lambda x: x[1], reverse=True)
            text = "🏆 **LEADERBOARD (Realized PnL)**\n\n"
            for i, (uname, net, trades) in enumerate(ranking[:10], start=1):
                text += f"{i}. @{uname} — `{net:+.2f} USDC` ({trades} trades)\n"
            bot.send_message(call.message.chat.id, text, parse_mode='Markdown')

        elif data == "menu_settp":
            markup = InlineKeyboardMarkup()
            markup.row(*[InlineKeyboardButton(f"{p}%", callback_data=f"settp_{p}") for p in [25, 50, 75, 100, 200]])
            markup.row(InlineKeyboardButton("❌ Matikan Auto TP" if user['tp_on'] else "✅ Nyalakan Auto TP", callback_data="toggletp"))
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, f"⚙️ **Auto Take Profit**\nSaat ini: {user['tp_pct']}% ({'ON' if user['tp_on'] else 'OFF'})\nPilih target baru:", parse_mode='Markdown', reply_markup=markup)

        elif data == "menu_setsl":
            markup = InlineKeyboardMarkup()
            markup.row(*[InlineKeyboardButton(f"{p}%", callback_data=f"setsl_{p}") for p in [10, 20, 30, 50, 70]])
            markup.row(InlineKeyboardButton("❌ Matikan Auto SL" if user['sl_on'] else "✅ Nyalakan Auto SL", callback_data="togglesl"))
            bot.answer_callback_query(call.id)
            bot.send_message(call.message.chat.id, f"⚙️ **Auto Stop Loss**\nSaat ini: {user['sl_pct']}% ({'ON' if user['sl_on'] else 'OFF'})\nPilih batas baru:", parse_mode='Markdown', reply_markup=markup)

        elif data.startswith("settp_"):
            user['tp_pct'] = float(data.split('_')[1])
            bot.answer_callback_query(call.id, f"✅ Auto TP diatur ke {user['tp_pct']}%")

        elif data.startswith("setsl_"):
            user['sl_pct'] = float(data.split('_')[1])
            bot.answer_callback_query(call.id, f"✅ Auto SL diatur ke {user['sl_pct']}%")

        elif data == "toggletp":
            user['tp_on'] = not user['tp_on']
            bot.answer_callback_query(call.id, f"Auto TP {'AKTIF ✅' if user['tp_on'] else 'NONAKTIF ❌'}")

        elif data == "togglesl":
            user['sl_on'] = not user['sl_on']
            bot.answer_callback_query(call.id, f"Auto SL {'AKTIF ✅' if user['sl_on'] else 'NONAKTIF ❌'}")

        elif data.startswith("buycustom_"):
            parts = data.split('_')
            context = parts[1]
            bot.answer_callback_query(call.id)
            if context == "new":
                msg = bot.send_message(call.message.chat.id, "✏️ **Custom Buy:**\nKirimkan nominal USDC (contoh: `150`):", parse_mode='Markdown')
                bot.register_next_step_handler(msg, process_custom_buy, parts[2], 0, "recent", False)
            else:
                msg = bot.send_message(call.message.chat.id, "✏️ **Custom DCA:**\nKirimkan tambahan nominal USDC:", parse_mode='Markdown')
                bot.register_next_step_handler(msg, process_custom_buy, parts[1], int(parts[2]), parts[3], True)

        elif data.startswith("pnlpage_"):
            parts = data.split('_')
            text, markup = render_pnl_page(user, int(parts[1]), parts[2] if len(parts) > 2 else "recent")
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

        elif data.startswith("buy_") or data.startswith("dca_"):
            parts = data.split('_')
            amount, address = float(parts[1]), parts[2]

            if user['balance'] < amount:
                bot.answer_callback_query(call.id, "❌ Saldo tidak cukup!", show_alert=True)
                return

            token_data = get_dexscreener_data(address)
            price = float(token_data.get('priceUsd', 0)) if token_data else 1.0
            symbol = token_data.get('baseToken', {}).get('symbol', 'UNKNOWN') if token_data else "TOKEN"
            chain = token_data.get('chainId', 'UNKNOWN') if token_data else "UNKNOWN"
            tokens_bought = amount / price

            msg = f"✅ **BUY FILLED (${amount:.2f})**\n\n🏷 **${symbol}** ({chain})\n"
            msg += get_realtime_metrics_text(token_data) + "\n"

            if address in user['positions']:
                pos = user['positions'][address]
                new_inv = pos['invested'] + amount
                new_tok = pos['tokens'] + tokens_bought
                user['positions'][address].update({'invested': new_inv, 'tokens': new_tok, 'entry_usd': new_inv / new_tok})
                msg += f"\n🪙 Balance Terbaru: `{new_tok:,.0f} {symbol}`"
                bot.send_message(call.message.chat.id, msg, parse_mode='Markdown')
                if data.startswith("dca_"):
                    text, markup = render_pnl_page(user, int(parts[3]), parts[4])
                    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
            else:
                user['positions'][address] = {'symbol': symbol, 'chain': chain, 'entry_usd': price, 'invested': amount, 'tokens': tokens_bought, 'time': datetime.now()}
                msg += f"\n🪙 Balance: `{tokens_bought:,.0f} {symbol}`"
                bot.edit_message_text(msg, call.message.chat.id, call.message.message_id, parse_mode='Markdown')

            user['balance'] -= amount

        elif data.startswith("sell_"):
            parts = data.split('_')
            sell_pct, address = int(parts[1]), parts[2]
            page = int(parts[3]) if len(parts) > 3 else 0
            sort_by = parts[4] if len(parts) > 4 else "recent"

            if address not in user['positions']:
                bot.answer_callback_query(call.id, "❌ Token sudah terjual.", show_alert=True)
                return

            execute_sell(call.message.chat.id, user, address, sell_pct)

            text, markup = render_pnl_page(user, page, sort_by)
            if not markup and page > 0: text, markup = render_pnl_page(user, page - 1, sort_by)
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)

    except Exception as e:
        log.exception(f"Callback error on data='{data}': {e}")
        try:
            bot.answer_callback_query(call.id, "⚠️ Terjadi error, cek log server.", show_alert=True)
        except Exception:
            pass

# ================= BACKGROUND: AUTO TP/SL CHECKER =================

def tp_sl_worker():
    while True:
        try:
            for chat_id, user in list(users_db.items()):
                if not (user['tp_on'] or user['sl_on']):
                    continue
                for address in list(user['positions'].keys()):
                    pos = user['positions'].get(address)
                    if not pos:
                        continue
                    data = get_dexscreener_data(address)
                    if not data:
                        continue
                    cur_price = float(data.get('priceUsd', 0))
                    pnl_pct = ((cur_price - pos['entry_usd']) / pos['entry_usd']) * 100 if pos['entry_usd'] > 0 else 0

                    if user['tp_on'] and pnl_pct >= user['tp_pct']:
                        bot.send_message(chat_id, f"🎯 **AUTO TP TERPICU** untuk ${pos['symbol']} (`{pnl_pct:+.2f}%`)", parse_mode='Markdown')
                        execute_sell(chat_id, user, address, 100)
                    elif user['sl_on'] and pnl_pct <= -user['sl_pct']:
                        bot.send_message(chat_id, f"🛑 **AUTO SL TERPICU** untuk ${pos['symbol']} (`{pnl_pct:+.2f}%`)", parse_mode='Markdown')
                        execute_sell(chat_id, user, address, 100)
        except Exception as e:
            log.exception(f"tp_sl_worker error: {e}")
        time.sleep(20)

# ================= BACKGROUND: SCANNER =================

def scanner_worker():
    while True:
        try:
            active_users = [(cid, u) for cid, u in users_db.items() if u['scanner_on']]
            if active_users:
                boosted = get_boosted_tokens(15)
                for item in boosted:
                    addr = item.get('tokenAddress', '')
                    chain = item.get('chainId', 'unknown').upper()
                    if not addr:
                        continue
                    for chat_id, user in active_users:
                        if addr in user['seen_scanner_tokens']:
                            continue
                        user['seen_scanner_tokens'].add(addr)
                        pdata = get_dexscreener_data(addr)
                        symbol = pdata.get('baseToken', {}).get('symbol', '???') if pdata else '???'
                        price = float(pdata.get('priceUsd', 0)) if pdata else 0
                        text = f"🆕 **TOKEN BARU TERDETEKSI**\n🌐 {chain} | **${symbol}**\n💵 `${price:.6f}`\n`{addr}`"
                        markup = InlineKeyboardMarkup()
                        markup.row(InlineKeyboardButton("Buy $50", callback_data=f"buy_50_{addr}"), InlineKeyboardButton("Buy $100", callback_data=f"buy_100_{addr}"))
                        try:
                            bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)
                        except Exception as e:
                            log.warning(f"Gagal kirim scanner notif ke {chat_id}: {e}")
        except Exception as e:
            log.exception(f"scanner_worker error: {e}")
        time.sleep(30)

# ================= START =================

if __name__ == "__main__":
    threading.Thread(target=tp_sl_worker, daemon=True).start()
    threading.Thread(target=scanner_worker, daemon=True).start()
    log.info("Bot starting polling...")
    bot.infinity_polling()
