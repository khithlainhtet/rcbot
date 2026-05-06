import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List, Tuple
from cryptography.fernet import Fernet
from telethon import TelegramClient, errors

logger = logging.getLogger(__name__)

ENCRYPTION_KEY_FILE = ".encryption_key"
AGENTS_FILE = "agents.encrypted"


@dataclass
class AgentCredentials:
    serial_number: int
    api_id: int
    api_hash: str
    phone: str
    session_name: str
    is_active: bool = True


class AgentManager:
    def __init__(self):
        self.agents: List[AgentCredentials] = []
        self.current_index = 0
        self._lock = asyncio.Lock()
        self._ensure_encryption_key()
        self.cipher = Fernet(self._load_encryption_key())

    def _ensure_encryption_key(self):
        if not Path(ENCRYPTION_KEY_FILE).exists():
            key = Fernet.generate_key()
            with open(ENCRYPTION_KEY_FILE, 'wb') as f:
                f.write(key)
            logger.info("Generated new encryption key.")

    def _load_encryption_key(self) -> bytes:
        with open(ENCRYPTION_KEY_FILE, 'rb') as f:
            return f.read()

    def load_agents(self):
        if not Path(AGENTS_FILE).exists():
            logger.info("No agents file found. Starting fresh.")
            self.agents = []
            return

        try:
            with open(AGENTS_FILE, 'rb') as f:
                encrypted_data = f.read()
            
            if not encrypted_data:
                self.agents = []
                return

            decrypted_data = self.cipher.decrypt(encrypted_data)
            agents_list = json.loads(decrypted_data.decode('utf-8'))
            
            self.agents = [AgentCredentials(**agent) for agent in agents_list]
            logger.info(f"Loaded {len(self.agents)} agent(s).")
        except Exception as e:
            logger.error(f"Failed to load agents: {e}")
            self.agents = []

    def _save_agents(self):
        try:
            agents_list = [asdict(agent) for agent in self.agents]
            json_data = json.dumps(agents_list, indent=2)
            encrypted_data = self.cipher.encrypt(json_data.encode('utf-8'))
            
            with open(AGENTS_FILE, 'wb') as f:
                f.write(encrypted_data)
            
            logger.info("Agents saved successfully.")
        except Exception as e:
            logger.error(f"Failed to save agents: {e}")

    def has_agents(self) -> bool:
        return len(self.agents) > 0

    def get_active_count(self) -> int:
        return sum(1 for agent in self.agents if agent.is_active)

    async def get_next_agent(self) -> Optional[AgentCredentials]:
        async with self._lock:
            active_agents = [a for a in self.agents if a.is_active]
            
            if not active_agents:
                return None
            
            agent = active_agents[self.current_index % len(active_agents)]
            self.current_index += 1
            
            return agent

    async def add_agent(
        self,
        api_id: int,
        api_hash: str,
        phone: str,
        code: str,
        phone_code_hash: str = "",
        password: Optional[str] = None,
        session_name: Optional[str] = None
    ) -> Tuple[bool, str]:
        try:
            if session_name is None:
                serial = len(self.agents) + 1
                session_name = f"agent_{serial}"
            else:
                serial = len(self.agents) + 1

            client = TelegramClient(session_name, api_id, api_hash)
            
            try:
                await client.connect()
                
                if not await client.is_user_authorized():
                    try:
                        if phone_code_hash:
                            await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                        else:
                            sent_code = await client.send_code_request(phone)
                            await client.sign_in(phone, code, phone_code_hash=sent_code.phone_code_hash)
                    except errors.SessionPasswordNeededError:
                        if password:
                            await client.sign_in(password=password)
                        else:
                            await client.disconnect()
                            return False, "2FA password required. Please provide your password."
                    except errors.PhoneCodeExpiredError:
                        await client.disconnect()
                        self._cleanup_session_files(session_name)
                        return False, "Verification code expired. Please start again."
                    except errors.PhoneCodeInvalidError:
                        await client.disconnect()
                        self._cleanup_session_files(session_name)
                        return False, "Invalid verification code. Please check and try again."
                    except Exception as e:
                        await client.disconnect()
                        self._cleanup_session_files(session_name)
                        logger.error(f"Sign-in error: {e}")
                        return False, f"Authentication failed: {str(e)}"
                
                me = await client.get_me()
                await client.disconnect()
                
                agent = AgentCredentials(
                    serial_number=serial,
                    api_id=api_id,
                    api_hash=api_hash,
                    phone=phone,
                    session_name=session_name,
                    is_active=True
                )
                
                self.agents.append(agent)
                self._save_agents()
                
                logger.info(f"Agent #{serial} ({phone}) added successfully.")
                return True, f"✅ Agent #{serial} added: {phone} (@{me.username if me.username else 'no username'})"
                
            except Exception as e:
                try:
                    await client.disconnect()
                except:
                    pass
                self._cleanup_session_files(session_name)
                logger.error(f"Failed to add agent: {e}")
                return False, f"Failed to authenticate: {str(e)}"
                
        except Exception as e:
            logger.error(f"Unexpected error in add_agent: {e}")
            return False, f"Unexpected error: {str(e)}"

    def _cleanup_session_files(self, session_name: str):
        for f in os.listdir():
            if f.startswith(session_name) and (f.endswith('.session') or f.endswith('.session-journal')):
                try:
                    os.remove(f)
                    logger.debug(f"Cleaned up session file: {f}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup {f}: {e}")

    def delete_agent(self, serial_number: int) -> Tuple[bool, str]:
        for i, agent in enumerate(self.agents):
            if agent.serial_number == serial_number:
                self._cleanup_session_files(agent.session_name)
                
                del self.agents[i]
                self._save_agents()
                
                logger.info(f"Agent #{serial_number} deleted.")
                return True, f"Agent #{serial_number} ({agent.phone}) deleted successfully."
        
        return False, f"Agent #{serial_number} not found."

    def get_all_agents(self) -> List[dict]:
        return [
            {
                "serial": agent.serial_number,
                "phone": agent.phone,
                "active": agent.is_active,
                "session": agent.session_name
            }
            for agent in self.agents
        ]

    async def verify_agent_auth(self, agent: AgentCredentials) -> bool:
        try:
            client = TelegramClient(agent.session_name, agent.api_id, agent.api_hash)
            await client.connect()
            
            is_auth = await client.is_user_authorized()
            await client.disconnect()
            
            return is_auth
        except Exception as e:
            logger.error(f"Failed to verify agent #{agent.serial_number}: {e}")
            return False
