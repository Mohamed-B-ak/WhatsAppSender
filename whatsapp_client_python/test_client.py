"""
Test script for Python WhatsApp Client
Tests the functionality similar to the Node.js version
"""

import asyncio
import sys
import os

# Add the parent directory to the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from whatsapp_client_python import WhatsAppClient


async def test_whatsapp_client():
    """Test the WhatsApp client functionality"""
    print("🚀 Testing Python WhatsApp Client")
    print("=" * 50)

    # Initialize client with credentials
    client = WhatsAppClient(
        session_name="685c1019b12fc82021121258_jalsa09",
        server_url="https://siyadah-whatsapp-saas.onrender.com",
        api_key="comp_mc7mcc35p1c_ztn52oisa8t")

    try:
        # Test connection
        print("🔍 Testing connection...")
        connection_results = await client.test_connection()
        print(f"Connection results: {connection_results}")

        # Test status
        print("\n📊 Getting status...")
        status = client.get_status()
        print(f"Status: {status}")

        # Test single message using ONLY custom API (no fallbacks)
        print("\n📱 Testing message via custom API only...")
        result = await client.send_message(
            phone="+21621219217",
            message="مرحبا سحر! هذه رسالة اختبار من Python WhatsApp Client")
        print(f"Message result: {result}")

        # Test bulk messaging
        print("\n📮 Testing bulk messaging...")
        recipients = [{
            "phone": "+21621219217",
            "message": "رسالة جماعية للعميل سحر"
        }, {
            "phone": "+966555123456",
            "message": "رسالة جماعية للعميل التجريبي"
        }]

        bulk_results = await client.send_bulk_messages(recipients, delay=1)
        print(f"Bulk results: {bulk_results}")

        print("\n✅ Python WhatsApp Client test completed successfully!")

    except Exception as e:
        print(f"❌ Test error: {e}")

    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(test_whatsapp_client())
