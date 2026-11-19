from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import ddddocr
import re
import io
from PIL import Image

app = FastAPI()

# ফ্রন্টএন্ড থেকে কল করার পারমিশন (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ক্যাপচা পড়ার AI ইঞ্জিন
ocr = ddddocr.DdddOcr(show_ad=False)

@app.get("/")
def home():
    return {"message": "IVAC Live Tracker API is Running smoothly!"}

@app.get("/track")
def track_visa(bgd: str):
    bgd = bgd.strip().upper()
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })

    try:
        # ১. passtrack পেজে গিয়ে সেশন কুকি ও ক্যাপচা আনা
        main_page = session.get("https://passtrack.net", timeout=10)
        soup = BeautifulSoup(main_page.text, "html.parser")
        
        # ক্যাপচা ইমেজ লিংক খোঁজা
        captcha_img = soup.find("img", {"id": re.compile(r"captcha|code", re.I)})
        captcha_text = ""
        
        if captcha_img and captcha_img.get("src"):
            img_url = captcha_img["src"]
            if not img_url.startswith("http"):
                img_url = "https://passtrack.net/" + img_url.lstrip("/")
            
            img_data = session.get(img_url, timeout=10).content
            # AI দিয়ে ক্যাপচা সমাধান
            captcha_text = ocr.classification(img_data)
        
        # ২. BGD নম্বর ও ক্যাপচা দিয়ে সার্চ পাঠানো
        payload = {
            "webfile_no": bgd,
            "captcha": captcha_text
        }
        
        post_url = "https://passtrack.net/applicant-tracking-process"
        res = session.post(post_url, data=payload, timeout=15)
        res_soup = BeautifulSoup(res.text, "html.parser")
        
        # ৩. যাচাই: ভুল BGD নম্বর হলে
        if "not found" in res.text.lower() or "no record" in res.text.lower() or not res.text.strip():
            return {
                "success": False,
                "message": "কোনো রেকর্ড পাওয়া যায়নি! সঠিক BGD নম্বর দিন।"
            }

        # ৪. সফল হলে ডেটা রিড করা
        # টেবিল থেকে নাম ও স্ট্যাটাস খোঁজা
        name = "APPLICANT"
        status_text = "Received At Center"
        step = 1

        text_content = res.text.upper()
        if "READY FOR DELIVERY" in text_content:
            status_text = "Ready For Delivery"
            step = 3
        elif "PROCESS INITIATED" in text_content or "UNDER PROCESS" in text_content:
            status_text = "Process Initiated"
            step = 2
        elif "DELIVERED" in text_content:
            status_text = "Delivered From Center"
            step = 4

        return {
            "success": True,
            "bgd": bgd,
            "status": status_text,
            "step": step,
            "message": "সফলভাবে তথ্য পাওয়া গেছে"
        }

    except Exception as e:
        return {
            "success": False,
            "message": "সার্ভারে সমস্যা হয়েছে, কিছুক্ষণ পর আবার চেষ্টা করুন।"
      }
