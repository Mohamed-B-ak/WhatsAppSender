"""
Standalone helper / example: build a [{phone, message}, ...] list from a small
in-memory dataset and POST it to a webhook URL — same shape that the FastAPI
`/send-bulk` endpoint uses.

Run directly to test your webhook from the command line:

    python send_whatsapp_campaign.py
"""

import json
import requests

# ---------------------------------------------------------------------------
# 1. Configure your webhook + payload
# ---------------------------------------------------------------------------
WEBHOOK_URL = "https://your-webhook.example.com/endpoint"

# Each item needs at least `name` and `phone`. `name` is used by the
# personalization step; only `phone` and `message` are sent to the webhook.
recipients = [
    {"name": "أحمد",   "phone": "+966500000001"},
    {"name": "سارة",   "phone": "+966500000002"},
    {"name": "محمد",   "phone": "+966500000003"},
]

# Use [الاسم] anywhere in the template to personalize per recipient.
message_template = "🌟 مرحبًا [الاسم]! هذه رسالة تجريبية من نظامك."

REQUEST_TIMEOUT = 60  # seconds


# ---------------------------------------------------------------------------
# 2. Helpers (mirrors the logic in main.py — kept light here)
# ---------------------------------------------------------------------------
def normalize_phone(raw: str) -> str:
    """
    Strip spaces / dashes / '+' and return a clean digits-only string.
    Adjust to your country/format rules as needed.
    """
    return (raw or "").replace(" ", "").replace("-", "").replace("+", "")


def build_payload(recipients_list, template):
    """Return [{phone, message}, ...] ready to POST to the webhook."""
    payload = []
    for r in recipients_list:
        name = (r.get("name") or "").strip()
        phone = normalize_phone(r.get("phone", ""))
        if not name or not phone:
            continue
        payload.append({
            "phone": phone,
            "message": template.replace("[الاسم]", name),
        })
    return payload


def send_to_webhook(url: str, payload):
    """POST the payload as JSON. Returns the response object."""
    print(f"📤 POST {url}  ({len(payload)} entries)")
    resp = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=REQUEST_TIMEOUT,
    )
    print(f"   ↳ HTTP {resp.status_code}")
    print(f"   ↳ Response: {resp.text[:500]}")
    return resp


# ---------------------------------------------------------------------------
# 3. Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    payload = build_payload(recipients, message_template)

    if not payload:
        print("⚠️  No valid recipients — aborting.")
        raise SystemExit(1)

    print("Payload preview:")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    try:
        response = send_to_webhook(WEBHOOK_URL, payload)
        if 200 <= response.status_code < 300:
            print("✅ Webhook accepted the payload.")
        else:
            print("❌ Webhook returned an error.")
    except requests.RequestException as e:
        print(f"⚠️  Request failed: {e}")