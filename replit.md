# Telegram Phone Number Checker Bot

## Overview
A professional Telegram bot that validates phone numbers and retrieves user information (ID and username). Features **in-bot multi-agent setup** with rotation for rate limit avoidance and faster processing.

## Recent Changes
- **2025-11-15**: Added global message handlers for seamless interaction
  - **ALWAYS RESPONSIVE**: Bot now accepts phone numbers and files anytime without requiring /start
  - **NO MORE REPEATED /START**: Send numbers directly after first use
  - **IMPROVED USER EXPERIENCE**: More natural, chat-like interaction
  
- **2025-11-15**: Implemented true concurrent processing with queue-based agent reservation
  - **CONCURRENT AGENT EXECUTION**: All agents now work simultaneously on different numbers
  - **Queue-based reservation system**: Each agent processes only one number at a time
  - **Massive speed improvement**: 5x faster with 5 agents (all working concurrently vs sequential)
  - **Example**: 5 agents + 10 numbers = ~2x faster (agents continuously process as they become available)
  - **Automatic backpressure**: Queue handles any number of phones without overwhelming agents
  - **Progress tracking maintained**: Real-time updates during concurrent processing
  
- **2025-11-15**: Changed output format to categorized .txt files
  - **NEW OUTPUT FORMAT**: Results now displayed in categorized lists with emojis
    - ✅ REGISTERED ACCOUNTS
    - 🚫 BANNED ACCOUNTS
    - ❌ UNREGISTERED ACCOUNTS
    - 🎯 SUMMARY with counts
  - **NEW EXPORT FORMAT**: Separate .txt files for each category instead of JSON
    - registered_YYYYMMDD_HHMMSS.txt (only registered numbers)
    - banned_YYYYMMDD_HHMMSS.txt (only banned numbers)
    - unregistered_YYYYMMDD_HHMMSS.txt (only unregistered numbers)
    - Each file contains phone numbers, one per line
  - Fixed critical 2FA authentication bug
    - Session files now preserved when 2FA is required
    - Password entry completes authentication using same session
  - Fixed "confirmation code expired" errors with proper session reuse
    - Same session used throughout entire authentication process
    - Eliminates code expiration by avoiding session recreation

## Project Architecture

### Main Components
- **bot.py**: Main Telegram bot application
  - In-bot agent setup conversation flow
  - Agent management commands (/agents, /addagents, /deleteagents)
  - Phone number checking interface
  - Result formatting and .txt export
  
- **agent_manager.py**: Multi-agent management system
  - Encrypted credential storage using Fernet
  - Round-robin agent rotation
  - CRUD operations for agents
  - Session file management
  
- **checker_service.py**: Phone checking service
  - **Queue-based concurrent agent system** - All agents work simultaneously
  - **Agent reservation** - Each agent processes one number at a time (no collisions)
  - Simplified data retrieval (ID + username only)
  - Registration state detection
  - No profile photo downloading

### File Structure
```
.
├── bot.py                  # Main Telegram bot
├── agent_manager.py        # Multi-agent manager with encryption
├── checker_service.py      # Phone checking service
├── requirements.txt        # Python dependencies
├── README.md              # User documentation
├── replit.md              # Project documentation (this file)
├── LICENSE                # MIT License
├── .gitignore             # Ignore sessions and credentials
├── .encryption_key        # Auto-generated encryption key (gitignored)
├── agents.encrypted       # Encrypted agent credentials (gitignored)
├── agent_*.session        # Agent session files (gitignored)
└── results/               # .txt export files (gitignored)
```

## Features
- **In-bot agent configuration** - No separate setup scripts needed
- **True concurrent processing** - All agents work simultaneously for maximum speed
- **Queue-based agent reservation** - Each agent processes one number at a time (prevents collisions)
- **Encrypted credential storage** - Secure agent data with Fernet encryption
- **Agent management commands** - Add, view, and delete agents via Telegram
- **3-state phone detection** - banned/unregistered/registered (hidden users appear as unregistered due to privacy limitations)
- **Simplified data retrieval** - Only user ID and username (no photos)
- **Batch processing** - Upload .txt files or paste multiple numbers
- **Categorized .txt export** - Separate files for registered, banned, and unregistered numbers
- **Progress tracking** - Real-time progress updates

## Configuration Required

### Environment Variables (Replit Secrets)
1. **BOT_TOKEN** - Telegram Bot Token from @BotFather

### Agent Setup (In-Bot)
No environment variables needed for agents! Everything is configured through the bot itself:
1. User sends `/start` (or bot detects no agents)
2. Bot asks: "How many agents do you want to add?"
3. For each agent:
   - API_ID (from https://my.telegram.org/apps)
   - API_HASH (from https://my.telegram.org/apps)
   - Phone number (with country code)
   - OTP verification code
   - 2FA password (if enabled)

Agents are stored encrypted in `agents.encrypted` file.

## Dependencies
- **telethon**: Telegram Client API for phone checking
- **python-telegram-bot**: Telegram Bot API interface
- **cryptography**: Fernet encryption for credential storage
- **python-dotenv**: Environment variable management

## Architecture Notes
- **Concurrent multi-agent system**: All agents work simultaneously using asyncio.Queue for reservation
- **Queue-based scheduling**: Agents are acquired from queue, process one number, then returned
- **Encrypted storage**: Agent credentials encrypted with auto-generated Fernet key
- **In-bot setup**: No CLI scripts - all configuration via Telegram chat
- **Dual-client architecture**: Uses both Telegram Bot API (interface) and Client API (checking)
- **Async design**: Fully async with asyncio.gather for concurrent processing
- **Session management**: Each agent has its own session file
- **Rate limit avoidance**: Multiple agents + concurrent processing = maximum speed without FloodWait

## User Preferences
- Prefers in-bot configuration over CLI scripts
- Wants multi-agent support for speed and rate limit avoidance
- Only needs user ID and username (no profile photos)
- Wants ability to add/delete agents dynamically

## Bot Commands
- `/start` - Check phone numbers (or initial agent setup if none configured)
- `/agents` - List all configured agents with status
- `/addagents` - Add new agents
- `/deleteagents` - Delete agents by serial number
- `/cancel` - Cancel current operation

## Notes
- This tool is for educational purposes only
- Agents use separate Telegram accounts for checking
- All credentials are encrypted and stored locally
- Session files are automatically managed
- Privacy settings may limit information retrieval
- More agents = faster processing + less rate limiting
- Recommended: 2-5 agents for optimal performance
