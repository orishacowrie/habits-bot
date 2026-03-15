import os
import logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
import gspread
from google.oauth2.service_account import Credentials
import json
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('BOT_TOKEN')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
GOOGLE_CREDS = os.environ.get('GOOGLE_CREDS')
TIMEZONE = 'Europe/Moscow'

user_habits = {}
user_notify_hour = {}
user_selections = {}
user_state = {}


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


def get_user_sheet(sheet, chat_id):
    name = f'user_{chat_id}'
    try:
        return sheet.worksheet(name)
    except Exception:
        ws = sheet.add_worksheet(name, 1000, 15)
        ws.append_row(['Дата', 'notify_hour'] + [f'Привычка {i+1}' for i in range(10)])
        return ws


def load_user_data(chat_id):
    if chat_id in user_habits:
        return user_habits.get(chat_id, []), user_notify_hour.get(chat_id, 21)
    try:
        sheet = get_sheet()
        ws = get_user_sheet(sheet, chat_id)
        header = ws.row_values(1)
        hour = 21
        habits = []
        for h in header[1:]:
            if h.startswith('notify_hour:'):
                hour = int(h.replace('notify_hour:', ''))
            elif h and not h.startswith('Привычка') and h != 'notify_hour':
                habits.append(h)
        user_habits[chat_id] = habits
        user_notify_hour[chat_id] = hour
        return habits, hour
    except Exception:
        return [], 21


def save_user_data(chat_id, habits, hour):
    user_habits[chat_id] = habits
    user_notify_hour[chat_id] = hour
    try:
        sheet = get_sheet()
        name = f'user_{chat_id}'
        try:
            ws = sheet.worksheet(name)
            sheet.del_worksheet(ws)
        except Exception:
            pass
        ws = sheet.add_worksheet(name, 1000, 15)
        ws.append_row(['Дата', f'notify_hour:{hour}'] + habits)
    except Exception as e:
        logger.error(f'Error saving user data: {e}')


def save_checkin(chat_id, date_str, selections, habits):
    try:
        sheet = get_sheet()
        ws = get_user_sheet(sheet, chat_id)
        row = [date_str, ''] + ['✅' if h in selections else '❌' for h in habits]
        ws.append_row(row)
    except Exception as e:
        logger.error(f'Error saving checkin: {e}')


def get_stats(chat_id, days):
    try:
        sheet = get_sheet()
        ws = get_user_sheet(sheet, chat_id)
        rows = ws.get_all_values()
        if len(rows) <= 1:
            return None
        habits = []
        for h in rows[0][2:]:
            if h and not h.startswith('Привычка'):
                habits.append(h)
        if not habits:
            return None
        tz = pytz.timezone(TIMEZONE)
        cutoff = (datetime.now(tz) - timedelta(days=days)).strftime('%Y-%m-%d')
        counts = [0] * len(habits)
        total = 0
        for row in rows[1:]:
            if len(row) < 3:
                continue
            if row[0] >= cutoff:
                total += 1
                for i in range(len(habits)):
                    if i + 2 < len(row) and row[i + 2] == '✅':
                        counts[i] += 1
        return habits, counts, total
    except Exception:
        return None


def get_checkin_keyboard(habits, selections):
    keyboard = []
    for h in habits:
        check = '✅ ' if h in selections else '☐ '
        keyboard.append([InlineKeyboardButton(check + h, callback_data=f'toggle_{h}')])
    keyboard.append([InlineKeyboardButton('Сохранить', callback_data='save_checkin')])
    return InlineKeyboardMarkup(keyboard)


def get_stats_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('За 7 дней', callback_data='stats_7')],
        [InlineKeyboardButton('За 30 дней', callback_data='stats_30')],
        [InlineKeyboardButton('За 365 дней', callback_data='stats_365')],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    user_state[chat_id] = 'waiting_habits'
    await update.message.reply_text(
        'Напиши через запятую привычки, которые ты хочешь отслеживать каждый день'
    )


async def cmd_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    habits, hour = load_user_data(chat_id)
    if not habits:
        text = 'У тебя пока нет списка привычек.'
    else:
        text = 'Твои текущие привычки:\n' + '\n'.join(f'- {h}' for h in habits)
    text += '\n\nНапиши новый список через запятую, чтобы заменить:'
    user_state[chat_id] = 'waiting_habits'
    await update.message.reply_text(text)


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('За какой период?', reply_markup=get_stats_keyboard())


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    data = query.data

    if data.startswith('toggle_'):
        habit = data[7:]
        if chat_id not in user_selections:
            user_selections[chat_id] = set()
        if habit in user_selections[chat_id]:
            user_selections[chat_id].remove(habit)
        else:
            user_selections[chat_id].add(habit)
        habits, _ = load_user_data(chat_id)
        await query.edit_message_reply_markup(
            get_checkin_keyboard(habits, user_selections[chat_id])
        )

    elif data == 'save_checkin':
        habits, _ = load_user_data(chat_id)
        selections = user_selections.get(chat_id, set())
        tz = pytz.timezone(TIMEZONE)
        date_str = datetime.now(tz).strftime('%Y-%m-%d')
        save_checkin(chat_id, date_str, selections, habits)
        done = [h for h in habits if h in selections]
        if done:
            text = 'Сохранено!\n\nСегодня выполнено:\n' + '\n'.join(f'- {h}' for h in done)
        else:
            text = 'Сохранено! Сегодня — день отдыха.'
        user_selections[chat_id] = set()
        await query.edit_message_text(text)

    elif data.startswith('stats_'):
        days = int(data.split('_')[1])
        result = get_stats(chat_id, days)
        if not result:
            await query.edit_message_text(
                'Нет данных пока. Сначала отметь несколько дней!'
            )
            return
        habits, counts, total = result
        lines = [f'Статистика за {days} дней:\n']
        for i, h in enumerate(habits):
            pct = round(counts[i] / total * 100) if total > 0 else 0
            lines.append(f'- {h}: {counts[i]} из {total} ({pct}%)')
        await query.edit_message_text('\n'.join(lines))


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    state = user_state.get(chat_id)
    text = update.message.text.strip()

    if state == 'waiting_habits':
        habits = [h.strip() for h in text.split(',') if h.strip()][:10]
        if not habits:
            await update.message.reply_text(
                'Не понял. Напиши привычки через запятую, например:\nЗарядка, Чтение, Медитация'
            )
            return
        user_habits[chat_id] = habits
        user_state[chat_id] = 'waiting_hour'
        await update.message.reply_text(
            'В котором часу присылать напоминание? (по Москве, только цифры, например: 21)'
        )

    elif state == 'waiting_hour':
        if not text.isdigit() or not (0 <= int(text) <= 23):
            await update.message.reply_text(
                'Напиши только число от 0 до 23, например: 21'
            )
            return
        hour = int(text)
        habits = user_habits.get(chat_id, [])
        save_user_data(chat_id, habits, hour)
        user_state[chat_id] = None
        await update.message.reply_text(
            f'Всё принято! В {hour:02d}:00 ты получишь свой первый опросник.\n\n'
            f'После заполнения используй /stats чтобы видеть прогресс, '
            f'используй /list чтобы менять список привычек.'
        )

    else:
        await update.message.reply_text(
            'Используй /stats для статистики или /list чтобы изменить список привычек.'
        )


async def send_daily_check(bot):
    try:
        sheet = get_sheet()
        worksheets = sheet.worksheets()
        tz = pytz.timezone(TIMEZONE)
        current_hour = datetime.now(tz).hour
        for ws in worksheets:
            if ws.title.startswith('user_'):
                chat_id = ws.title.replace('user_', '')
                try:
                    habits, hour = load_user_data(chat_id)
                    if habits and hour == current_hour:
                        user_selections[chat_id] = set()
                        await bot.send_message(
                            chat_id=chat_id,
                            text='Привет! Отмечай, что выполнила сегодня:',
                            reply_markup=get_checkin_keyboard(habits, set())
                        )
                except Exception as e:
                    logger.error(f'Error sending to {chat_id}: {e}')
    except Exception as e:
        logger.error(f'Error in send_daily_check: {e}')


async def scheduler(bot):
    tz = pytz.timezone(TIMEZONE)
    while True:
        now = datetime.now(tz)
        if now.minute == 0:
            await send_daily_check(bot)
            await asyncio.sleep(61)
        else:
            await asyncio.sleep(30)


async def post_init(application: Application):
    asyncio.create_task(scheduler(application.bot))


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('list', cmd_list))
    app.add_handler(CommandHandler('stats', cmd_stats))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
