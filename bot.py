import os
import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import gspread
from google.oauth2.service_account import Credentials
import json
import asyncio

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
        scopes=[
            'https://spreadsheets.google.com/feeds',
            'https://www.googleapis.com/auth/drive'
        ]
    )
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)


def save_to_sheet(date_str, selections):
    sheet = get_sheet()
    try:
        log = sheet.worksheet('Log')
    except Exception:
        log = sheet.add_worksheet('Log', 1000, 10)
        log.append_row(['Date', 'Workout', 'Self-dev', 'Income', 'Career'])
    row = [date_str]
    for key, _ in HABITS:
        row.append('✅' if key in selections else '❌')
    log.append_row(row)


def get_stats(days):
    sheet = get_sheet()
    try:
        log = sheet.worksheet('Log')
    except Exception:
        return None
    rows = log.get_all_values()
    if len(rows) <= 1:
        return None
    tz = pytz.timezone(TIMEZONE)
    cutoff = (datetime.now(tz) - timedelta(days=days)).strftime('%Y-%m-%d')
    counts = [0, 0, 0, 0]
    total = 0
    for row in rows[1:]:
        if len(row) < 5:
            continue
        if row[0] >= cutoff:
            total += 1
            for i in range(4):
                if row[i + 1] == '✅':
                    counts[i] += 1
    return counts, total


def get_keyboard(selections):
    keyboard = []
    for key, label in HABITS:
        check = '✅ ' if key in selections else '☐ '
        keyboard.append([InlineKeyboardButton(check + label, callback_data=key)])
    keyboard.append([InlineKeyboardButton('💾 Сохранить', callback_data='save')])
    return InlineKeyboardMarkup(keyboard)


async def send_daily_check(bot):
    chat_id = CHAT_ID
    user_selections[chat_id] = set()
    await bot.send_message(
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


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Считаю статистику...')
    try:
        r7 = get_stats(7)
        r30 = get_stats(30)
        lines = ['📊 Твоя статистика\n']
        for label, result in [('За 7 дней', r7), ('За 30 дней', r30)]:
            lines.append(f'*{label}*')
            if not result:
                lines.append('Нет данных\n')
                continue
            counts, total = result
            for i, (_, habit) in enumerate(HABITS):
                lines.append(f'{habit}: {counts[i]} из {total}')
            lines.append('')
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
    except Exception:
        await update.message.reply_text('Не удалось загрузить статистику 😔')


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
        if done:
            text = '✅ Сохранено!\n\nСегодня ты уделила время:\n' + '\n'.join(done)
        else:
            text = '✅ Сохранено!\nСегодня — день отдыха 😴'
        await query.edit_message_text(text)
        user_selections[chat_id] = set()
        return
    if query.data in [k for k, _ in HABITS]:
        if query.data in user_selections[chat_id]:
            user_selections[chat_id].remove(query.data)
        else:
            user_selections[chat_id].add(query.data)
        await query.edit_message_reply_markup(get_keyboard(user_selections[chat_id]))


async def scheduler(bot):
    tz = pytz.timezone(TIMEZONE)
    while True:
        now = datetime.now(tz)
        if now.hour == 21 and now.minute == 0:
            await send_daily_check(bot)
            await asyncio.sleep(61)
        else:
            await asyncio.sleep(30)


async def post_init(application: Application):
    asyncio.create_task(scheduler(application.bot))


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('stats', stats))
    app.add_handler(CallbackQueryHandler(button))
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
