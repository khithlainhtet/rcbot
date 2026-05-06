import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telethon import errors as telethon_errors

from checker_service import TelegramCheckerService
from agent_manager import AgentManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

RESULTS_DIR = Path("results")
RESULTS_DIR.mkdir(exist_ok=True)

CHOOSING_METHOD, AWAITING_INPUT = range(2)
SETUP_ASK_COUNT, SETUP_API_ID, SETUP_API_HASH, SETUP_PHONE, SETUP_OTP, SETUP_2FA = range(2, 8)
ADD_ASK_COUNT, ADD_API_ID, ADD_API_HASH, ADD_PHONE, ADD_OTP, ADD_2FA = range(8, 14)
DELETE_ASK_NUMBER = 14

agent_manager = None
checker_service = None


def escape_md(text: str) -> str:
    if not text:
        return ""
    return escape_markdown(str(text), version=2)


def format_result_emoji(state: str) -> str:
    emoji_map = {
        "banned": "🚫",
        "invalid": "❌",
        "unregistered": "❌",
        "registered": "✅",
        "error": "💥"
    }
    return emoji_map.get(state, "❓")


def format_single_result(result: Dict) -> str:
    state = result.get("state")
    phone = escape_md(result.get("phone", "Unknown"))
    emoji = format_result_emoji(state)
    
    if state == "banned":
        return f"{emoji} *{phone}*\n└ Status: BANNED\n"
    
    elif state == "invalid":
        return f"{emoji} *{phone}*\n└ Status: INVALID NUMBER\n"
    
    elif state == "unregistered":
        return f"{emoji} *{phone}*\n└ Status: NOT REGISTERED \\(or hidden by privacy\\)\n"
    
    elif state == "registered":
        data = result.get("data", {})
        user_id = data.get('id', 'Unknown')
        username = escape_md(data.get('username', ''))
        
        result_text = f"{emoji} *{phone}*\n"
        result_text += f"├ ID: `{user_id}`\n"
        if username:
            result_text += f"└ Username: @{username}\n"
        else:
            result_text += f"└ Username: _None_\n"
        return result_text
    
    elif state == "error":
        error = escape_md(result.get("error", "Unknown error"))
        return f"{emoji} *{phone}*\n└ Error: {error}\n"
    
    return f"❓ *{phone}*\n└ Status: Unknown\n"


def create_summary_stats(results: List[Dict]) -> str:
    stats = {
        "banned": 0,
        "invalid": 0,
        "unregistered": 0,
        "registered": 0,
        "error": 0
    }
    
    for result in results:
        state = result.get("state")
        if state in stats:
            stats[state] += 1
    
    total = len(results)
    summary = f"📊 *Summary \\({total} numbers\\)*\n\n"
    summary += f"✅ Registered: {stats['registered']}\n"
    summary += f"❌ Unregistered: {stats['unregistered']}\n"
    summary += f"🚫 Banned: {stats['banned']}\n"
    summary += f"❌ Invalid: {stats['invalid']}\n"
    if stats['error'] > 0:
        summary += f"💥 Errors: {stats['error']}\n"
    
    return summary


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not agent_manager.has_agents():
        await update.message.reply_text(
            "👋 Welcome to the Telegram Phone Number Checker Bot!\n\n"
            "⚠️ You don't have any agents configured yet.\n"
            "Agents are Telegram accounts used to check phone numbers.\n\n"
            "Let's set up your first agent!",
        )
        return await start_agent_setup(update, context)
    
    agent_count = agent_manager.get_active_count()
    
    welcome_text = (
        "🤖 *Telegram Phone Number Checker*\n\n"
        "Welcome\\! I can check if phone numbers are registered on Telegram\\.\n\n"
        "*How to use:*\n"
        "📝 Send phone numbers directly \\(one per line or comma\\-separated\\)\n"
        "📄 Upload a \\.txt file with phone numbers \\(one per line\\)\n\n"
        "*Example text:*\n"
        "`\\+1234567890`\n"
        "`\\+9876543210, \\+1122334455`\n\n"
        "*Detection States:*\n"
        "✅ Registered \\- ID and username available\n"
        "🚫 Banned \\- Number is banned\n"
        "❌ Unregistered \\- Not on Telegram \\+ Hidden users\n\n"
        f"*Active Agents:* {agent_count}\n\n"
        "Just send me phone numbers or upload a file to start\\!"
    )
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    
    return ConversationHandler.END


async def start_agent_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "🔧 Agent Setup\n\n"
        "How many agents do you want to add?\n"
        "(Recommended: 2-5 for better speed and rate limit avoidance)\n\n"
        "Send a number or /cancel to abort."
    )
    return SETUP_ASK_COUNT


async def setup_agent_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        count = int(update.message.text.strip())
        if count < 1 or count > 20:
            await update.message.reply_text("Please enter a number between 1 and 20.")
            return SETUP_ASK_COUNT
        
        context.user_data['setup_count'] = count
        context.user_data['setup_current'] = 1
        context.user_data['setup_agents'] = []
        
        await update.message.reply_text(
            f"✅ Setting up {count} agent(s).\n\n"
            f"📝 Agent 1/{count}\n\n"
            "Please send your Telegram API ID.\n"
            "(Get it from https://my.telegram.org/apps)\n\n"
            "Send /cancel to abort."
        )
        return SETUP_API_ID
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return SETUP_ASK_COUNT


async def setup_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        api_id = int(update.message.text.strip())
        context.user_data['temp_api_id'] = api_id
        
        current = context.user_data['setup_current']
        total = context.user_data['setup_count']
        
        await update.message.reply_text(
            f"📝 Agent {current}/{total}\n\n"
            f"API ID: {api_id}\n\n"
            "Now send your API Hash:"
        )
        return SETUP_API_HASH
    except ValueError:
        await update.message.reply_text("Please enter a valid API ID (numbers only).")
        return SETUP_API_ID


async def setup_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    api_hash = update.message.text.strip()
    context.user_data['temp_api_hash'] = api_hash
    
    current = context.user_data['setup_current']
    total = context.user_data['setup_count']
    
    await update.message.reply_text(
        f"📝 Agent {current}/{total}\n\n"
        "Now send your phone number (with country code):\n"
        "Example: +1234567890"
    )
    return SETUP_PHONE


async def setup_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    context.user_data['temp_phone'] = phone
    
    api_id = context.user_data['temp_api_id']
    api_hash = context.user_data['temp_api_hash']
    
    from telethon import TelegramClient
    
    current = context.user_data['setup_current']
    serial = len(agent_manager.agents) + current
    session_name = f"agent_{serial}"
    context.user_data['temp_session'] = session_name
    
    client = TelegramClient(session_name, api_id, api_hash)
    
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        context.user_data['phone_code_hash'] = sent_code.phone_code_hash
        await client.disconnect()
        
        total = context.user_data['setup_count']
        
        await update.message.reply_text(
            f"📝 Agent {current}/{total}\n\n"
            f"✅ Verification code sent to {phone}!\n\n"
            "Please send the code you received:"
        )
        return SETUP_OTP
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        
        for f in os.listdir():
            if f.startswith(session_name) and (f.endswith('.session') or f.endswith('.session-journal')):
                try:
                    os.remove(f)
                except:
                    pass
        
        await update.message.reply_text(
            "❌ Failed to send verification code. Please check your API credentials and try again.\n\n"
            "Send your API ID:"
        )
        return SETUP_API_ID


async def setup_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().replace("-", "").replace(" ", "")
    
    api_id = context.user_data['temp_api_id']
    api_hash = context.user_data['temp_api_hash']
    phone = context.user_data['temp_phone']
    phone_code_hash = context.user_data.get('phone_code_hash', '')
    session_name = context.user_data.get('temp_session')
    
    success, message = await agent_manager.add_agent(
        api_id, api_hash, phone, code,
        phone_code_hash=phone_code_hash,
        session_name=session_name
    )
    
    if "2FA" in message or "password" in message.lower():
        await update.message.reply_text(
            "🔐 Two-factor authentication detected.\n\n"
            "Please send your 2FA password:"
        )
        context.user_data['temp_code'] = code
        return SETUP_2FA
    
    if not success:
        session_name = context.user_data.get('temp_session')
        if session_name:
            for f in os.listdir():
                if f.startswith(session_name) and (f.endswith('.session') or f.endswith('.session-journal')):
                    try:
                        os.remove(f)
                    except:
                        pass
    
    if success:
        context.user_data['setup_agents'].append(message)
        
        current = context.user_data['setup_current']
        total = context.user_data['setup_count']
        
        if current < total:
            context.user_data['setup_current'] = current + 1
            
            await update.message.reply_text(
                f"{message}\n\n"
                f"📝 Agent {current + 1}/{total}\n\n"
                "Please send your Telegram API ID:"
            )
            return SETUP_API_ID
        else:
            await checker_service.initialize()
            
            summary = "\n".join(context.user_data['setup_agents'])
            await update.message.reply_text(
                f"🎉 Setup complete!\n\n{summary}\n\n"
                "You can now use /start to check phone numbers!"
            )
            return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ {message}\n\n"
            "Please try again with the API ID:"
        )
        return SETUP_API_ID


async def setup_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    
    api_id = context.user_data['temp_api_id']
    api_hash = context.user_data['temp_api_hash']
    phone = context.user_data['temp_phone']
    code = context.user_data['temp_code']
    phone_code_hash = context.user_data.get('phone_code_hash', '')
    session_name = context.user_data.get('temp_session')
    
    success, message = await agent_manager.add_agent(
        api_id, api_hash, phone, code,
        phone_code_hash=phone_code_hash,
        password=password,
        session_name=session_name
    )
    
    if success:
        context.user_data['setup_agents'].append(message)
        
        current = context.user_data['setup_current']
        total = context.user_data['setup_count']
        
        if current < total:
            context.user_data['setup_current'] = current + 1
            
            await update.message.reply_text(
                f"{message}\n\n"
                f"📝 Agent {current + 1}/{total}\n\n"
                "Please send your Telegram API ID:"
            )
            return SETUP_API_ID
        else:
            await checker_service.initialize()
            
            summary = "\n".join(context.user_data['setup_agents'])
            await update.message.reply_text(
                f"🎉 Setup complete!\n\n{summary}\n\n"
                "You can now use /start to check phone numbers!"
            )
            return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ {message}\n\n"
            "Please try again with the API ID:"
        )
        return SETUP_API_ID


async def agents_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    agents = agent_manager.get_all_agents()
    
    if not agents:
        await update.message.reply_text("📭 No agents configured.\n\nUse /addagents to add agents.")
        return
    
    message = "🤖 *Configured Agents*\n\n"
    for agent in agents:
        status = "✅ Active" if agent['active'] else "❌ Inactive"
        message += f"Agent \\#{agent['serial']}\n"
        message += f"├ Phone: `{escape_md(agent['phone'])}`\n"
        message += f"└ Status: {status}\n\n"
    
    message += f"_Total: {len(agents)} agent\\(s\\)_"
    
    await update.message.reply_text(message, parse_mode=ParseMode.MARKDOWN_V2)


async def addagents_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "➕ Add New Agents\n\n"
        "How many agents do you want to add?\n\n"
        "Send a number or /cancel to abort."
    )
    return ADD_ASK_COUNT


async def add_agent_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        count = int(update.message.text.strip())
        if count < 1 or count > 20:
            await update.message.reply_text("Please enter a number between 1 and 20.")
            return ADD_ASK_COUNT
        
        context.user_data['add_count'] = count
        context.user_data['add_current'] = 1
        context.user_data['add_agents'] = []
        
        await update.message.reply_text(
            f"✅ Adding {count} agent(s).\n\n"
            f"📝 Agent 1/{count}\n\n"
            "Please send your Telegram API ID:"
        )
        return ADD_API_ID
    except ValueError:
        await update.message.reply_text("Please enter a valid number.")
        return ADD_ASK_COUNT


async def add_api_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        api_id = int(update.message.text.strip())
        context.user_data['temp_api_id'] = api_id
        
        current = context.user_data['add_current']
        total = context.user_data['add_count']
        
        await update.message.reply_text(
            f"📝 Agent {current}/{total}\n\n"
            f"API ID: {api_id}\n\n"
            "Now send your API Hash:"
        )
        return ADD_API_HASH
    except ValueError:
        await update.message.reply_text("Please enter a valid API ID (numbers only).")
        return ADD_API_ID


async def add_api_hash(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    api_hash = update.message.text.strip()
    context.user_data['temp_api_hash'] = api_hash
    
    current = context.user_data['add_current']
    total = context.user_data['add_count']
    
    await update.message.reply_text(
        f"📝 Agent {current}/{total}\n\n"
        "Now send your phone number (with country code):\n"
        "Example: +1234567890"
    )
    return ADD_PHONE


async def add_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    phone = update.message.text.strip()
    context.user_data['temp_phone'] = phone
    
    api_id = context.user_data['temp_api_id']
    api_hash = context.user_data['temp_api_hash']
    
    from telethon import TelegramClient
    
    current = context.user_data['add_current']
    serial = len(agent_manager.agents) + current
    session_name = f"agent_{serial}"
    context.user_data['temp_session'] = session_name
    
    client = TelegramClient(session_name, api_id, api_hash)
    
    try:
        await client.connect()
        sent_code = await client.send_code_request(phone)
        context.user_data['phone_code_hash'] = sent_code.phone_code_hash
        await client.disconnect()
        
        total = context.user_data['add_count']
        
        await update.message.reply_text(
            f"📝 Agent {current}/{total}\n\n"
            f"✅ Verification code sent to {phone}!\n\n"
            "Please send the code you received:"
        )
        return ADD_OTP
    except Exception as e:
        try:
            await client.disconnect()
        except:
            pass
        
        for f in os.listdir():
            if f.startswith(session_name) and (f.endswith('.session') or f.endswith('.session-journal')):
                try:
                    os.remove(f)
                except:
                    pass
        
        await update.message.reply_text(
            "❌ Failed to send verification code. Please check your API credentials and try again.\n\n"
            "Send your API ID:"
        )
        return ADD_API_ID


async def add_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    code = update.message.text.strip().replace("-", "").replace(" ", "")
    
    api_id = context.user_data['temp_api_id']
    api_hash = context.user_data['temp_api_hash']
    phone = context.user_data['temp_phone']
    phone_code_hash = context.user_data.get('phone_code_hash', '')
    session_name = context.user_data.get('temp_session')
    
    success, message = await agent_manager.add_agent(
        api_id, api_hash, phone, code,
        phone_code_hash=phone_code_hash,
        session_name=session_name
    )
    
    if "2FA" in message or "password" in message.lower():
        await update.message.reply_text(
            "🔐 Two-factor authentication detected.\n\n"
            "Please send your 2FA password:"
        )
        context.user_data['temp_code'] = code
        return ADD_2FA
    
    if not success:
        session_name = context.user_data.get('temp_session')
        if session_name:
            for f in os.listdir():
                if f.startswith(session_name) and (f.endswith('.session') or f.endswith('.session-journal')):
                    try:
                        os.remove(f)
                    except:
                        pass
    
    if success:
        context.user_data['add_agents'].append(message)
        
        current = context.user_data['add_current']
        total = context.user_data['add_count']
        
        if current < total:
            context.user_data['add_current'] = current + 1
            
            await update.message.reply_text(
                f"{message}\n\n"
                f"📝 Agent {current + 1}/{total}\n\n"
                "Please send your Telegram API ID:"
            )
            return ADD_API_ID
        else:
            await checker_service.initialize()
            
            summary = "\n".join(context.user_data['add_agents'])
            await update.message.reply_text(
                f"🎉 Agents added successfully!\n\n{summary}\n\n"
                "Use /agents to see all configured agents."
            )
            return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ {message}\n\n"
            "Please try again with the API ID:"
        )
        return ADD_API_ID


async def add_2fa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    password = update.message.text.strip()
    
    api_id = context.user_data['temp_api_id']
    api_hash = context.user_data['temp_api_hash']
    phone = context.user_data['temp_phone']
    code = context.user_data['temp_code']
    phone_code_hash = context.user_data.get('phone_code_hash', '')
    session_name = context.user_data.get('temp_session')
    
    success, message = await agent_manager.add_agent(
        api_id, api_hash, phone, code,
        phone_code_hash=phone_code_hash,
        password=password,
        session_name=session_name
    )
    
    if success:
        context.user_data['add_agents'].append(message)
        
        current = context.user_data['add_current']
        total = context.user_data['add_count']
        
        if current < total:
            context.user_data['add_current'] = current + 1
            
            await update.message.reply_text(
                f"{message}\n\n"
                f"📝 Agent {current + 1}/{total}\n\n"
                "Please send your Telegram API ID:"
            )
            return ADD_API_ID
        else:
            await checker_service.initialize()
            
            summary = "\n".join(context.user_data['add_agents'])
            await update.message.reply_text(
                f"🎉 Agents added successfully!\n\n{summary}\n\n"
                "Use /agents to see all configured agents."
            )
            return ConversationHandler.END
    else:
        await update.message.reply_text(
            f"❌ {message}\n\n"
            "Please try again with the API ID:"
        )
        return ADD_API_ID


async def deleteagents_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    agents = agent_manager.get_all_agents()
    
    if not agents:
        await update.message.reply_text("📭 No agents configured.")
        return ConversationHandler.END
    
    message = "🗑️ Delete Agent\n\n"
    message += "Configured agents:\n\n"
    for agent in agents:
        message += f"Agent #{agent['serial']} - {agent['phone']}\n"
    
    message += "\nSend the agent number to delete (e.g., '1' to delete Agent #1)\n"
    message += "Or send /cancel to abort."
    
    await update.message.reply_text(message)
    return DELETE_ASK_NUMBER


async def delete_agent_number(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        serial_number = int(update.message.text.strip())
        
        success, message = agent_manager.delete_agent(serial_number)
        
        if success:
            await checker_service.initialize()
            await update.message.reply_text(f"✅ {message}")
        else:
            await update.message.reply_text(f"❌ {message}")
        
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("Please enter a valid agent number.")
        return DELETE_ASK_NUMBER


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "input_text":
        instruction_text = (
            "📝 *Enter Phone Numbers*\n\n"
            "Send me phone numbers in one of these formats:\n"
            "• One per line\n"
            "• Comma separated\n"
            "• With or without country code\n\n"
            "Example:\n"
            "`\\+1234567890`\n"
            "`\\+9876543210, \\+1122334455`\n\n"
            "Send /cancel to go back\\."
        )
        
        await query.message.edit_text(
            instruction_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return AWAITING_INPUT
    
    elif query.data == "input_file":
        instruction_text = (
            "📄 *Upload File*\n\n"
            "Upload a \\.txt file with phone numbers\\.\n"
            "One number per line\\.\n\n"
            "Example file content:\n"
            "`\\+1234567890`\n"
            "`\\+9876543210`\n"
            "`\\+1122334455`\n\n"
            "Send /cancel to go back\\."
        )
        
        await query.message.edit_text(
            instruction_text,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return AWAITING_INPUT
    
    elif query.data == "help":
        agent_count = agent_manager.get_active_count()
        
        help_text = (
            "ℹ️ *Help Information*\n\n"
            "*What this bot does:*\n"
            "• Checks if phone numbers are registered on Telegram\n"
            "• Retrieves user ID and username \\(if available\\)\n"
            "• Uses multiple agents for faster processing\n\n"
            "*Detection States:*\n"
            "✅ Registered \\- ID and username available\n"
            "🚫 Banned \\- Number is banned\n"
            "❌ Unregistered \\- Not on Telegram \\+ Hidden users\n\n"
            f"*Active Agents:* {agent_count}\n\n"
            "*Commands:*\n"
            "/start \\- Check phone numbers\n"
            "/agents \\- View all agents\n"
            "/addagents \\- Add new agents\n"
            "/deleteagents \\- Remove agents\n\n"
            "Use /start to begin checking\\!"
        )
        
        keyboard = [[InlineKeyboardButton("« Back to Menu", callback_data="back_to_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.message.edit_text(
            help_text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return CHOOSING_METHOD
    
    elif query.data == "back_to_menu":
        return await start(update, context)
    
    return CHOOSING_METHOD


async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    phone_numbers = []
    for line in text.replace(',', '\n').split('\n'):
        line = line.strip()
        if line and not line.startswith('/'):
            phone_numbers.append(line)
    
    if not phone_numbers:
        await update.message.reply_text(
            "❌ No valid phone numbers found\\. Please try again\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return AWAITING_INPUT
    
    await process_phone_numbers(update, context, phone_numbers)
    return ConversationHandler.END


async def handle_file_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    document = update.message.document
    
    if not document.file_name.endswith('.txt'):
        await update.message.reply_text(
            "❌ Please upload a \\.txt file\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return AWAITING_INPUT
    
    file = await context.bot.get_file(document.file_id)
    file_path = f"temp_{update.message.chat_id}.txt"
    await file.download_to_drive(file_path)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        phone_numbers = [line.strip() for line in lines if line.strip()]
        
        if not phone_numbers:
            await update.message.reply_text(
                "❌ No phone numbers found in file\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return AWAITING_INPUT
        
        await process_phone_numbers(update, context, phone_numbers)
        
    finally:
        if os.path.exists(file_path):
            os.remove(file_path)
    
    return ConversationHandler.END


async def process_phone_numbers(update: Update, context: ContextTypes.DEFAULT_TYPE, phone_numbers: List[str]):
    total = len(phone_numbers)
    agent_count = agent_manager.get_active_count()
    
    if agent_count == 0:
        await update.message.reply_text("❌ No agents available. Please configure agents first.")
        return
    
    status_msg = await update.message.reply_text(
        f"🚀 Found {total} numbers. Checking with {agent_count} agent(s) working concurrently..."
    )
    
    completed = 0
    
    async def check_with_progress(phone: str):
        nonlocal completed
        result = await checker_service.check_phone(phone)
        completed += 1
        
        if completed % 5 == 0 or completed == total:
            progress = int((completed / total) * 100)
            try:
                await status_msg.edit_text(
                    f"🔄 Progress: {completed}/{total} ({progress}%)\n"
                    f"Using {agent_count} agent(s) concurrently"
                )
            except:
                pass
        
        return result
    
    results = await asyncio.gather(*[
        check_with_progress(phone) 
        for phone in phone_numbers
    ])
    
    await status_msg.delete()
    
    registered = []
    banned = []
    unregistered = []
    errors = []
    invalid = []
    
    for result in results:
        state = result.get("state")
        phone = result.get("phone", "")
        
        if state == "registered":
            data = result.get("data", {})
            user_id = data.get("id", "N/A")
            username = data.get("username") or "N/A"
            registered.append({
                "phone": phone,
                "id": user_id,
                "username": username
            })
        elif state == "banned":
            banned.append(phone)
        elif state == "unregistered":
            unregistered.append(phone)
        elif state == "error":
            error_msg = result.get("error", "Unknown error")
            errors.append({"phone": phone, "error": error_msg})
        elif state == "invalid":
            invalid.append(phone)
    
    message_lines = ["🎯 CHECKING COMPLETED 🎯\n"]
    
    if registered:
        message_lines.append("✅ REGISTERED ACCOUNTS:")
        for user in registered:
            username_display = f"@{user['username']}" if user['username'] != "N/A" else "Username: None"
            message_lines.append(f"{user['phone']} | ID: {user['id']} | {username_display}")
        message_lines.append("")
    
    if banned:
        message_lines.append("🚫 BANNED ACCOUNTS:")
        message_lines.extend(banned)
        message_lines.append("")
    
    if unregistered:
        message_lines.append("❌ UNREGISTERED ACCOUNTS:")
        message_lines.extend(unregistered)
        message_lines.append("")
    
    if errors:
        message_lines.append("⚠️ ERRORS (could not check):")
        for err in errors:
            message_lines.append(f"{err['phone']} - {err['error']}")
        message_lines.append("")
    
    if invalid:
        message_lines.append("❓ INVALID NUMBERS:")
        message_lines.extend(invalid)
        message_lines.append("")
    
    message_lines.append("🎯 SUMMARY:")
    message_lines.append(f"REGISTERED ✅: {len(registered)}")
    message_lines.append(f"BANNED 🚫: {len(banned)}")
    message_lines.append(f"UNREGISTERED ❌: {len(unregistered)}")
    message_lines.append(f"ERRORS ⚠️: {len(errors)}")
    message_lines.append(f"INVALID ❓: {len(invalid)}")
    
    final_message = "\n".join(message_lines)
    
    await update.message.reply_text(final_message)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    files_to_send = []
    
    if registered:
        registered_file = RESULTS_DIR / f"registered_{ts}.txt"
        with open(registered_file, 'w', encoding='utf-8') as f:
            for user in registered:
                username_display = f"@{user['username']}" if user['username'] != "N/A" else "Username: None"
                f.write(f"{user['phone']} | ID: {user['id']} | {username_display}\n")
        files_to_send.append(registered_file)
    
    if banned:
        banned_file = RESULTS_DIR / f"banned_{ts}.txt"
        with open(banned_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(banned))
        files_to_send.append(banned_file)
    
    if unregistered:
        unregistered_file = RESULTS_DIR / f"unregistered_{ts}.txt"
        with open(unregistered_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(unregistered))
        files_to_send.append(unregistered_file)
    
    if errors:
        errors_file = RESULTS_DIR / f"errors_{ts}.txt"
        with open(errors_file, 'w', encoding='utf-8') as f:
            for err in errors:
                f.write(f"{err['phone']} - {err['error']}\n")
        files_to_send.append(errors_file)
    
    if invalid:
        invalid_file = RESULTS_DIR / f"invalid_{ts}.txt"
        with open(invalid_file, 'w', encoding='utf-8') as f:
            f.write("\n".join(invalid))
        files_to_send.append(invalid_file)
    
    for file_path in files_to_send:
        with open(file_path, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=file_path.name
            )
    
    await update.message.reply_text(
        "✅ Check complete! Send more numbers or upload a file to continue checking."
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "❌ Operation cancelled. Use /start to begin again."
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception while handling an update: {context.error}")


async def post_init(application: Application):
    global checker_service
    try:
        await checker_service.initialize()
        agent_count = agent_manager.get_active_count()
        if agent_count > 0:
            logger.info(f"Checker service initialized with {agent_count} active agent(s)!")
        else:
            logger.warning("No active agents. Users will need to configure agents.")
    except Exception as e:
        logger.error(f"Error during post_init: {e}")


async def post_shutdown(application: Application):
    try:
        await checker_service.shutdown()
        logger.info("Checker service shut down successfully.")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")


def main():
    global agent_manager, checker_service
    
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    
    if not BOT_TOKEN:
        raise ValueError("Missing required environment variable: BOT_TOKEN")
    
    agent_manager = AgentManager()
    checker_service = TelegramCheckerService(agent_manager)
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    setup_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            SETUP_ASK_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_agent_count)],
            SETUP_API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_api_id)],
            SETUP_API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_api_hash)],
            SETUP_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_phone)],
            SETUP_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_otp)],
            SETUP_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, setup_2fa)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="setup_conversation",
        persistent=False,
    )
    
    check_conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            AWAITING_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input),
                MessageHandler(filters.Document.TXT, handle_file_input),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="check_conversation",
        persistent=False,
    )
    
    add_conv = ConversationHandler(
        entry_points=[CommandHandler("addagents", addagents_command)],
        states={
            ADD_ASK_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_agent_count)],
            ADD_API_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_api_id)],
            ADD_API_HASH: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_api_hash)],
            ADD_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_phone)],
            ADD_OTP: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_otp)],
            ADD_2FA: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_2fa)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="add_conversation",
        persistent=False,
    )
    
    delete_conv = ConversationHandler(
        entry_points=[CommandHandler("deleteagents", deleteagents_command)],
        states={
            DELETE_ASK_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_agent_number)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        name="delete_conversation",
        persistent=False,
    )
    
    application.add_handler(setup_conv)
    application.add_handler(check_conv)
    application.add_handler(add_conv)
    application.add_handler(delete_conv)
    application.add_handler(CommandHandler("agents", agents_command))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_input), group=1)
    application.add_handler(MessageHandler(filters.Document.TXT, handle_file_input), group=1)
    
    application.add_error_handler(error_handler)
    
    logger.info("Bot started successfully!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
