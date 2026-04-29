# main.py
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import csv
import io
from typing import List, Dict, Tuple
import smtplib
import pandas as pd
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pydantic import BaseModel
import sys
import os

import httpx  # NEW: async HTTP client for wasenderapi.com
import uuid
import random
from datetime import datetime, timezone
from collections import OrderedDict

whatsapp_queue = asyncio.Queue()

# Per-batch results so the UI can poll progress while the worker drains the queue.
# OrderedDict lets us evict the oldest batch when we exceed MAX_BATCHES.
MAX_BATCHES = 100
batch_results: "OrderedDict[str, dict]" = OrderedDict()

# Random per-message delay window (seconds) — 2 to 3 minutes
MIN_DELAY_SECONDS = 120
MAX_DELAY_SECONDS = 180


def _evict_old_batches():
    """Drop oldest batches if we're over the cap."""
    while len(batch_results) > MAX_BATCHES:
        batch_results.popitem(last=False)

# Add the parent directory to path (kept for any other local imports you may add later)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# -----------------------------------------------------------------------------
# wasenderapi.com integration
# -----------------------------------------------------------------------------
WASENDER_API_URL = "https://wasenderapi.com/api/send-message"
WASENDER_TIMEOUT = 30.0  # seconds


async def send_whatsapp_via_wasender(
    api_key: str,
    phone: str,
    text: str,
    http_client: httpx.AsyncClient,
) -> Tuple[bool, str]:
    """
    Send a single WhatsApp message via wasenderapi.com.

    Returns (success, info). On failure, `info` contains the error message
    (HTTP status + body, or exception message).
    """
    # The API expects E.164 format with a leading '+'.
    # Our CSV normalization strips '+', so re-add it here.
    to = phone if phone.startswith("+") else f"+{phone}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"to": to, "text": text}

    try:
        response = await http_client.post(
            WASENDER_API_URL,
            headers=headers,
            json=payload,
            timeout=WASENDER_TIMEOUT,
        )
    except httpx.TimeoutException:
        return False, "request timed out"
    except httpx.RequestError as e:
        return False, f"request error: {e}"

    if 200 <= response.status_code < 300:
        return True, f"HTTP {response.status_code}"

    # Try to extract a useful error message from the response body
    try:
        body = response.json()
        err_msg = body.get("message") or body.get("error") or str(body)
    except Exception:
        err_msg = response.text or "<empty body>"

    return False, f"HTTP {response.status_code}: {err_msg}"


app = FastAPI(title="WhatsApp Bulk Messaging System")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BulkMessageRequest(BaseModel):
    api_key: str
    message: str
    recipients: List[Dict[str, str]]


# HTML Interface
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
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
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
        
        .form-group {
            margin-bottom: 25px;
        }
        
        label {
            display: block;
            margin-bottom: 8px;
            color: #555;
            font-weight: 600;
            font-size: 14px;
        }
        
        input[type="text"],
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
        textarea:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        textarea {
            min-height: 120px;
            resize: vertical;
        }
        
        .file-upload {
            position: relative;
            display: block;
            width: 100%;
        }
        
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
        
        .file-upload label:hover {
            background: #f0f0ff;
            border-color: #764ba2;
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
            position: relative;
            overflow: hidden;
        }
        
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 30px rgba(102, 126, 234, 0.4);
        }
        
        .btn:disabled {
            opacity: 0.6;
            cursor: not-allowed;
            transform: none;
        }
        
        .progress {
            display: none;
            margin-top: 20px;
            padding: 20px;
            background: #f5f5f5;
            border-radius: 10px;
            text-align: center;
        }
        
        .progress.active {
            display: block;
        }
        
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
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .result {
            margin-top: 20px;
            padding: 15px;
            border-radius: 10px;
            display: none;
        }
        
        .result.success {
            background: #e8f5e9;
            color: #2e7d32;
            border: 1px solid #4caf50;
        }
        
        .result.error {
            background: #ffebee;
            color: #c62828;
            border: 1px solid #f44336;
        }
        
        .stats {
            display: flex;
            justify-content: space-around;
            margin-top: 15px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 10px;
        }
        
        .stat {
            text-align: center;
        }
        
        .stat-number {
            font-size: 24px;
            font-weight: bold;
            color: #667eea;
        }
        
        .stat-label {
            font-size: 12px;
            color: #666;
            margin-top: 5px;
        }
        
        .note {
            background: #fff3cd;
            border: 1px solid #ffc107;
            color: #856404;
            padding: 12px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 13px;
        }
        
        /* Additional style for better file input appearance */
        input[type="file"]::-webkit-file-upload-button {
            padding: 8px 15px;
            margin-left: 10px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: 600;
        }
        
        input[type="file"]::-webkit-file-upload-button:hover {
            background: linear-gradient(135deg, #764ba2 0%, #667eea 100%);
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>📱 نظام إرسال رسائل WhatsApp الجماعية</h1>
        
        <div class="note">
            💡 يمكنك استخدام [الاسم] في الرسالة وسيتم استبداله باسم العميل تلقائياً
        </div>
        
        <form id="bulkForm">
            <div class="form-group">
                <label for="api_key">مفتاح API (Wasender Bearer Token)</label>
                <input type="text" id="api_key" name="api_key" required placeholder="أدخل Bearer Token من wasenderapi.com">
            </div>
            
            <div class="form-group">
                <label for="message">الرسالة</label>
                <textarea id="message" name="message" required 
                          placeholder="اكتب رسالتك هنا... يمكنك استخدام [الاسم] ليتم استبداله باسم العميل"></textarea>
            </div>
            
            <div class="form-group">
                <label for="csvFile">رفع ملف CSV (يحتوي على عمود name وعمود phone)</label>
                <div class="file-upload">
                    <input type="file" id="csvFile" name="csvFile" accept=".csv" required>
                </div>
                <div class="file-info" id="fileInfo"></div>
            </div>
            
            <button type="submit" class="btn" id="sendBtn">
                🚀 إرسال الرسائل
            </button>
        </form>
        
        <div class="progress" id="progress">
            <div class="spinner"></div>
            <div id="progressText">جاري إرسال الرسائل...</div>
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
                
                // Read and preview CSV content
                const reader = new FileReader();
                reader.onload = function(event) {
                    const text = event.target.result;
                    const lines = text.split('\\n').slice(0, 3);
                    console.log('معاينة الملف:', lines);
                };
                reader.readAsText(file);
            }
        });
        
        form.addEventListener('submit', async function(e) {
            e.preventDefault();
            
            const formData = new FormData();
            formData.append('api_key', document.getElementById('api_key').value);
            formData.append('message', document.getElementById('message').value);
            formData.append('file', fileInput.files[0]);
            
            sendBtn.disabled = true;
            progress.classList.add('active');
            result.style.display = 'none';
            progressText.textContent = '⏳ جاري رفع القائمة وإضافتها للطابور...';
            
            try {
                const response = await fetch('/send-bulk', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (!response.ok) {
                    result.className = 'result error';
                    result.innerHTML = `❌ خطأ: ${data.detail || 'حدث خطأ في الإرسال'}`;
                    result.style.display = 'block';
                    sendBtn.disabled = false;
                    progress.classList.remove('active');
                    return;
                }

                // Batch is queued. Now poll /queue-status/{batch_id} every 5s.
                const batchId = data.batch_id;
                const total = data.total;
                progressText.innerHTML = `📋 تم إضافة <b>${total}</b> رسالة للطابور.<br>` +
                    `⏱️ الوقت المتوقع: ${data.estimated_minutes_min}-${data.estimated_minutes_max} دقيقة<br>` +
                    `<small>كل رسالة تنتظر 2-3 دقائق قبل الإرسال</small>`;

                const pollInterval = 5000; // 5 seconds
                const poll = async () => {
                    try {
                        const r = await fetch(`/queue-status/${batchId}`);
                        if (!r.ok) {
                            progressText.textContent = '⚠️ تعذر جلب حالة الطابور';
                            return;
                        }
                        const s = await r.json();
                        const done = s.sent + s.failed;
                        const pct = s.total ? Math.round((done / s.total) * 100) : 0;
                        progressText.innerHTML =
                            `📊 التقدم: <b>${done}/${s.total}</b> (${pct}%)<br>` +
                            `✅ مرسل: ${s.sent} &nbsp;&nbsp; ❌ فشل: ${s.failed} &nbsp;&nbsp; ⏳ متبقي: ${s.pending}`;

                        if (s.status === 'completed') {
                            progress.classList.remove('active');
                            result.className = 'result success';
                            result.innerHTML = `
                                <div style="font-size: 18px; margin-bottom: 15px;">✅ اكتملت العملية!</div>
                                <div class="stats">
                                    <div class="stat">
                                        <div class="stat-number">${s.sent}</div>
                                        <div class="stat-label">رسائل مرسلة</div>
                                    </div>
                                    <div class="stat">
                                        <div class="stat-number">${s.failed}</div>
                                        <div class="stat-label">رسائل فاشلة</div>
                                    </div>
                                    <div class="stat">
                                        <div class="stat-number">${s.total}</div>
                                        <div class="stat-label">المجموع</div>
                                    </div>
                                </div>
                                <details style="margin-top: 15px;">
                                    <summary style="cursor: pointer; color: #667eea;">عرض التفاصيل</summary>
                                    <pre style="margin-top: 10px; font-size: 12px; max-height: 200px; overflow-y: auto;">${JSON.stringify(s.details, null, 2)}</pre>
                                </details>
                            `;
                            result.style.display = 'block';
                            sendBtn.disabled = false;
                            return;
                        }
                        setTimeout(poll, pollInterval);
                    } catch (err) {
                        progressText.textContent = `⚠️ خطأ في الاستعلام: ${err.message}`;
                        setTimeout(poll, pollInterval);
                    }
                };
                setTimeout(poll, pollInterval);

            } catch (error) {
                result.className = 'result error';
                result.innerHTML = `❌ خطأ في الاتصال: ${error.message}`;
                result.style.display = 'block';
                sendBtn.disabled = false;
                progress.classList.remove('active');
            }
        });
    </script>
</body>
</html>
    """


@app.on_event("startup")
async def start_whatsapp_worker():
    asyncio.create_task(whatsapp_worker())


async def whatsapp_worker():
    """
    Background worker that drains whatsapp_queue and sends messages
    via wasenderapi.com. Sleeps a random 2-3 minutes BEFORE each send
    to look human. Reuses one httpx.AsyncClient for the worker lifetime.

    Job shape:
        {
            "api_key":   str,
            "phone":     str,
            "message":   str,
            "name":      str (optional),
            "batch_id":  str (optional, for /send-bulk progress tracking),
        }
    """
    async with httpx.AsyncClient() as http_client:
        while True:
            job = await whatsapp_queue.get()
            try:
                api_key = job["api_key"]
                phone = job["phone"]
                message = job["message"]
                name = job.get("name", "")
                batch_id = job.get("batch_id")

                # ⏳ Random delay BEFORE sending, to look human and avoid rate-limits
                delay = random.uniform(MIN_DELAY_SECONDS, MAX_DELAY_SECONDS)
                print(f"⏳ Worker sleeping {delay:.1f}s before sending to {phone}")
                await asyncio.sleep(delay)

                success, info = await send_whatsapp_via_wasender(
                    api_key=api_key,
                    phone=phone,
                    text=message,
                    http_client=http_client,
                )

                if success:
                    print(f"✅ [QUEUE] Sent to {phone} ({info})")
                else:
                    print(f"❌ [QUEUE] Failed to send to {phone}: {info}")

                # Update batch progress if this job belongs to a bulk batch
                if batch_id and batch_id in batch_results:
                    b = batch_results[batch_id]
                    if success:
                        b["sent"] += 1
                        b["details"].append({
                            "phone": phone, "name": name, "status": "✅ sent",
                        })
                    else:
                        b["failed"] += 1
                        b["details"].append({
                            "phone": phone, "name": name,
                            "status": "❌ failed", "error": info,
                        })
                    b["pending"] -= 1
                    if b["pending"] <= 0:
                        b["status"] = "completed"
                        b["completed_at"] = datetime.now(timezone.utc).isoformat()

            except Exception as e:
                print(f"❌ Worker error: {e}")
                # Still mark the job as resolved on the batch so pending doesn't stick
                bid = job.get("batch_id") if isinstance(job, dict) else None
                if bid and bid in batch_results:
                    b = batch_results[bid]
                    b["failed"] += 1
                    b["pending"] -= 1
                    b["details"].append({
                        "phone": job.get("phone", "?"),
                        "name": job.get("name", ""),
                        "status": "❌ error",
                        "error": str(e),
                    })
                    if b["pending"] <= 0:
                        b["status"] = "completed"
                        b["completed_at"] = datetime.now(timezone.utc).isoformat()
            finally:
                whatsapp_queue.task_done()


import re


def digits_only(phone: str) -> str:
    return re.sub(r"\D", "", phone)


class WhatsAppMessageRequest(BaseModel):
    api_key: str
    phone: str
    message: str


@app.post("/send-whatsApp-message")
async def send_whatsApp_message(payload: WhatsAppMessageRequest):

    phone = digits_only(payload.phone)
    if not phone:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    await whatsapp_queue.put({
        "api_key": payload.api_key,
        "phone": phone,
        "message": payload.message,
    })

    return {
        "status": "queued",
        "phone": phone,
    }


@app.post("/send-bulk")
async def send_bulk_messages(
    api_key: str = Form(...),
    message: str = Form(...),
    file: UploadFile = File(...),
):
    """
    Send bulk WhatsApp messages from CSV file via wasenderapi.com
    CSV should have 'name' and 'phone' columns
    """
    try:
        # Validate file type
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV file")
        
        # Read CSV file
        contents = await file.read()
        
        # Try different encodings
        try:
            csv_text = contents.decode('utf-8')
        except UnicodeDecodeError:
            try:
                csv_text = contents.decode('utf-8-sig')  # Handle BOM
            except UnicodeDecodeError:
                csv_text = contents.decode('latin-1')  # Fallback encoding
        
        # Parse CSV
        csv_reader = csv.DictReader(io.StringIO(csv_text))
        
        # Check if required columns exist
        if csv_reader.fieldnames and 'name' not in csv_reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV must have 'name' column")
        if csv_reader.fieldnames and 'phone' not in csv_reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV must have 'phone' column")
        
        recipients = []
        for row_num, row in enumerate(csv_reader, start=2):  # Start at 2 (header is line 1)
            try:
                if 'name' in row and 'phone' in row:
                    name = row['name'].strip() if row['name'] else " "
                    phone = row['phone'].strip() if row['phone'] else ""

                    if phone:
                        # Remove common symbols
                        phone = phone.replace(" ", "").replace("-", "").replace("+", "")

                        # Remove international prefix 00966 -> replace with nothing
                        if phone.startswith("00966"):
                            phone = phone[5:]

                        # Remove leading zero (e.g. 055...)
                        if phone.startswith("0"):
                            phone = phone[1:]

                        # If phone does not start with 966, add it
                        if not phone.startswith("966"):
                            phone = "966" + phone

                        # Length check (966 + 9 digits = 12)
                        if len(phone) != 12 or not phone.isdigit():
                            print(f"❌ Invalid Saudi number: {row['phone']} -> {phone}")
                            phone = ""  # Clear invalid number
                        else:
                            print(f"✅ Valid Saudi number: {phone}")
                    
                    if name and phone:
                        # Replace [الاسم] placeholder with actual name
                        personalized_message = message.replace('[الاسم]', name)
                        text_list = [
                            "حيّاك الله",
                            "السلام عليكم و رحمة الله و بركاته",
                            "يسعد أوقاتك",
                            "تحية طيبة",
                            "يعطيك العافية",
                            "يسعد أيامك",
                            "حيّاك الله",
                            "يا هلا",
                            "أهلًا",
                            "السلام عليكم",
                        ]
                        name_list = [
                            "نور",
                            "سارة",
                            "ريم",
                            "هدى",
                            "فاطمة",
                            "مريم",
                            "جواهر",
                            "شهد",
                            "دلال",
                            "نورة",
                            "أروى",
                            "ضحى",
                            "رغد",
                            "سمية",
                            "لمى",
                            "غادة",
                            "جنان",
                            "ليان",
                            "سلمى",
                            "زينب"]

                        random_text = random.choice(text_list)
                        final_personalized_message1 = personalized_message.replace('[التحية]', random_text)
                        random_text2 = random.choice(name_list)
                        final_personalized_message = final_personalized_message1.replace('[الفريق]', random_text2)
                        rtl_message = f"\u202B{final_personalized_message}\u202C"
                        recipients.append({
                            'phone': phone,
                            'message': rtl_message,
                            'name': name,
                        })
                        print(recipients)
                    else:
                        print(f"Skipping row {row_num}: missing name or phone")
            except Exception as e:
                print(f"Error processing row {row_num}: {str(e)}")
                continue
        
        if not recipients:
            raise HTTPException(
                status_code=400,
                detail="No valid recipients found in CSV. Make sure CSV has 'name' and 'phone' columns with data.",
            )
        
        # ---------------------------------------------------------------
        # Enqueue all messages for the worker to drain at 2-3 min intervals.
        # We DO NOT send synchronously here — the request returns immediately
        # with a batch_id the UI can poll via /queue-status/{batch_id}.
        # ---------------------------------------------------------------
        batch_id = uuid.uuid4().hex
        total = len(recipients)

        batch_results[batch_id] = {
            "batch_id": batch_id,
            "status": "queued",
            "total": total,
            "sent": 0,
            "failed": 0,
            "pending": total,
            "details": [],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            # Each message waits 2-3 min, so worst-case ETA ≈ total * 3 min
            "estimated_minutes_min": round(total * MIN_DELAY_SECONDS / 60),
            "estimated_minutes_max": round(total * MAX_DELAY_SECONDS / 60),
        }
        _evict_old_batches()

        for recipient in recipients:
            await whatsapp_queue.put({
                "api_key": api_key,
                "phone": recipient["phone"],
                "message": recipient["message"],
                "name": recipient["name"],
                "batch_id": batch_id,
            })

        print(
            f"Queued {total} messages as batch {batch_id} "
            f"(ETA {batch_results[batch_id]['estimated_minutes_min']}-"
            f"{batch_results[batch_id]['estimated_minutes_max']} min)"
        )

        return JSONResponse(content={
            "batch_id": batch_id,
            "status": "queued",
            "queued": total,
            "total": total,
            "estimated_minutes_min": batch_results[batch_id]["estimated_minutes_min"],
            "estimated_minutes_max": batch_results[batch_id]["estimated_minutes_max"],
            "poll_url": f"/queue-status/{batch_id}",
        })

    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in send_bulk_messages: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue-status/{batch_id}")
async def queue_status(batch_id: str):
    """Poll progress of a /send-bulk batch."""
    b = batch_results.get(batch_id)
    if not b:
        raise HTTPException(status_code=404, detail="Unknown batch_id")
    return JSONResponse(content=b)


from fastapi import FastAPI, Body, Form
from typing import Optional


@app.post("/sendwhatsApp")
async def send_bulk_messages_debug(
    api_key: Optional[str] = Body(None),
    message: Optional[str] = Body(None),
    number: Optional[str] = Body(None),
):
    print("api_key:", api_key)
    print("message:", message)
    print("number:", number)

    return {"status": "ok"}


# -------------------------------
# ✉️ EMAIL INTERFACE
# -------------------------------
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
            button:hover {
                background: #36D1DC;
            }
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


# -------------------------------
# ✉️ EMAIL ENDPOINT
# -------------------------------
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
        if not file.filename.endswith('.csv'):
            raise HTTPException(status_code=400, detail="File must be a CSV file")

        contents = await file.read()
        try:
            csv_text = contents.decode('utf-8')
        except UnicodeDecodeError:
            csv_text = contents.decode('latin-1')

        reader = csv.DictReader(io.StringIO(csv_text))
        if 'email' not in reader.fieldnames or 'name' not in reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV must have 'name' and 'email' columns")

        recipients = [r for r in reader if r.get('email')]

        # Connect to Gmail SMTP
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(sender_email, app_password)

        results = {"sent": 0, "failed": 0, "total": len(recipients), "details": []}

        for r in recipients:
            try:
                personalized_body = body.replace('[name]', r['name'])
                msg = MIMEMultipart()
                msg["From"] = sender_email
                msg["To"] = r['email']
                msg["Subject"] = subject
                msg.attach(MIMEText(personalized_body, "plain"))
                server.send_message(msg)
                results["sent"] += 1
                results["details"].append({"email": r['email'], "name": r['name'], "status": "✅ Sent"})
                await asyncio.sleep(1)
            except Exception as e:
                results["failed"] += 1
                results["details"].append({"email": r['email'], "error": str(e)})

        server.quit()
        return JSONResponse(content=results)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "WhatsApp Bulk Messaging System"}


@app.get("/test")
async def test_endpoint():
    """Test endpoint to verify server is running"""
    return {"message": "Server is running!", "status": "OK"}


if __name__ == "__main__":
    import uvicorn
    print("Starting WhatsApp Bulk Messaging System...")
    print("Access the interface at: http://localhost:8002")
    uvicorn.run(app, host="0.0.0.0", port=8002)