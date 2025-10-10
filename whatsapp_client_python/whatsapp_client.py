"""
WhatsApp Client - Python Library
Easy-to-use WhatsApp messaging client with working authentication
Based on the Node.js WhatsApp client architecture
"""

import asyncio
import aiohttp
import json
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime
import requests

@dataclass
class MessageInfo:
    """Structure for incoming message information"""
    from_number: str
    body: str
    type: str
    timestamp: float
    session: str
    event: str


class WhatsAppClient:
    """Python WhatsApp client with authentication and messaging capabilities"""

    def __init__(self,
                 session_name: str = "mohamed_session",
                 server_url: Optional[str] = None,
                 api_key: Optional[str] = None):
        """
        Initialize WhatsApp client

        Args:
            session_name: Name of the WhatsApp session
            server_url: Server URL (optional, uses default if not provided)
            api_key: Master API Key (for identification purposes)
        """
        self.session_name = session_name
        self.server_url = server_url or "https://siyadah-whatsapp-saas.onrender.com"
        self.api_key = api_key
        self.secret_key: Optional[str] = None
        self.auth_token: Optional[str] = None
        self.authenticated = False

        # Webhook functionality
        self.webhook_running = False
        self.webhook_port: Optional[int] = None
        self.message_callback: Optional[Callable] = None
        self.received_messages: List[MessageInfo] = []

        # Session for HTTP requests
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession()
        await self._authenticate()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()

    async def _authenticate(self) -> bool:
        """Internal authentication method"""
        try:
            if not self.session:
                self.session = aiohttp.ClientSession()

            # Step 1: Get secret key
            async with self.session.get(
                    f"{self.server_url}/api/secret-key",
                    timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    self.secret_key = data.get("secretKey", "")
                else:
                    print(f"❌ Failed to get secret key: {response.status}")
                    return False

            # Step 2: Generate auth token
            async with self.session.post(
                    f"{self.server_url}/api/{self.session_name}/{self.secret_key}/generate-token",
                    timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 201:
                    data = await response.json()
                    self.auth_token = data.get("full", "")
                    self.authenticated = True
                    print(
                        f"✅ WhatsApp authentication successful for session: {self.session_name}"
                    )
                    return True
                else:
                    print(
                        f"❌ Failed to generate auth token: {response.status}")
                    return False

        except Exception as e:
            print(f"❌ Authentication error: {e}")
            return False

    async def is_connected(self) -> bool:
        """Check if WhatsApp session is connected"""
        if not self.authenticated:
            return False

        try:
            async with self.session.get(
                    f"{self.server_url}/api/{self.session_name}/check-connection-session",
                    headers={"Authorization": f"Bearer {self.auth_token}"},
                    timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("status") == "CONNECTED"
                return False
        except Exception as e:
            print(f"❌ Connection check error: {e}")
            return False

    

    def send_message(self, phone: str, message: str) -> bool:
        """
        Send a WhatsApp message (synchronous version).
        """
        if not self.authenticated:
            if not self._authenticate():  # also needs to be rewritten sync
                return False

        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.auth_token}"
            }

            payload = {"phone": phone, "message": message}

            resp = requests.post(
                f"{self.server_url}/api/{self.session_name}/send-message",
                json=payload,
                headers=headers,
                timeout=30
            )

            if resp.status_code in [200, 201]:
                print(f"✅ Message sent successfully to {phone}")
                return True
            else:
                print(f"❌ Message send failed: {resp.status_code}")
                return False

        except Exception as e:
            print(f"❌ Send error: {e}")
            return False


    async def send_bulk_messages(self,
                                 recipients: List[Dict[str, str]],
                                 delay: int = 2) -> Dict[str, Any]:
        """
        Send messages to multiple recipients

        Args:
            recipients: List of dictionaries with 'phone' and 'message' keys
            delay: Delay between messages in seconds

        Returns:
            Results summary dictionary
        """
        results = {"sent": 0, "failed": 0, "details": []}

        for recipient in recipients:
            phone = recipient.get("phone")
            message = recipient.get("message")

            if not phone or not message:
                results["failed"] += 1
                results["details"].append({
                    "phone": phone,
                    "status": "failed",
                    "error": "Missing phone or message"
                })
                continue

            success = await self.send_message(phone, message)
            if success:
                results["sent"] += 1
                results["details"].append({"phone": phone, "status": "sent"})
            else:
                results["failed"] += 1
                results["details"].append({"phone": phone, "status": "failed"})

            if delay > 0:
                await asyncio.sleep(delay)

        return results

    def get_status(self) -> Dict[str, Any]:
        """Get detailed status information"""
        return {
            "session_name": self.session_name,
            "server_url": self.server_url,
            "api_key": self.api_key or None,
            "authenticated": self.authenticated,
            "webhook_running": self.webhook_running,
            "webhook_port": self.webhook_port,
            "auth_method":
            "API Key + Token Auth" if self.api_key else "Token Auth Only",
            "timestamp": datetime.now().isoformat()
        }

    async def refresh_authentication(self) -> bool:
        """Refresh authentication tokens"""
        return await self._authenticate()

    def get_received_messages(self) -> List[MessageInfo]:
        """Get all received messages"""
        return self.received_messages.copy()

    def clear_received_messages(self):
        """Clear all received messages"""
        self.received_messages.clear()
        print("✅ Received messages cleared")

    def generate_whatsapp_web_link(self, phone: str, message: str) -> str:
        """Generate WhatsApp Web link as fallback"""
        clean_phone = phone.replace("+", "").replace(" ", "").replace("-", "")
        encoded_message = message[:100]  # Limit message length for URL
        return f"https://wa.me/{clean_phone}?text={encoded_message}"

    async def send_message_with_fallback(
            self,
            phone: str,
            message: str,
            customer_name: str = "") -> Dict[str, Any]:
        """
        Send WhatsApp message with fallback to WhatsApp Web link

        Args:
            phone: Phone number
            message: Message text
            customer_name: Customer name for logging

        Returns:
            Dictionary with success status and details
        """
        try:
            # Try to send via API first
            success = await self.send_message(phone, message)

            if success:
                return {
                    "success": True,
                    "method": "api",
                    "phone": phone,
                    "message": message,
                    "customer_name": customer_name
                }
            else:
                # Generate WhatsApp Web link as fallback
                web_link = self.generate_whatsapp_web_link(phone, message)
                print(
                    f"📱 WhatsApp Web link generated for {customer_name}: {web_link}"
                )

                return {
                    "success": True,
                    "method": "web_link",
                    "phone": phone,
                    "message": message,
                    "customer_name": customer_name,
                    "web_link": web_link
                }

        except Exception as e:
            # Emergency fallback
            web_link = self.generate_whatsapp_web_link(phone, message)
            print(f"❌ WhatsApp API error: {e}")
            print(
                f"📱 Emergency WhatsApp Web link for {customer_name}: {web_link}"
            )

            return {
                "success": True,
                "method": "emergency_fallback",
                "phone": phone,
                "message": message,
                "customer_name": customer_name,
                "web_link": web_link,
                "error": str(e)
            }

    async def test_connection(self) -> Dict[str, Any]:
        """Test all connection aspects"""
        results = {
            "server_reachable": False,
            "authentication": False,
            "session_connected": False,
            "overall_status": "failed"
        }

        try:
            # Test server reachability
            async with self.session.get(
                    f"{self.server_url}/api/secret-key",
                    timeout=aiohttp.ClientTimeout(total=5)) as response:
                results["server_reachable"] = response.status == 200

            # Test authentication
            results["authentication"] = await self._authenticate()

            # Test session connection
            if results["authentication"]:
                results["session_connected"] = await self.is_connected()

            # Overall status
            if results["server_reachable"] and results["authentication"]:
                results["overall_status"] = "connected" if results[
                    "session_connected"] else "authenticated"
            elif results["server_reachable"]:
                results["overall_status"] = "server_reachable"
            else:
                results["overall_status"] = "server_unreachable"

        except Exception as e:
            results["error"] = str(e)

        return results

    async def close(self):
        """Close the HTTP session"""
        if self.session:
            await self.session.close()

    def __del__(self):
        """Cleanup on deletion"""
        if self.session and not self.session.closed:
            try:
                asyncio.create_task(self.session.close())
            except:
                pass
