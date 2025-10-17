# main.py
from fastapi import FastAPI, File, UploadFile, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import asyncio
import csv
import io
from typing import List, Dict

from pydantic import BaseModel
import sys
import os

# Add the parent directory to path to import the WhatsApp client
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from whatsapp_client_python.whatsapp_client import WhatsAppClient

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
    session_name: str
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
                <label for="session_name">اسم الجلسة (Session Name)</label>
                <input type="text" id="session_name" name="session_name" required placeholder="أدخل اسم الجلسة">
            </div>
            
            <div class="form-group">
                <label for="api_key">مفتاح API (API Key)</label>
                <input type="text" id="api_key" name="api_key" required placeholder="أدخل مفتاح API">
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
            formData.append('session_name', document.getElementById('session_name').value);
            formData.append('api_key', document.getElementById('api_key').value);
            formData.append('message', document.getElementById('message').value);
            formData.append('file', fileInput.files[0]);
            
            sendBtn.disabled = true;
            progress.classList.add('active');
            result.style.display = 'none';
            
            try {
                const response = await fetch('/send-bulk', {
                    method: 'POST',
                    body: formData
                });
                
                const data = await response.json();
                
                if (response.ok) {
                    result.className = 'result success';
                    result.innerHTML = `
                        <div style="font-size: 18px; margin-bottom: 15px;">✅ تمت العملية بنجاح!</div>
                        <div class="stats">
                            <div class="stat">
                                <div class="stat-number">${data.sent}</div>
                                <div class="stat-label">رسائل مرسلة</div>
                            </div>
                            <div class="stat">
                                <div class="stat-number">${data.failed}</div>
                                <div class="stat-label">رسائل فاشلة</div>
                            </div>
                            <div class="stat">
                                <div class="stat-number">${data.total}</div>
                                <div class="stat-label">المجموع</div>
                            </div>
                        </div>
                        <details style="margin-top: 15px;">
                            <summary style="cursor: pointer; color: #667eea;">عرض التفاصيل</summary>
                            <pre style="margin-top: 10px; font-size: 12px; max-height: 200px; overflow-y: auto;">${JSON.stringify(data.details, null, 2)}</pre>
                        </details>
                    `;
                } else {
                    result.className = 'result error';
                    result.innerHTML = `❌ خطأ: ${data.detail || 'حدث خطأ في الإرسال'}`;
                }
            } catch (error) {
                result.className = 'result error';
                result.innerHTML = `❌ خطأ في الاتصال: ${error.message}`;
            } finally {
                sendBtn.disabled = false;
                progress.classList.remove('active');
                result.style.display = 'block';
            }
        });
    </script>
</body>
</html>
    """

@app.post("/send-bulk")
async def send_bulk_messages(
    session_name: str = Form(...),
    api_key: str = Form(...),
    message: str = Form(...),
    file: UploadFile = File(...)
):
    """
    Send bulk WhatsApp messages from CSV file
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
                    name = row['name'].strip() if row['name'] else " "  # Use a space if the name is empty
                    phone = row['phone'].strip() if row['phone'] else ""
                    
                    if name and phone:
                        # Replace [الاسم] placeholder with actual name
                        personalized_message = message.replace('[الاسم]', name)
                        import random
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
                                    "السلام عليكم"
                                ]

                        random_text = random.choice(text_list)
                        final_personalized_message = personalized_message.replace('[التحية]', random_text)
                        recipients.append({
                            'phone': phone,
                            'message': final_personalized_message,
                            'name': name
                        })
                    else:
                        print(f"Skipping row {row_num}: missing name or phone")
            except Exception as e:
                print(f"Error processing row {row_num}: {str(e)}")
                continue
        
        if not recipients:
            raise HTTPException(status_code=400, detail="No valid recipients found in CSV. Make sure CSV has 'name' and 'phone' columns with data.")
        
        # Initialize WhatsApp client and send messages
        results = {
            "sent": 0,
            "failed": 0,
            "total": len(recipients),
            "details": []
        }
        
        print(f"Starting to send {len(recipients)} messages...")
        
        async with WhatsAppClient(session_name=session_name, api_key=api_key) as client:
            # Check if client is authenticated
            if not client.authenticated:
                raise HTTPException(status_code=401, detail="Failed to authenticate WhatsApp client")
            
            for idx, recipient in enumerate(recipients, 1):
                try:
                    print(f"Sending message {idx}/{len(recipients)} to {recipient['phone']} ({recipient['name']})")
                    
                    # Using synchronous send_message as per the client implementation
                    try: 
                        success = client.send_message(recipient['phone'], recipient['message'])
                        
                        if success:
                            results["sent"] += 1
                            results["details"].append({
                                "phone": recipient['phone'],
                                "name": recipient['name'],
                                "status": "✅ sent"
                            })
                            print(f"✅ Successfully sent to {recipient['phone']}")
                        else:
                            results["failed"] += 1
                            results["details"].append({
                                "phone": recipient['phone'],
                                "name": recipient['name'],
                                "status": "❌ failed"
                            })
                            print(f"❌ Failed to send to {recipient['phone']}")
                    except:
                        print("can't send")
                    
                    # Add delay between messages to avoid rate limiting
                    if idx < len(recipients):  # Don't delay after the last message
                        await asyncio.sleep(2)
                    
                except Exception as e:
                    print(f"Error sending to {recipient['phone']}: {str(e)}")
                    results["failed"] += 1
                    results["details"].append({
                        "phone": recipient['phone'],
                        "name": recipient['name'],
                        "status": "❌ error",
                        "error": str(e)
                    })
        
        print(f"Completed: {results['sent']} sent, {results['failed']} failed")
        return JSONResponse(content=results)
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error in send_bulk_messages: {str(e)}")
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
    print("Access the interface at: http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8002)