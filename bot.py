import os
import logging
from datetime import datetime, time
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDS')
CHAT_ID = os.environ.get('CHAT_ID')
TIMEZONE = 'Europe/Moscow'

HABITS = [
    ('workout', '🏋️ Тренировка'),
    ('self_dev', '📚 Саморазвитие'),
    ('income', '💰 Доп. доход'),
    ('career', '🚀 Развитие карьеры'),
]

user_selections = {}

def get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS)
    creds = Credentials.from_service_account_info(
        creds_dict,
        scopes=['https://spreadsheets.google.com/feeds',
                'https://www.googleapis.com/auth/drive']
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def save_to_sheet(date_str, selections):
    sheet = get_sheet()
    try:
        log = sheet.worksheet('Лог')
    except:
        log = sheet.add_worksheet('Лог', 1000, 10)
        log.append_row(['Дата', '🏋️ Тренировка', '📚 Саморазвитие', '💰 Доп. доход', '🚀 Карьера'])
    row = [date_str]
    for key, _ in HABITS:
        row.append('✅' if key in selections else '❌')
    log.append_row(row)

def get_keyboard(selections):
    keyboard = []
    for key, label in HABITS:
        check = '✅ ' if key in selections else '☐ '
        keyboard.append([InlineKeyboardButton(check + label, callback_data=key)])
    keyboard.append([InlineKeyboardButton('💾 Сохранить', callback_data='save')])
    return InlineKeyboardMarkup(keyboard)

async def send_daily_check(context: ContextTypes.DEFAULT_TYPE):
    chat_id = CHAT_ID
    user_selections[chat_id] = set()
    await context.bot.send_message(
        chat_id=chat_id,
        text='Привет! Отмечай, чему уделила время сегодня 👇\n\n(нажимай на пункты, потом жми Сохранить)',
        reply_markup=get_keyboard(set())
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_selections[chat_id] = set()
    await update.message.reply_text(
        'Привет! Я буду каждый вечер спрашивать про твои привычки 👇',
        reply_markup=get_keyboard(set())
    )

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    if chat_id not in user_selections:
        user_selections[chat_id] = set()
    if query.data == 'save':
        tz = pytz.timezone(TIMEZONE)
        date_str = datetime.now(tz).strftime('%Y-%m-%d')
        save_to_sheet(date_str, user_selections[chat_id])
        done = [label for key, label in HABITS if key in user_selections[chat_id]]
        text = '✅ Сохранено!\n\nСегодня ты уделила время:\n' + '\n'.join(done) if done else '✅ Сохранено!\nСегодня — день отдыха 😴'
        await query.edit_message_text(text)
        user_selections[chat_id] = set()
        return
    if query.data in [k for k, _ in HABITS]:
        if query.data in user_selections[chat_id]:
            user_selections[chat_id].remove(query.data)
        else:
            user_selections[chat_id].add(query.data)
        await query.edit_message_reply_markup(get_keyboard(user_selections[chat_id]))

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button))
    tz = pytz.timezone(TIMEZONE)
    app.job_queue.run_daily(
        send_daily_check,
        time=time(hour=21, minute=0, tzinfo=tz),
        days=(0, 1, 2, 3, 4, 5, 6)
    )
    app.run_polling()

if __nam
