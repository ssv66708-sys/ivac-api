from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import base64
import uuid
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="IVAC Manual Captcha Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# প্রতিটি ইউজারের সেশন সাময়িকভাবে মনে রাখার ডিকশনারি
user_sessions = {}


@app.get("/")
def home():
    return {"status": "online", "message": "API Running with Live Captcha"}


# ১. লাইভ ক্যাপচা ইমেজ এনে Base64 ফরম্যাটে ফ্রন্টএন্ডে পাঠানো
@app.get("/get-captcha")
def get_captcha():
    session_id = str(uuid.uuid4())
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.passtrack.net/regular_passport.php"
    })

    try:
        url = "https://www.passtrack.net/regular_passport.php"
        res = session.get(url, timeout=15, verify=False)
        soup = BeautifulSoup(res.text, "html.parser")

        captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification|code|\.php", re.I)})
        if not captcha_img:
            return {"success": False, "message": "ক্যাপচা ছবি পাওয়া যায়নি!"}

        img_url = captcha_img["src"]
        if not img_url.startswith("http"):
            img_url = "https://www.passtrack.net/" + img_url.lstrip("/")

        img_response = session.get(img_url, timeout=10, verify=False)
        
        # ছবিকে Base64 টেক্সটে রূপান্তর (যাতে ব্রাউজারে কখনো ছবি লোড ফেইল না করে)
        b64_data = base64.b64encode(img_response.content).decode("utf-8")
        data_uri = f"data:image/png;base64,{b64_data}"

        # কুকিসহ সেশনটি মেমোরিতে রাখা
        user_sessions[session_id] = session

        return {
            "success": True,
            "session_id": session_id,
            "captcha_image": data_uri
        }

    except Exception as e:
        return {"success": False, "message": f"সার্ভার ত্রুটি: {str(e)}"}


# ২. ব্যবহারকারীর দেওয়া ক্যাপচা ও BGD দিয়ে লাইভ তথ্য আনা
class TrackRequest(BaseModel):
    bgd: str
    captcha_text: str
    session_id: str


@app.post("/submit-track")
def submit_track(req: TrackRequest):
    session = user_sessions.get(req.session_id)
    if not session:
        return {"success": False, "message": "ক্যাপচার মেয়াদ শেষ! রিফ্রেশ বাটনে চেপে নতুন ক্যাপচা নিন।"}

    bgd = req.bgd.strip().upper()
    code = req.captcha_text.strip()

    try:
        url = "https://www.passtrack.net/regular_passport.php"
        
        # ফর্ম ফিল্ড পেলোড
        payload = {
            "webfile_no": bgd,
            "code": code,
            "submit": "Submit"
        }

        post_res = session.post(url, data=payload, timeout=20, verify=False)
        res_upper = post_res.text.upper()

        # ক্যাপচা ভুল হলে
        if "INVALID CODE" in res_upper or "WRONG CODE" in res_upper:
            return {"success": False, "message": "ক্যাপচা কোডটি ভুল হয়েছে! আবার সঠিকভাবে লিখুন।"}

        # কোনো রেকর্ড না থাকলে
        if "NOT FOUND" in res_upper or "NO RECORD" in res_upper:
            return {"success": False, "message": f"passtrack-এ {bgd} নম্বরের কোনো রেকর্ড পাওয়া যায়নি!"}

        # স্ট্যাটাস এবং স্টেপ নির্ধারণ
        status = "Received At Center"
        step = 1

        if "DELIVERED" in res_upper:
            status = "Delivered From Center"
            step = 4
        elif "READY FOR DELIVERY" in res_upper:
            status = "Ready For Delivery"
            step = 3
        elif "PROCESS INITIATED" in res_upper or "UNDER PROCESS" in res_upper:
            status = "Process Initiated"
            step = 2

        # নাম খোঁজার চেষ্টা
        res_soup = BeautifulSoup(post_res.text, "html.parser")
        applicant_name = "ভিসা আবেদনকারী"
        for tr in res_soup.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2 and "NAME" in " ".join(cells).upper():
                applicant_name = cells[1]

        # কাজ শেষে সেশন ডিলিট করে মেমোরি খালি করা
        user_sessions.pop(req.session_id, None)

        return {
            "success": True,
            "bgd": bgd,
            "name": applicant_name,
            "status": status,
            "step": step,
            "message": "সফলভাবে তথ্য পাওয়া গেছে"
        }

    except Exception as e:
        return {"success": False, "message": "সার্ভারে সমস্যা হচ্ছে, কিছুক্ষণ পর চেষ্টা করুন।"}
