import asyncio
from whatsapp_client_python.whatsapp_client import WhatsAppClient

# --- بيانات الجلسة (ثابتة أو محملة من قاعدة بياناتك)
SESSION_NAME = "your_session_name"
API_KEY = "your_whatsapp_api_key"

# --- قائمة الأرقام بصيغة دولية
recipients = [
    "+966500000001",
    "+966500000002",
    "+966500000003"
]

# --- الرسالة التي سيتم إرسالها
message = "🌟 مرحبًا! هذه رسالة تجريبية من نظامك. شكرًا لتجربتك!"

# --- الدالة الرئيسية للإرسال
async def send_bulk_whatsapp(session_name, api_key, numbers, msg):
    async with WhatsAppClient(session_name=session_name, api_key=api_key) as client:
        for number in numbers:
            try:
                print(f"📤 إرسال إلى {number} ...")
                result = client.send_message(number, msg)
                success = await result if asyncio.iscoroutine(result) else result
                if success:
                    print(f"✅ تم الإرسال إلى {number}")
                else:
                    print(f"❌ فشل الإرسال إلى {number}")
            except Exception as e:
                print(f"⚠️ خطأ أثناء الإرسال إلى {number}: {e}")

# --- تنفيذ
if __name__ == "__main__":
    asyncio.run(send_bulk_whatsapp(SESSION_NAME, API_KEY, recipients, message))
