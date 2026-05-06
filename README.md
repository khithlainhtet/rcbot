# 🤖 Telegram Phone Number Checker Bot

A professional Telegram bot that checks if phone numbers are registered on Telegram with **multi-agent support** for faster processing and rate limit avoidance.

## ✨ Features

- 🔘 **In-Bot Agent Setup** - Configure agents directly through Telegram chat
- 🔄 **Multi-Agent Rotation** - Use multiple Telegram accounts to distribute requests
- 📝 **Text Input** - Enter numbers directly in chat (one per line or comma-separated)
- 📄 **File Upload** - Upload .txt files with phone numbers
- 📊 **Categorized Results** - Organized display by registration status
- 💾 **Separate .txt Files** - Export results in categorized text files
- 🔐 **Encrypted Storage** - Agent credentials are stored securely
- 🔎 **3-State Detection**:
  - ✅ Registered - ID and username available
  - 🚫 Banned - Number is banned
  - ❌ Unregistered - Not on Telegram + Hidden users
  - ⚠️ **Note**: Users with strict privacy settings cannot be distinguished from unregistered numbers

## 🚀 Quick Start

### 1. Get a Bot Token

1. Open Telegram and find [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow the instructions
3. Copy the bot token and add it to Replit Secrets as `BOT_TOKEN`

### 2. Start the Bot

The bot will start automatically. On first use, it will guide you through setting up agents.

### 3. Configure Agents (In-Bot)

1. Open Telegram and find your bot
2. Send `/start`
3. The bot will ask: "How many agents do you want to add?"
4. Enter a number (recommended: 2-5)
5. For each agent, provide:
   - API ID (from https://my.telegram.org/apps)
   - API Hash (from https://my.telegram.org/apps)
   - Phone number (with country code, e.g., +1234567890)
   - Verification code (sent to that number)
   - 2FA password (if enabled)

### 4. Start Checking Numbers

Once agents are configured, you can:
- Send `/start` to check phone numbers
- Choose to enter manually or upload a file
- Get results with user IDs and usernames

## 📋 Bot Commands

- `/start` - Check phone numbers
- `/agents` - View all configured agents
- `/addagents` - Add new agents
- `/deleteagents` - Remove agents by number

## 🔧 Agent Management

### View Agents
```
/agents
```
Shows all configured agents with their status and serial numbers.

### Add More Agents
```
/addagents
```
Follow the same setup process to add additional agents for better performance.

### Delete Agents
```
/deleteagents
```
Enter the agent number to delete (e.g., `1` to delete Agent #1).

## 📋 Input Formats

### Text Input
```
+1234567890
+9876543210, +1122334455
```

### File Upload (.txt)
```
+1234567890
+9876543210
+1122334455
```

## 📂 Output

### Categorized Display
```
🎯 CHECKING COMPLETED 🎯

✅ REGISTERED ACCOUNTS:
+1234567890
+9876543210

🚫 BANNED ACCOUNTS:
+1122334455

❌ UNREGISTERED ACCOUNTS:
+5556667777

🎯 SUMMARY:
REGISTERED ✅: 2
BANNED 🚫: 1
UNREGISTERED ❌: 1
```

### Exported Files
Separate .txt files for each category:
- `registered_YYYYMMDD_HHMMSS.txt` - Only registered numbers
- `banned_YYYYMMDD_HHMMSS.txt` - Only banned numbers
- `unregistered_YYYYMMDD_HHMMSS.txt` - Only unregistered numbers

Each file contains phone numbers, one per line.

## 🔒 Security

- All agent credentials are encrypted using Fernet encryption
- Session files are protected via `.gitignore`
- Encryption keys are generated automatically and stored securely
- No credentials are logged or exposed

## ⚡ Performance

- **Agent Rotation**: Requests are distributed across agents using round-robin
- **Rate Limit Avoidance**: Multiple agents help avoid Telegram API limits
- **Faster Processing**: More agents = faster batch processing
- **Recommended**: 2-5 agents for optimal performance

## 🔧 Troubleshooting

**Bot doesn't respond:**
- Check that `BOT_TOKEN` is set in Replit Secrets
- Restart the workflow

**"No active agents" error:**
- Use `/start` to configure your first agent
- Or use `/addagents` to add more agents

**Agent authentication failed:**
- Double-check API credentials from https://my.telegram.org/apps
- Ensure you enter the verification code correctly
- Check that 2FA password is correct (if enabled)

**Rate limiting:**
- Add more agents with `/addagents`
- The bot automatically distributes requests across agents

## ⚠️ Important Notes

- This tool is for educational purposes only
- Respect Telegram's terms of service and user privacy
- Each agent uses a separate Telegram account for checking
- Agent credentials are encrypted and stored locally
- Privacy settings may limit profile information retrieval

## 📄 License

MIT License

---

**Enjoy using the bot!** If you have questions or issues, check the troubleshooting section above.
