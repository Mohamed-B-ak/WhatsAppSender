# main.py
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import csv
import io
import re
import random
from typing import List, Dict
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys
import os

import httpx  # async HTTP client used to POST the payload to the user's webhook

# Webhook request timeout (seconds). The webhook receiver should respond quickly
# (typically by ack-ing the payload and queueing actual sending on its side).
WEBHOOK_TIMEOUT = 60.0

# Add the parent directory to path (kept for any other local imports you may add later)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))


app = FastAPI(title="WhatsApp Bulk Messaging System")

# CORS — keep wide-open for now; lock down in production if needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------
def digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone)


def normalize_saudi_phone(raw: str) -> str | None:
    """
    Normalize a phone number string to the 12-digit Saudi format `966XXXXXXXXX`.
    Returns None if the result isn't a valid 12-digit Saudi number.

    Rules (preserved from the original implementation):
      - strip spaces, dashes, '+'
      - drop leading '00966'
      - drop a single leading '0'
      - if it doesn't start with '966', prepend '966'
      - must be exactly 12 digits
    """
    if not raw:
        return None

    phone = raw.strip().replace(" ", "").replace("-", "").replace("+", "")

    if phone.startswith("00966"):
        phone = phone[5:]
    if phone.startswith("0"):
        phone = phone[1:]
    if not phone.startswith("966"):
        phone = "966" + phone

    if len(phone) != 12 or not phone.isdigit():
        return None
    return phone


# Pools used to vary [التحية] (greeting) and [الفريق] (team/agent name) per row,
# so messages don't look identical across recipients.
_GREETING_POOL = [
    "حيّاك الله",
    "السلام عليكم و رحمة الله و بركاته",
    "يسعد أوقاتك",
    "تحية طيبة",
    "يعطيك العافية",
    "يسعد أيامك",
    "يا هلا",
    "أهلًا",
    "السلام عليكم",
]
_TEAM_NAME_POOL = [
    "نور", "سارة", "ريم", "هدى", "فاطمة", "مريم", "جواهر", "شهد",
    "دلال", "نورة", "أروى", "ضحى", "رغد", "سمية", "لمى", "غادة",
    "جنان", "ليان", "سلمى", "زينب",
]


def personalize_message(template: str, name: str) -> str:
    """
    Substitute personalization placeholders and wrap result in RTL markers
    so it renders correctly on Arabic clients.

    Placeholders:
      [الاسم]   -> recipient name
      [التحية] -> random greeting from _GREETING_POOL
      [الفريق] -> random name from _TEAM_NAME_POOL
    """
    msg = template.replace("[الاسم]", name)
    msg = msg.replace("[التحية]", random.choice(_GREETING_POOL))
    msg = msg.replace("[الفريق]", random.choice(_TEAM_NAME_POOL))
    # \u202B = RTL embedding, \u202C = pop directional formatting
    return f"\u202B{msg}\u202C"


# -----------------------------------------------------------------------------
# HTML interface
# -----------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def get_interface():
    return """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>نظام إرسال رسائل WhatsApp الجماعية</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }

        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }

        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.2);
            padding: 40px;
            width: 100%;
            max-width: 600px;
        }

        h1 {
            color: #333;
            margin-bottom: 30px;
            text-align: center;
            font-size: 28px;
        }

        .form-group { margin-bottom: 25px; }

        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 600;
            font-size: 14px;
        }

        input[type="text"],
        input[type="url"],
        textarea {
            width: 100%;
            padding: 12px 15px;
            border: 2px solid #e0e0e0;
            border-radius: 10px;
            font-size: 14px;
            transition: all 0.3s ease;
            font-family: inherit;
        }

        input[type="text"]:focus,
        input[type="url"]:focus,
        textarea:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }

        textarea { min-height: 120px; resize: vertical; }

        .file-upload { position: relative; display: block; width: 100%; }

        .file-upload input[type=file] {
            width: 100%;
            padding: 12px 15px;
            border: 2px dashed #667eea;
            border-radius: 10px;
            background: #f8f9fa;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s ease;
        }

        .file-upload input[type=file]:hover {
            background: #f0f0ff;
            border-color: #764ba2;
        }

        .file-upload input[type=file]::file-selector-button {
            padding: 8px 15px;
            margin-left: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: 600;
        }

        .file-info {
            margin-top: 10px;
            padding: 10px;
            background: #e8f5e9;
            border-radius: 5px;
            font-size: 13px;
            color: #2e7d32;
            display: none;
        }

        .btn {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            padding: 14px 30px;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            transition: all 0.3s ease;
        }

        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
        }

        .btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }

        .progress {
            display: none;
            margin-top: 20px;
            padding: 20px;
            background: #f5f5f5;
            border-radius: 10px;
            text-align: center;
        }
        .progress.active { display: block; }

        .spinner {
            display: inline-block;
            width: 30px;
            height: 30px;
            border: 3px solid #e0e0e0;
            border-top-color: #667eea;
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin-bottom: 10px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        .result {
            margin-top: 20px;
            padding: 15px;
            border-radius: 10px;
            display: none;
        }
        .result.success { background: #e8f5e9; color: #2e7d32; border: 1px solid #4caf50; }
        .result.error   { background: #ffebee; color: #c62828; border: 1px solid #f44336; }

        .stats {
            display: flex;
            justify-content: space-around;
            margin-top: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 10px;
        }
        .stat { text-align: center; }
        .stat-number { font-size: 24px; font-weight: bold; color: #667eea; }
        .stat-label  { font-size: 12px; color: #666; margin-top: 5px; }

        .note {
            background: #fff3cd;
            border: 1px solid #ffc107;
            color: #856404;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 13px;
        }

        pre {
            background: #f4f4f4;
            padding: 10px;
            border-radius: 6px;
            overflow-x: auto;
            font-size: 12px;
            text-align: left;
            direction: ltr;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📱 نظام إرسال رسائل WhatsApp الجماعية</h1>

        <div class="note">
            💡 يمكنك استخدام <b>[الاسم]</b> في الرسالة وسيتم استبداله باسم العميل.
            سيتم إرسال القائمة الكاملة <b>[{phone, message}, ...]</b> إلى الـ Webhook URL الذي تحدده.
        </div>

        <form id="bulkForm">
            <div class="form-group">
                <label for="webhook_url">🔗 رابط الـ Webhook</label>
                <input type="url" id="webhook_url" name="webhook_url" required
                       placeholder="https://your-webhook.example.com/endpoint">
            </div>

            <div class="form-group">
                <label for="message">✉️ الرسالة</label>
                <textarea id="message" name="message" required
                          placeholder="اكتب رسالتك هنا... يمكنك استخدام [الاسم] ليتم استبداله باسم العميل"></textarea>
            </div>

            <div class="form-group">
                <label for="csvFile">📄 رفع ملف CSV (يحتوي على عمود name وعمود phone)</label>
                <div class="file-upload">
                    <input type="file" id="csvFile" name="csvFile" accept=".csv" required>
                </div>
                <div class="file-info" id="fileInfo"></div>
            </div>

            <button type="submit" class="btn" id="sendBtn">🚀 إرسال إلى الـ Webhook</button>
        </form>

        <div class="progress" id="progress">
            <div class="spinner"></div>
            <div id="progressText">جاري إرسال القائمة إلى الـ Webhook...</div>
        </div>

        <div class="result" id="result"></div>
    </div>

    <script>
        const form = document.getElementById('bulkForm');
        const fileInput = document.getElementById('csvFile');
        const fileInfo = document.getElementById('fileInfo');
        const progress = document.getElementById('progress');
        const progressText = document.getElementById('progressText');
        const result = document.getElementById('result');
        const sendBtn = document.getElementById('sendBtn');

        fileInput.addEventListener('change', function(e) {
            const file = e.target.files[0];
            if (file) {
                fileInfo.style.display = 'block';
                fileInfo.textContent = `✅ تم اختيار الملف: ${file.name} (${(file.size / 1024).toFixed(2)} KB)`;
            }
        });

        form.addEventListener('submit', async function(e) {
            e.preventDefault();

            const formData = new FormData();
            formData.append('webhook_url', document.getElementById('webhook_url').value);
            formData.append('message', document.getElementById('message').value);
            formData.append('file', fileInput.files[0]);

            sendBtn.disabled = true;
            progress.classList.add('active');
            result.style.display = 'none';
            progressText.textContent = '⏳ جاري بناء القائمة وإرسالها إلى الـ Webhook...';

            try {
                const response = await fetch('/send-bulk', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                progress.classList.remove('active');

                if (!response.ok) {
                    result.className = 'result error';
                    result.innerHTML = `❌ خطأ: ${data.detail || 'حدث خطأ في الإرسال'}`;
                    result.style.display = 'block';
                    sendBtn.disabled = false;
                    return;
                }

                const ok = data.status === 'delivered';
                result.className = ok ? 'result success' : 'result error';
                result.innerHTML = `
                    <div style="font-size: 18px; margin-bottom: 15px;">
                        ${ok ? '✅ تم إرسال القائمة إلى الـ Webhook' : '⚠️ الـ Webhook رد بخطأ'}
                    </div>
                    <div class="stats">
                        <div class="stat">
                            <div class="stat-number">${data.total_sent_to_webhook}</div>
                            <div class="stat-label">عناصر مُرسلة</div>
                        </div>
                        <div class="stat">
                            <div class="stat-number">${data.total_skipped}</div>
                            <div class="stat-label">صفوف متجاوزة</div>
                        </div>
                        <div class="stat">
                            <div class="stat-number">${data.webhook_status_code}</div>
                            <div class="stat-label">HTTP status</div>
                        </div>
                    </div>
                    <details style="margin-top: 15px;">
                        <summary style="cursor: pointer; color: #667eea;">معاينة أول 3 عناصر</summary>
                        <pre>${JSON.stringify(data.preview, null, 2)}</pre>
                    </details>
                    <details style="margin-top: 10px;">
                        <summary style="cursor: pointer; color: #667eea;">رد الـ Webhook</summary>
                        <pre>${typeof data.webhook_response === 'string'
                            ? data.webhook_response
                            : JSON.stringify(data.webhook_response, null, 2)}</pre>
                    </details>
                    ${data.total_skipped > 0 ? `
                    <details style="margin-top: 10px;">
                        <summary style="cursor: pointer; color: #c62828;">الصفوف المتجاوزة (${data.total_skipped})</summary>
                        <pre>${JSON.stringify(data.skipped, null, 2)}</pre>
                    </details>` : ''}
                `;
                result.style.display = 'block';
                sendBtn.disabled = false;
            } catch (error) {
                progress.classList.remove('active');
                result.className = 'result error';
                result.innerHTML = `❌ خطأ في الاتصال: ${error.message}`;
                result.style.display = 'block';
                sendBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
    """


# -----------------------------------------------------------------------------
# Bulk send: build [{phone, message}, ...] from CSV and POST to webhook URL
# -----------------------------------------------------------------------------
@app.post("/send-bulk")
async def send_bulk_messages(
    webhook_url: str = Form(...),
    message: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Read CSV, normalize phones, personalize messages, then POST the resulting
    list `[{phone, message}, ...]` as JSON to the user-supplied webhook URL.

    CSV must contain `name` and `phone` columns.
    """
    # ---- Validate webhook URL ----
    if not webhook_url.lower().startswith(("http://", "https://")):
        raise HTTPException(
            status_code=400,
            detail="webhook_url must start with http:// or https://",
        )

    # ---- Validate file type ----
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a CSV file")

    # ---- Read & decode CSV ----
    contents = await file.read()
    csv_text = None
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            csv_text = contents.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if csv_text is None:
        raise HTTPException(status_code=400, detail="Could not decode CSV file")

    csv_reader = csv.DictReader(io.StringIO(csv_text))
    fieldnames = csv_reader.fieldnames or []
    if "name" not in fieldnames or "phone" not in fieldnames:
        raise HTTPException(
            status_code=400,
            detail="CSV must have 'name' and 'phone' columns",
        )

    # ---- Build payload ----
    payload: List[Dict[str, str]] = []
    skipped: List[Dict[str, str]] = []

    for row_num, row in enumerate(csv_reader, start=2):  # row 1 is header
        try:
            name = (row.get("name") or "").strip()
            raw_phone = (row.get("phone") or "").strip()
            phone = normalize_saudi_phone(raw_phone) if raw_phone else None

            if not name or not phone:
                skipped.append({
                    "row": row_num,
                    "name": name,
                    "phone": raw_phone,
                    "reason": "missing or invalid name/phone",
                })
                continue

            payload.append({
                "phone": phone,
                "message": personalize_message(message, name),
            })
        except Exception as e:
            skipped.append({
                "row": row_num,
                "name": row.get("name", ""),
                "phone": row.get("phone", ""),
                "reason": f"row processing error: {e}",
            })
            continue

    if not payload:
        raise HTTPException(
            status_code=400,
            detail=(
                "No valid recipients found in CSV. "
                "Make sure 'name' and 'phone' columns have data."
            ),
        )

    # ---- POST the entire list to the webhook URL in a single request ----
    try:
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT) as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Webhook request timed out")
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Webhook request failed: {e}")

    # Try to surface webhook response as JSON, fall back to text.
    try:
        webhook_response = response.json()
    except Exception:
        webhook_response = response.text

    delivered = 200 <= response.status_code < 300

    print(
        f"[/send-bulk] Posted {len(payload)} entries to {webhook_url} "
        f"-> HTTP {response.status_code} ({'OK' if delivered else 'ERROR'})"
    )

    return JSONResponse(content={
        "status": "delivered" if delivered else "webhook_error",
        "webhook_url": webhook_url,
        "webhook_status_code": response.status_code,
        "webhook_response": webhook_response,
        "total_sent_to_webhook": len(payload),
        "total_skipped": len(skipped),
        "skipped": skipped,
        "preview": payload[:3],  # first 3 entries to confirm shape on the UI
    })


# -----------------------------------------------------------------------------
# Email interface (unchanged)
# -----------------------------------------------------------------------------
@app.get("/email", response_class=HTMLResponse)
async def get_email_interface():
    """HTML form for sending bulk emails"""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>📧 Bulk Email Sender</title>
        <style>
            body {
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #36D1DC 0%, #5B86E5 100%);
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
            }
            .container {
                background: white;
                padding: 40px;
                border-radius: 15px;
                width: 100%;
                max-width: 600px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            h1 { text-align: center; margin-bottom: 20px; }
            input, textarea {
                width: 100%;
                margin-bottom: 15px;
                padding: 10px;
                border: 2px solid #ddd;
                border-radius: 8px;
                font-size: 14px;
            }
            button {
                width: 100%;
                background: #5B86E5;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
            }
            button:hover { background: #36D1DC; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📧 Bulk Email Sender</h1>
            <form id="emailForm">
                <input type="text" name="sender_email" placeholder="Your Gmail address" required>
                <input type="password" name="app_password" placeholder="Your App Password" required>
                <input type="text" name="subject" placeholder="Email Subject" required>
                <textarea name="body" placeholder="Message body. Use [name] for personalization" required></textarea>
                <input type="file" name="file" accept=".csv" required>
                <button type="submit">🚀 Send Emails</button>
            </form>
            <div id="result" style="margin-top:20px;"></div>

            <script>
                const form = document.getElementById('emailForm');
                form.addEventListener('submit', async (e) => {
                    e.preventDefault();
                    const formData = new FormData(form);
                    const result = document.getElementById('result');
                    result.textContent = '⏳ Sending... Please wait.';

                    const response = await fetch('/send-email', {
                        method: 'POST',
                        body: formData
                    });
                    const data = await response.json();
                    if (response.ok) {
                        result.innerHTML = `<b>✅ Sent:</b> ${data.sent} | <b>❌ Failed:</b> ${data.failed} | Total: ${data.total}`;
                    } else {
                        result.innerHTML = `❌ Error: ${data.detail}`;
                    }
                });
            </script>
        </div>
    </body>
    </html>
    """


@app.post("/send-email")
async def send_bulk_emails(
    sender_email: str = Form(...),
    app_password: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Send personalized bulk emails from a CSV file.
    CSV columns required: name, email
    """
    try:
        if not file.filename.endswith(".csv"):
            raise HTTPException(status_code=400, detail="File must be a CSV file")

        contents = await file.read()
        try:
            csv_text = contents.decode("utf-8")
        except UnicodeDecodeError:
            csv_text = contents.decode("latin-1")

        reader = csv.DictReader(io.StringIO(csv_text))
        if "email" not in reader.fieldnames or "name" not in reader.fieldnames:
            raise HTTPException(
                status_code=400,
                detail="CSV must have 'name' and 'email' columns",
            )

        recipients = [r for r in reader if r.get("email")]

        # Connect to Gmail SMTP
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)

        results = {"sent": 0, "failed": 0, "total": len(recipients), "details": []}

        for r in recipients:
            try:
                personalized_body = body.replace("[name]", r["name"])
                msg = MIMEMultipart()
                msg["From"] = sender_email
                msg["To"] = r["email"]
                msg["Subject"] = subject
                msg.attach(MIMEText(personalized_body, "plain"))
                server.send_message(msg)
                results["sent"] += 1
                results["details"].append({"email": r["email"], "name": r["name"], "status": "✅ Sent"})
                await asyncio.sleep(1)
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"email": r["email"], "error": str(e)})

        server.quit()
        return JSONResponse(content=results)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -----------------------------------------------------------------------------
# Health / test
# -----------------------------------------------------------------------------
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "WhatsApp Bulk Messaging System"}


@app.get("/test")
async def test_endpoint():
    return {"message": "Server is running!", "status": "OK"}


if __name__ == "__main__":
    import uvicorn
    print("Starting WhatsApp Bulk Messaging System...")
    print("Access the interface at: http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)