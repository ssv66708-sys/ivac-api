from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import re
import uuid
import base64
from urllib.parse import urljoin

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# সেশন স্টোর করার জন্য ডিকশনারি (মেমোরিতে)
# বাস্তব প্রোডাকশনে Redis ব্যবহার করা ভালো, তবে ছোট অ্যাপের জন্য এটি ঠিক আছে
sessions_db = {}

class TrackRequest(BaseModel):
    bgd: str
    captcha_text: str
    session_id: str

@app.get("/")
def home():
    return {"status": "online"}

# ধাপ ১: ক্যাপচা নিয়ে আসার API
@app.get("/get-captcha")
def get_captcha():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.passtrack.net/",
        "Origin": "https://www.passtrack.net"
    })
    
    try:
        url = "https://www.passtrack.net/regular_passport.php"
        res = session.get(url, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # ক্যাপচা ইমেজ খোঁজা
        captcha_img = soup.find("img", {"src": re.compile(r"captcha", re.I)})
        
        if not captcha_img:
            raise HTTPException(status_code=500, detail="Captcha not found on website")
            
        img_url = captcha_img["src"]
        if not img_url.startswith("http"):
            img_url = urljoin("https://www.passtrack.net/", img_url.lstrip("/"))
            
        # ক্যাপচা ইমেজ ডাউনলোড করা
        img_data = session.get(img_url, timeout=10).content
        
        # ইমেজকে Base64 এ কনভার্ট করা যাতে ফ্রন্টএন্ডে দেখানো যায়
        img_base64 = base64.b64encode(img_data).decode('utf-8')
        
        # সেশন আইডি তৈরি করা এবং সেশন সেভ করা
        session_id = str(uuid.uuid4())
        sessions_db[session_id] = session
        
        return {
            "success": True,
            "session_id": session_id,
            "captcha_image": f"data:image/png;base64,{img_base64}"
        }
        
    except Exception as e:
        return {"success": False, "message": str(e)}

# ধাপ ২: ইউজারের দেওয়া ক্যাপচা ও BGD দিয়ে সাবমিট করা
@app.post("/submit-track")
def submit_track(data: TrackRequest):
    bgd = data.bgd.strip().upper()
    session_id = data.session_id
    
    if session_id not in sessions_db:
        return {"success": False, "message": "সেশন মেয়াদোত্তীর্ণ! আবার চেষ্টা করুন।"}
        
    session = sessions_db[session_id]
    
    try:
        url = "https://www.passtrack.net/regular_passport.php"
        
        payload = {
            "web_file_no": bgd,
            "code": data.captcha_text,
            "submit": "Submit"
        }
        
        post_res = session.post(url, data=payload, timeout=15)
        text = post_res.text.upper()
        
        # সেশন ডিলিট করে দেওয়া (কাজ শেষ)
        del sessions_db[session_id]
        
        if "NOT FOUND" in text or "NO RECORD" in text:
            return {"success": False, "message": "কোনো রেকর্ড পাওয়া যায়নি! সঠিক তথ্য দিন।"}
            
        if "INVALID CAPTCHA" in text or "WRONG CAPTCHA" in text:
            return {"success": False, "message": "ক্যাপচা ভুল হয়েছে! আবার চেষ্টা করুন।"}
            
        # স্ট্যাটাস নির্ধারণ
        status = "Received At Center"
        step = 1
        if "READY FOR DELIVERY" in text:
            status = "Ready for Delivery"
            step = 3
        elif "PROCESS INITIATED" in text or "UNDER PROCESS" in text:
            status = "Process Initiated"
            step = 2
        elif "DELIVERED" in text:
            status = "Delivered"
            step = 4
            
        return {
            "success": True,
            "bgd": bgd,
            "status": status,
            "step": step,
            "message": "সফলভাবে তথ্য পাওয়া গেছে"
        }
        
    except Exception as e:
        return {"success": False, "message": "সার্ভার এরর।"}
