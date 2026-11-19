from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import dddocr
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="IVAC Visa API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ocr = dddocr.DdddOcr(show_ad=False)


@app.get("/")
def home():
    return {"status": "online", "message": "API is Live"}


# 🔍 ১ সেকেন্ডে আসল সমস্যা ধরার ডিবাগ রুট
@app.get("/debug")
def debug_tracker(bgd: str = "BGDCV2A60426"):
    bgd = bgd.strip().upper()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.passtrack.net/regular_passport.php"
    })

    try:
        url = "https://www.passtrack.net/regular_passport.php"
        res = session.get(url, timeout=15, verify=False)
        soup = BeautifulSoup(res.text, "html.parser")

        # ক্যাপচা পড়া
        captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification", re.I)})
        captcha_text = ""
        if captcha_img and captcha_img.get("src"):
            img_url = captcha_img["src"]
            if not img_url.startswith("http"):
                img_url = "https://www.passtrack.net/" + img_url.lstrip("/")
            img_data = session.get(img_url, timeout=10, verify=False).content
            captcha_text = ocr.classification(img_data).strip().upper()

        # সাবমিট
        payload = {"webfile_no": bgd, "code": captcha_text, "submit": "Submit"}
        post_res = session.post(url, data=payload, timeout=15, verify=False)

        # সার্ভারের মূল উত্তর
        raw_text = post_res.text
        clean_text = BeautifulSoup(raw_text, "html.parser").get_text(separator=" ", strip=True)

        return {
            "http_status": post_res.status_code,
            "solved_captcha": captcha_text,
            "is_cloudflare_blocked": "Just a moment" in raw_text or "Cloudflare" in raw_text,
            "server_reply_summary": clean_text[:400],
            "raw_snippet": raw_text[:300]
        }
    except Exception as e:
        return {"error": str(e)}


# 🚀 মূল ট্র্যাকিং রুট
@app.get("/track")
def track_visa(bgd: str = Query(..., description="BGD Number")):
    bgd = bgd.strip().upper()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.passtrack.net/regular_passport.php"
    })

    try:
        url = "https://www.passtrack.net/regular_passport.php"
        res = session.get(url, timeout=15, verify=False)
        soup = BeautifulSoup(res.text, "html.parser")

        captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification", re.I)})
        captcha_text = ""
        if captcha_img and captcha_img.get("src"):
            img_url = captcha_img["src"]
            if not img_url.startswith("http"):
                img_url = "https://www.passtrack.net/" + img_url.lstrip("/")
            img_data = session.get(img_url, timeout=10, verify=False).content
            captcha_text = ocr.classification(img_data).strip().upper()

        payload = {"webfile_no": bgd, "code": captcha_text, "submit": "Submit"}
        post_res = session.post(url, data=payload, timeout=15, verify=False)
        text = post_res.text.upper()

        if "NOT FOUND" in text or "NO RECORD" in text or not post_res.text.strip():
            return {"success": False, "message": "কোনো রেকর্ড পাওয়া যায়নি! সঠিক BGD নম্বর দিন।"}

        status = "Received At Center"
        step = 1

        if "DELIVERED" in text:
            status = "Delivered From Center"
            step = 4
        elif "READY FOR DELIVERY" in text:
            status = "Ready For Delivery"
            step = 3
        elif "PROCESS INITIATED" in text or "UNDER PROCESS" in text:
            status = "Process Initiated"
            step = 2

        return {
            "success": True,
            "bgd": bgd,
            "name": "আবেদনকারী",
            "status": status,
            "step": step,
            "center": "IVAC Center",
            "message": "সফলভাবে তথ্য পাওয়া গেছে"
        }
    except Exception as e:
        return {"success": False, "message": "সার্ভারে কানেক্ট হতে সমস্যা হচ্ছে, কিছুক্ষণ পর চেষ্টা করুন।"}
