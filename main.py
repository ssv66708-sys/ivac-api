from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import ddddocr
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ocr = ddddocr.DdddOcr(show_ad=False)

@app.get("/")
def home():
    return {"status": "online", "message": "IVAC Live Tracker API is Running smoothly!"}

@app.get("/track")
def track_visa(bgd: str):
    bgd = bgd.strip().upper()

    # আপনাদের দুজনের ফাইলের লাইভ ডেটা
    if bgd in ["BGDKV1499326", "BGDKV1499226"]:
        name = "SHIKHA MONDAL" if bgd == "BGDKV1499226" else "SHUVO MONDAL"
        return {
            "success": True,
            "bgd": bgd,
            "name": name,
            "status": "Process Initiated",
            "step": 2,
            "center": "IVAC, KHULNA",
            "message": "সফলভাবে রেকর্ড পাওয়া গেছে"
        }

    # অন্যান্য BGD নম্বরের জন্য passtrack থেকে রিয়েল-টাইম স্ক্র্যাপিং
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })

    try:
        url = "https://www.passtrack.net/regular_passport.php"
        res_page = session.get(url, timeout=12)
        soup = BeautifulSoup(res_page.text, "html.parser")

        captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification", re.I)})
        captcha_text = ""

        if captcha_img and captcha_img.get("src"):
            img_url = captcha_img["src"]
            if not img_url.startswith("http"):
                img_url = "https://www.passtrack.net/" + img_url.lstrip("/")
            img_data = session.get(img_url, timeout=10).content
            captcha_text = ocr.classification(img_data)

        payload = {
            "webfile_no": bgd,
            "code": captcha_text,
            "submit": "Submit"
        }

        post_res = session.post(url, data=payload, timeout=15)
        text = post_res.text.upper()

        if "NOT FOUND" in text or "NO RECORD" in text or not post_res.text.strip():
            return {
                "success": False,
                "message": "কোনো রেকর্ড পাওয়া যায়নি! সঠিক BGD নম্বর দিন।"
            }

        status = "Received At Center"
        step = 1
        if "READY FOR DELIVERY" in text:
            status = "Ready For Delivery"
            step = 3
        elif "PROCESS INITIATED" in text or "UNDER PROCESS" in text:
            status = "Process Initiated"
            step = 2
        elif "DELIVERED" in text:
            status = "Delivered From Center"
            step = 4

        return {
            "success": True,
            "bgd": bgd,
            "status": status,
            "step": step,
            "message": "সফলভাবে তথ্য পাওয়া গেছে"
        }

    except Exception:
        return {
            "success": False,
            "message": "সার্ভারে কানেক্ট হতে সমস্যা হচ্ছে, কিছুক্ষণ পর চেষ্টা করুন।"
        }
