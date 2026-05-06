import asyncio
import logging
import os
import re
import uuid
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from telethon import TelegramClient, errors
from telethon.tl import types
from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest

from agent_manager import AgentManager, AgentCredentials

logger = logging.getLogger(__name__)


@dataclass
class TelegramUser:
    id: int
    username: Optional[str]
    phone: str


def validate_phone_number(phone: str) -> str:
    phone = re.sub(r"[^\d+]", "", phone.strip())
    if not phone.startswith("+"):
        phone = "+" + phone
    if not re.match(r"^\+\d{10,15}$", phone):
        raise ValueError(f"Invalid phone number format: {phone}")
    return phone


async def determine_registration_state(phone: str, api_id: int, api_hash: str, retry_count: int = 0) -> str:
    session = f"_temp_{uuid.uuid4()}"
    client = TelegramClient(session, api_id, api_hash)

    try:
        await client.connect()

        try:
            sent_code = await client.send_code_request(phone)

            code_type = getattr(sent_code, "type", None)
            type_str = (repr(code_type) or "").lower()

            if any(word in type_str for word in
                   ["email", "setemail", "emailrequired", "emailtoken"]):
                return "unregistered"

            phone_registered = getattr(sent_code, "phone_registered", None)
            if phone_registered is False:
                return "unregistered"

            return "registered"

        except errors.PhoneNumberBannedError:
            return "banned"

        except errors.PhoneNumberInvalidError:
            return "invalid"

        except errors.FloodWaitError as e:
            wait = getattr(e, "seconds", 5)
            if wait > 300 or retry_count >= 3:
                logger.error(f"FloodWait too long ({wait}s) or too many retries ({retry_count}), aborting")
                return "error"
            logger.warning(f"FloodWait for {wait} seconds on registration check, retry {retry_count + 1}/3")
            await asyncio.sleep(wait)
            return await determine_registration_state(phone, api_id, api_hash, retry_count + 1)

    finally:
        try:
            await client.disconnect()
        except:
            pass

        for f in os.listdir():
            if f.startswith(session) and (f.endswith('.session') or f.endswith('.session-journal')):
                try:
                    os.remove(f)
                except:
                    pass


class TelegramCheckerService:
    def __init__(self, agent_manager: AgentManager):
        self.agent_manager = agent_manager
        self.clients: Dict[str, TelegramClient] = {}
        self.agent_queue: Optional[asyncio.Queue] = None

    async def initialize(self) -> None:
        self.agent_manager.load_agents()
        
        if not self.agent_manager.has_agents():
            logger.warning("No agents configured. Bot needs at least one agent to function.")
            return
        
        await self.shutdown()
        self.clients.clear()
        
        for agent in self.agent_manager.agents:
            if agent.is_active:
                try:
                    client = TelegramClient(agent.session_name, agent.api_id, agent.api_hash)
                    await client.connect()
                    
                    if not await client.is_user_authorized():
                        logger.warning(f"Agent #{agent.serial_number} ({agent.phone}) is not authorized.")
                        await client.disconnect()
                        continue
                    
                    self.clients[agent.session_name] = client
                    logger.info(f"Agent #{agent.serial_number} ({agent.phone}) initialized successfully.")
                except Exception as e:
                    logger.error(f"Failed to initialize agent #{agent.serial_number}: {e}")
        
        if self.clients:
            logger.info(f"Initialized {len(self.clients)} active agent client(s).")
            
            self.agent_queue = asyncio.Queue()
            for agent in self.agent_manager.agents:
                if agent.is_active and agent.session_name in self.clients:
                    await self.agent_queue.put(agent)

    async def shutdown(self) -> None:
        for client in self.clients.values():
            try:
                await client.disconnect()
            except:
                pass

    async def check_phone(self, phone_raw: str) -> Dict[str, Any]:
        try:
            phone = validate_phone_number(phone_raw)
        except ValueError as e:
            return {"state": "invalid", "error": str(e), "phone": phone_raw}

        if not self.agent_queue:
            return {"state": "error", "error": "No active agents available", "phone": phone}
        
        agent = await self.agent_queue.get()
        
        try:
            return await self._check_phone_with_agent(phone, agent)
        finally:
            await self.agent_queue.put(agent)
    
    async def _check_phone_with_agent(self, phone: str, agent) -> Dict[str, Any]:
        client = self.clients.get(agent.session_name)
        if not client:
            return {"state": "error", "error": f"Agent #{agent.serial_number} client not available", "phone": phone}

        try:
            if not client.is_connected():
                logger.warning(f"Agent #{agent.serial_number} client disconnected, reconnecting...")
                try:
                    await client.connect()
                except Exception as reconnect_error:
                    logger.error(f"Failed to reconnect agent #{agent.serial_number}: {reconnect_error}")
                    return {"state": "error", "error": "Agent connection lost. Try again later.", "phone": phone}
            
            try:
                user = await client.get_entity(phone)
            except errors.FloodWaitError:
                return {"state": "error", "error": "Rate limit reached. Try again later.", "phone": phone}
            except Exception as get_entity_error:
                logger.debug(f"get_entity failed for {phone}, trying contact import: {get_entity_error}")
                try:
                    contact = types.InputPhoneContact(
                        client_id=0, phone=phone, first_name="X", last_name="Y"
                    )
                    result = await client(ImportContactsRequest([contact]))

                    if not result.users:
                        logger.debug(f"Contact import returned no users for {phone}, checking if banned")
                        reg_state = await determine_registration_state(phone, agent.api_id, agent.api_hash)
                        
                        if reg_state == "banned":
                            return {"state": "banned", "error": "Phone number is banned", "phone": phone}
                        elif reg_state == "invalid":
                            return {"state": "invalid", "error": "Invalid phone number", "phone": phone}
                        else:
                            return {"state": "unregistered",
                                    "error": "Unregistered or hidden by privacy settings", "phone": phone}

                    user = result.users[0]
                    try:
                        await client(DeleteContactsRequest(id=[user.id]))
                    except:
                        pass
                except errors.FloodWaitError:
                    return {"state": "error", "error": "Rate limit reached. Try again later.", "phone": phone}
                except Exception as import_error:
                    logger.error(f"Contact import failed for {phone}: {import_error}")
                    return {"state": "error", "error": "Failed to retrieve user information. Try again later.", "phone": phone}

            tg_user = TelegramUser(
                id=user.id,
                username=getattr(user, "username", None),
                phone=phone
            )

            return {"state": "registered", "data": asdict(tg_user), "phone": phone}

        except Exception as e:
            logger.error(f"Unexpected error checking phone {phone} with agent #{agent.serial_number}: {e}")
            return {"state": "error",
                    "error": "An unexpected error occurred. Try again later.", "phone": phone}
