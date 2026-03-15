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
        ws.append_row(['Дата'] + [f'Привычка {i+1}' for i in range(10)])
        return ws


def load_user_habits(chat_id):
    if chat_id in user_habits:
        return user_habits[chat_id]
    try:
        sheet = get_sheet()
        ws = get_user_sheet(sheet, chat_id)
        header = ws.row_values(1)
        habits = [h for h in header[1:] if h and not h.startswith('Привычка')]
        user_habits[chat_id] = habits
        return habits
    except Exception:
        return []


def save_user_habits(chat_id, habits):
    user_habits[chat_id] = habits
    try:
        sheet = get_sheet()
        name = f'user_{chat_id}'
        try:
            ws = sheet.worksheet(name)
            sheet.del_worksheet(ws)
        except Exception:
            pass
        ws = sheet.add_worksheet(name, 1000, 15)
        ws.append_row(['Дата'] + habits)
    except Exception as e:
        logger.error(f'Error saving habits: {e}')


def save_checkin(chat_id, date_str, selections, habits):
    try:
        sheet = get_sheet()
        ws = get_user_sheet(sheet, chat_id)
        row = [date_str] + ['✅' if h in selections else '❌' for h in habits]
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
        habits = [h for h in rows[0][1:] if h]
        tz = pytz.timezone(TIMEZONE)
        cutoff = (datetime.now(tz) - timedelta(days=days)).strftime('%Y-%m-%d')
        counts = [0] * len(habits)
        total = 0
        for row in rows[1:]:
            if len(row) < 2:
                continue
            if row[0] >= cutoff:
                total += 1
                for i in range(len(habits)):
                    if i + 1 < len(row) and row[i + 1] == '✅':
                        counts[i] += 1
        return habits, counts, total
    except Exception:
        return None


def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('✏️ Мои привычки', callback_data='my_habits')],
        [InlineKeyboardButton('✅ Отметить день', callback_data='checkin')],
        [InlineKeyboardButton('📊 Статистика', callback_data='stats_menu')],
    ])


def get_checkin_keyboard(habits, selections):
    keyboard = []
    for h in habits:
        check = '✅ ' if h in selections else '☐ '
        keyboard.append([InlineKeyboardButton(check + h, callback_data=f'toggle_{h}')])
    keyboard.append([InlineKeyboardButton('💾 Сохранить', callback_data='save_checkin')])
    keyboard.append([InlineKeyboardButton('« Назад', callback_data='back')])
    return InlineKeyboardMarkup(keyboard)


def get_stats_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton('За 7 дней', callback_data='stats_7')],
        [InlineKeyboardButton('За 30 дней', callback_data='stats_30')],
        [InlineKeyboardButton('За 365 дней', callback_data='stats_365')],
        [InlineKeyboardButton('« Назад', callback_data='back')],
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    name = update.effective_user.first_name or 'друг'
    habits = load_user_habits(chat_id)
    if not habits:
        await update.message.reply_text(
            f'Привет, {name}! 👋\n\nЯ помогу отслеживать твои привычки.\n\nДля начала добавь привычки — нажми кнопку ниже.',
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text(
            f'Привет, {name}! 👋\n\nЧто делаем?',
            reply_markup=get_main_keyboard()
        )


async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = str(query.message.chat_id)
    data = query.data

    if data == 'back':
        await query.edit_message_text('Что делаем?', reply_markup=get_main_keyboard())

    elif data == 'my_habits':
        habits = load_user_habits(chat_id)
        text = '✏️ Твои привычки:\n\n'
        if habits:
            text += '\n'.join(f'{i+1}. {h}' for i, h in enumerate(habits))
        else:
            text += 'Пока нет привычек.'
        text += '\n\nЧтобы задать новый список — напиши мне привычки через запятую.\nНапример: Зарядка, Чтение, Медитация\n\n(максимум 10 штук)'
        user_state[chat_id] = 'waiting_habits'
        await query.edit_message_text(text)

    elif data == 'checkin':
        habits = load_user_habits(chat_id)
        if not habits:
            await query.edit_message_text(
                'Сначала добавь привычки! Нажми "Мои привычки".',
                reply_markup=get_main_keyboard()
            )
            return
        user_selections[chat_id] = set()
        await query.edit_message_text(
            'Отмечай что сделала сегодня 👇',
            reply_markup=get_checkin_keyboard(habits, set())
        )

    elif data.startswith('toggle_'):
        habit = data[7:]
        if chat_id not in user_selections:
            user_selections[chat_id] = set()
        if habit in user_selections[chat_id]:
            user_selections[chat_id].remove(habit)
        else:
            user_selections[chat_id].add(habit)
        habits = load_user_habits(chat_id)
        await query.edit_message_reply_markup(
            get_checkin_keyboard(habits, user_selections[chat_id])
        )

    elif data == 'save_checkin':
        habits = load_user_habits(chat_id)
        selections = user_selections.get(chat_id, set())
        tz = pytz.timezone(TIMEZONE)
        date_str = datetime.now(tz).strftime('%Y-%m-%d')
        save_checkin(chat_id, date_str, selections, habits)
        done = [h for h in habits if h in selections]
        if done:
            text = '✅ Сохранено!\n\nСегодня ты уделила время:\n' + '\n'.join(done)
        else:
            text = '✅ Сохранено!\nСегодня — день отдыха 😴'
        user_selections[chat_id] = set()
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton('« В меню', callback_data='back')]
        ]))

    elif data == 'stats_menu':
        await query.edit_message_text('За какой период?', reply_markup=get_stats_keyboard())

    elif data.startswith('stats_'):
        days = int(data.split('_')[1])
        result = get_stats(chat_id, days)
        if not result:
            await query.edit_message_text(
                'Нет данных пока. Сначала отметь несколько дней!',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('« Назад', callback_data='stats_menu')]])
            )
            return
        habits, counts, total = result
        lines = [f'📊 Статистика за {days} дней\n']
        for i, h in enumerate(habits):
            pct = round(counts[i] / total * 100) if total > 0 else 0
            lines.append(f'{h}: {counts[i]} из {total} ({pct}%)')
        await query.edit_message_text(
            '\n'.join(lines),
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('« Назад', callback_data='stats_menu')]
            ])
        )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    state = user_state.get(chat_id)

    if state == 'waiting_habits':
        text = update.message.text
        habits = [h.strip() for h in text.split(',') if h.strip()][:10]
        if not habits:
            await update.message.reply_text(
                'Не понял 🤔 Напиши привычки через запятую, например:\nЗарядка, Чтение, Медитация'
            )
            return
        save_user_habits(chat_id, habits)
        user_state[chat_id] = None
        await update.message.reply_text(
            f'Отлично! Сохранила {len(habits)} привычек:\n' + '\n'.join(f'• {h}' for h in habits) +
            '\n\nКаждый день в 23:00 я буду напоминать тебе их отметить 👇',
            reply_markup=get_main_keyboard()
        )
    else:
        await update.message.reply_text('Что делаем?', reply_markup=get_main_keyboard())


async def send_daily_check(bot):
    try:
        sheet = get_sheet()
        worksheets = sheet.worksheets()
        for ws in worksheets:
            if ws.title.startswith('user_'):
                chat_id = ws.title.replace('user_', '')
                try:
                    habits = load_user_habits(chat_id)
                    if habits:
                        user_selections[chat_id] = set()
                        await bot.send_message(
                            chat_id=chat_id,
                            text='Привет! Отмечай, чему уделила время сегодня 👇',
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
        if now.hour == 23 and now.minute == 0:
            await send_daily_check(bot)
            await asyncio.sleep(61)
        else:
            await asyncio.sleep(30)


async def post_init(application: Application):
    asyncio.create_task(scheduler(application.bot))


def main():
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(drop_pending_updates=True)


if __name__ == '__main__':
    main()
