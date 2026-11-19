from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
from bs4 import BeautifulSoup
import base64
import uuid
import re
import urllib3
import time

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="IVAC Professional Live Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ইউজার সেশনগুলো মেমোরিতে সাময়িক রাখার জন্য ডিকশনারি
session_store = {}

PASSTRACK_URL = "https://www.passtrack.net/regular_passport.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Referer": "https://www.passtrack.net/regular_passport.php",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
}

class TrackRequest(BaseModel):
    bgd: str
    captcha_text: str
    session_id: str


@app.get("/")
def home():
    return {"status": "online", "message": "IVAC Live Tracker API Running smoothly!"}


# ১. লাইভ ক্যাপচা ইমেজ আনা
@app.get("/get-captcha")
def get_captcha():
    # পুরনো সেশন ক্লিনআপ (১০ মিনিটের বেশি পুরনো হলে মুছে ফেলা)
    now = time.time()
    for sid in list(session_store.keys()):
        if now - session_store[sid]["time"] > 600:
            del session_store[sid]

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        res = session.get(PASSTRACK_URL, timeout=15, verify=False)
        soup = BeautifulSoup(res.text, "html.parser")

        captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification|\.php", re.I)})
        if not captcha_img or not captcha_img.get("src"):
            return {"success": False, "message": "ক্যাপচা লোড করা যায়নি। আবার চেষ্টা করুন।"}

        img_url = captcha_img["src"]
        if not img_url.startswith("http"):
            img_url = "https://www.passtrack.net/" + img_url.lstrip("/")

        img_res = session.get(img_url, timeout=10, verify=False)
        base64_img = "data:image/jpeg;base64," + base64.b64encode(img_res.content).decode("utf-8")

        # সেশন আইডি তৈরি ও সংরক্ষণ
        session_id = str(uuid.uuid4())
        session_store[session_id] = {
            "session": session,
            "time": time.time()
        }

        return {
            "success": True,
            "session_id": session_id,
            "captcha_image": base64_img
        }
    except Exception as e:
        return {"success": False, "message": f"সার্ভার ত্রুটি: {str(e)}"}


# ২. স্ট্যাটাস সাবমিট করা
@app.post("/submit-track")
def submit_track(req: TrackRequest):
    bgd = req.bgd.strip().upper()
    code = req.captcha_text.strip()
    session_id = req.session_id

    if session_id not in session_store:
        return {"success": False, "message": "ক্যাপচার মেয়াদ শেষ হয়ে গেছে! অনুগ্রহ করে নতুন ক্যাপচা আনুন।"}

    session = session_store[session_id]["session"]

    try:
        payload = {
            "webfile_no": bgd,
            "code": code,
            "submit": "Submit"
        }

        post_res = session.post(PASSTRACK_URL, data=payload, timeout=20, verify=False)
        html_text = post_res.text
        html_upper = html_text.upper()

        # ক্যাপচা ভুল হলে
        if "INVALID CODE" in html_upper or "WRONG CODE" in html_upper or "ENTER VALID CODE" in html_upper:
            return {"success": False, "message": "ক্যাপচা কোডটি ভুল হয়েছে! সঠিক কোড দিন।"}

        # রেকর্ড না থাকলে
        if "NOT FOUND" in html_upper or "NO RECORD" in html_upper:
            return {"success": False, "message": f"passtrack-এ {bgd} নম্বরের কোনো রেকর্ড পাওয়া যায়নি!"}

        # স্ট্যাটাস পার্সিং
        status = "Received At Center"
        step = 1

        if "DELIVERED" in html_upper:
            status = "Delivered From Center"
            step = 4
        elif "READY FOR DELIVERY" in html_upper:
            status = "Ready For Delivery"
            step = 3
        elif "PROCESS INITIATED" in html_upper or "UNDER PROCESS" in html_upper:
            status = "Process Initiated"
            step = 2

        # নাম ও সেন্টার খোঁজা
        res_soup = BeautifulSoup(html_text, "html.parser")
        applicant_name = "ভিসা আবেদনকারী"
        center_name = "IVAC Center"

        for tr in res_soup.find_all("tr"):
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2:
                row_str = " ".join(cells).upper()
                if "NAME" in row_str and len(cells) >= 2:
                    applicant_name = cells[1]
                elif "CENTER" in row_str and len(cells) >= 2:
                    center_name = cells[1]

        # কাজ শেষে সেশন মেমোরি থেকে মুছে ফেলা
        del session_store[session_id]

        return {
            "success": True,
            "bgd": bgd,
            "name": applicant_name,
            "status": status,
            "step": step,
            "center": center_name,
            "message": "সফলভাবে লাইভ তথ্য পাওয়া গেছে!"
        }

    except Exception as e:
        return {"success": False, "message": f"প্রসেসিং ত্রুটি: {str(e)}"}
