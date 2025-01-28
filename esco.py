




import logging
import os
import html
import json
import asyncio
import time
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from telethon import TelegramClient, errors
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from telethon.tl.types import (
    UserStatusOnline, UserStatusRecently, UserStatusLastWeek, UserStatusOffline,
    MessageMediaWebPage
)

########################################
# Logging
########################################
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

########################################
# Konstanten und globale Variablen
########################################
BOT_TOKEN = "7464671663:AAGsUwRunSi2SqUi5oDBKZ_QSDrTMDKVcaU"
USER_STATE = {}  # user_id -> Zustand
# Mögliche Zustände: "MAIN_MENU", "ENTER_API_ID", "ENTER_API_HASH",
# "ENTER_PHONE", "WAITING_CODE", "WAITING_PASSWORD", "AUTHORIZED", "WAITING_INTERVAL"

########################################
# Keyboards
########################################
def start_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Weiter ▶️", callback_data="continue")]
    ])

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Konto verbinden 🔑", callback_data="connect_account")],
        [InlineKeyboardButton("Tagger starten 🚀", callback_data="launch_tagger")],
        [InlineKeyboardButton("Anleitung 📚", callback_data="instructions")],
        [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
    ])

def digit_keyboard():
    kb = [
        [
            InlineKeyboardButton("1", callback_data="digit_1"),
            InlineKeyboardButton("2", callback_data="digit_2"),
            InlineKeyboardButton("3", callback_data="digit_3")
        ],
        [
            InlineKeyboardButton("4", callback_data="digit_4"),
            InlineKeyboardButton("5", callback_data="digit_5"),
            InlineKeyboardButton("6", callback_data="digit_6")
        ],
        [
            InlineKeyboardButton("7", callback_data="digit_7"),
            InlineKeyboardButton("8", callback_data="digit_8"),
            InlineKeyboardButton("9", callback_data="digit_9")
        ],
        [
            InlineKeyboardButton("0", callback_data="digit_0"),
            InlineKeyboardButton("Löschen ⬅️", callback_data="digit_del"),
            InlineKeyboardButton("Senden ✅", callback_data="digit_submit")
        ],
        [
            InlineKeyboardButton("Zurück ↩️", callback_data="back")
        ]
    ]
    return InlineKeyboardMarkup(kb)

########################################
# /start
########################################
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_STATE[user_id] = "MAIN_MENU"
    await update.message.reply_text(
        "Hallo 👋! Willkommen beim Bot. Drücke bitte „Weiter“, um das Menü zu öffnen.",
        reply_markup=start_keyboard()
    )

########################################
# Tagger-Funktion (Versand)
########################################
async def run_tagger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Endloser Versand der letzten Nachricht aus „Gespeicherte Nachrichten“ an alle Gruppen."""

    client = context.user_data.get('client')
    if not client:
        await update.effective_message.reply_text("Bitte zuerst das Konto verbinden. ❗")
        return

    interval = context.user_data.get('interval', 60.0)
    invisible_char = '\u200B'
    max_length = 1014

    await update.effective_message.reply_text(
        f"🚀 Der Tagger wurde gestartet! Alle {interval} Sek. wird eine Nachricht gesendet. 📨"
    )

    while True:
        try:
            dialogs = await client.get_dialogs(limit=100)
            saved_messages_dialog = await client.get_entity('me')
            messages = await client.get_messages(saved_messages_dialog, limit=1)
            if not messages:
                logger.info("Keine Nachrichten in den gespeicherten Nachrichten gefunden.")
                await asyncio.sleep(interval)
                continue

            last_message = messages[0]
            message_text = last_message.message if last_message.message else ''
            message_text = html.escape(message_text)
            media = last_message.media
            target_chats = [d for d in dialogs if d.is_group]

            if not target_chats:
                logger.info("Keine Gruppen gefunden, um Nachrichten zu senden.")
                await asyncio.sleep(interval)
                continue

            for chat in target_chats:
                try:
                    participants_list = []
                    # Teilnehmer sammeln
                    async for participant in client.iter_participants(chat):
                        if (
                            isinstance(
                                participant.status,
                                (
                                    UserStatusOnline,
                                    UserStatusRecently,
                                    UserStatusLastWeek,
                                    UserStatusOffline
                                )
                            )
                            and participant.username
                        ):
                            mention = f'<a href="tg://user?id={participant.id}">{invisible_char}</a>'
                            participants_list.append(mention)

                    # Falls keine Teilnehmer gefunden: die letzten 50 Schreiber
                    if not participants_list:
                        async for msg in client.iter_messages(chat, limit=50):
                            if msg.sender and msg.sender.username:
                                mention = f'<a href="tg://user?id={msg.sender_id}">{invisible_char}</a>'
                                participants_list.append(mention)
                            if len(participants_list) >= 50:
                                break

                    # Länge abchecken
                    available_space = max_length - len(html.escape(message_text))
                    mentions = []
                    current_length = 0

                    for mention in participants_list:
                        mention_length = len(html.escape(mention))
                        if current_length + mention_length > available_space:
                            break
                        mentions.append(mention)
                        current_length += mention_length

                    mention_text = ''.join(mentions)
                    final_message_text = message_text + mention_text

                    # >>>>>>>>>>>>  Wichtig: Prüfen, ob media sendbar ist <<<<<<<<<<
                    # Wenn es ein echtes Foto/Video/Datei ist, dann send_file
                    # Falls es ein WebPage-Preview ist (MessageMediaWebPage), verwenden wir nur send_message
                    if media and not isinstance(media, MessageMediaWebPage):
                        await client.send_file(
                            chat,
                            media,
                            caption=final_message_text,
                            parse_mode='html'
                        )
                    else:
                        # Sonst nur Text
                        await client.send_message(
                            chat,
                            final_message_text,
                            parse_mode='html'
                        )

                    logger.info(f"Nachricht wurde an die Gruppe {chat.name} gesendet.")

                except FloodWaitError as e:
                    logger.warning(f"FloodWaitError: Warten für {e.seconds} Sek.")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    logger.error(f"Unerwarteter Fehler beim Senden an {chat.name}: {e}")

            logger.info(f"Warten {interval} Sek. vor dem nächsten Versand...")
            await asyncio.sleep(interval)

        except Exception as e:
            logger.error(f"Fehler in der Hauptschleife des Taggers: {e}")
            await asyncio.sleep(interval)

########################################
# Callback-Handler für Buttons
########################################
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    await query.answer()

    # Buttons für den Code (Ziffern)
    if data.startswith("digit_"):
        if 'code' not in context.user_data:
            context.user_data['code'] = ""

        digit_value = data.split('_')[1]
        if digit_value == "del":
            context.user_data['code'] = context.user_data['code'][:-1]
        elif digit_value == "submit":
            await confirm_code(update, context)
            return
        else:
            context.user_data['code'] += digit_value

        await query.edit_message_text(
            f"Aktueller Code: {context.user_data['code']}",
            reply_markup=digit_keyboard()
        )
        return

    if data == "continue":
        USER_STATE[user_id] = "MAIN_MENU"
        await query.edit_message_text("Hauptmenü:", reply_markup=main_menu_keyboard())

    elif data == "connect_account":
        USER_STATE[user_id] = "ENTER_API_ID"
        await query.edit_message_text(
            "Bitte geben Sie Ihre API ID ein:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
            ])
        )

    elif data == "launch_tagger":
        # Wenn autorisiert, fragen wir nach dem Intervall
        if USER_STATE.get(user_id) == "AUTHORIZED":
            USER_STATE[user_id] = "WAITING_INTERVAL"
            await query.edit_message_text(
                "Bitte geben Sie das Versandintervall in Sekunden ein (z.B. 60):",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
                ])
            )
        else:
            await query.edit_message_text(
                "Bitte zuerst ein Konto verbinden. ❗",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
                ])
            )

    elif data == "instructions":
        await query.edit_message_text(
            "📚 Anleitung:\n"
            "- Verbinden Sie Ihr Konto, indem Sie API-Daten eingeben.\n"
            "- Drücken Sie „Tagger starten“ und geben Sie das Intervall ein.\n"
            "Dann beginnt die automatische Nachricht mit Erwähnungen der Gruppenmitglieder. ✨",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
            ])
        )

    elif data == "back":
        USER_STATE[user_id] = "MAIN_MENU"
        await query.edit_message_text("Hauptmenü:", reply_markup=main_menu_keyboard())

########################################
# Text-Handler
########################################
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    state = USER_STATE.get(user_id, "")

    # API ID
    if state == "ENTER_API_ID":
        context.user_data['api_id'] = update.message.text.strip()
        USER_STATE[user_id] = "ENTER_API_HASH"
        await update.message.reply_text(
            "Perfekt! Bitte geben Sie Ihren API Hash ein:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
            ])
        )
        return

    # API Hash
    if state == "ENTER_API_HASH":
        context.user_data['api_hash'] = update.message.text.strip()
        USER_STATE[user_id] = "ENTER_PHONE"
        await update.message.reply_text(
            "Gut! Bitte geben Sie Ihre Telefonnummer ein (z.B. +49991234567):",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
            ])
        )
        return

    # Telefonnummer
    if state == "ENTER_PHONE":
        context.user_data['phone_number'] = update.message.text.strip()
        await update.message.reply_text(
            "Code wird von Telegram angefordert...",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
            ])
        )
        await create_telethon_client(update, context)
        return

    # Intervall, bevor Tagger gestartet wird
    if state == "WAITING_INTERVAL":
        user_input = update.message.text.strip()
        try:
            interval_value = float(user_input)
            if interval_value <= 0:
                raise ValueError("Das Intervall muss eine positive Zahl sein.")
            context.user_data['interval'] = interval_value
            await update.message.reply_text(
                f"✅ Intervall eingestellt: {interval_value} Sek.\nVersand wird gestartet..."
            )
            USER_STATE[user_id] = "AUTHORIZED"
            asyncio.create_task(run_tagger(update, context))
        except ValueError:
            await update.message.reply_text(
                "Fehler: Bitte geben Sie eine positive Zahl ein. Versuchen Sie es erneut. ❗"
            )
        return

    await update.message.reply_text(
        "Bitte verwenden Sie die Menütasten oder warten Sie auf den richtigen Schritt. ⚠️"
    )

########################################
# Codebestätigung (wenn Ziffern-Buttons verwendet wurden)
########################################
async def confirm_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    code = context.user_data.get('code', '')

    if not code:
        await update.effective_message.reply_text("Code ist leer. Bitte erneut versuchen. ❗")
        return

    client = context.user_data.get('client')
    if not client:
        await update.effective_message.reply_text("Client nicht vorhanden. Bitte erneut anfangen.")
        return

    try:
        await client.sign_in(context.user_data['phone_number'], code)
    except SessionPasswordNeededError:
        await update.effective_message.reply_text(
            "Zwei-Faktor-Authentifizierung aktiviert. Bitte geben Sie Ihr Passwort ein:"
        )
        USER_STATE[user_id] = "WAITING_PASSWORD"
        return
    except FloodWaitError as e:
        await update.effective_message.reply_text(
            f"Zu viele Versuche. Bitte {e.seconds} Sek. warten."
        )
        return
    except errors.PhoneCodeInvalidError:
        await update.effective_message.reply_text("Der Code ist ungültig, bitte erneut eingeben.")
        context.user_data['code'] = ""
        await update.effective_message.reply_text(
            "Bitte geben Sie den Code aus Telegram ein:",
            reply_markup=digit_keyboard()
        )
        return
    except Exception as e:
        await update.effective_message.reply_text(f"Fehler bei der Code-Eingabe: {e}")
        return

    USER_STATE[user_id] = "AUTHORIZED"
    await update.effective_message.reply_text(
        "✔️ Authentifizierung erfolgreich! Sie können nun den Tagger starten.",
        reply_markup=main_menu_keyboard()
    )

########################################
# Telethon-Client erstellen und Code anfordern
########################################
async def create_telethon_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    api_id = context.user_data['api_id']
    api_hash = context.user_data['api_hash']
    phone_number = context.user_data['phone_number']

    session_name = f"session_{user_id}"
    context.user_data['client'] = TelegramClient(session_name, api_id, api_hash)

    client = context.user_data['client']
    await client.connect()
    is_authorized = await client.is_user_authorized()

    if not is_authorized:
        try:
            await client.send_code_request(phone_number)
            USER_STATE[user_id] = "WAITING_CODE"
            context.user_data['code'] = ""
            await update.message.reply_text(
                "Bitte geben Sie den Code aus Telegram ein:",
                reply_markup=digit_keyboard()
            )
        except Exception as e:
            await update.message.reply_text(
                f"Fehler bei der Code-Anforderung: {e}",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Zurück ↩️", callback_data="back")]
                ])
            )
            USER_STATE.pop(user_id, None)
    else:
        USER_STATE[user_id] = "AUTHORIZED"
        await update.message.reply_text(
            "✔️ Bereits authentifiziert! Sie können den Tagger jetzt starten.",
            reply_markup=main_menu_keyboard()
        )

########################################
# Main
########################################
if __name__ == "__main__":
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CallbackQueryHandler(callback_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    application.run_polling()
