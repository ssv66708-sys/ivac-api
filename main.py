from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import ddddocr
import re
import cv2
import numpy as np
from urllib.parse import urljoin

app = FastAPI()

# CORS সেটআপ (ফ্রন্টএন্ড থেকে কল করার জন্য)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # প্রোডাকশনে গেলে "*" এর জায়গায় আপনার ফ্রন্টএন্ডের ডোমেইন দিন
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# OCR ইনিশিয়ালাইজ
ocr = ddddocr.DdddOcr(show_ad=False)

@app.get("/")
def home():
    return {"status": "online", "message": "IVAC Live Tracker API is Running smoothly!"}

@app.get("/track")
def track_visa(bgd: str):
    bgd = bgd.strip().upper()

    # ১. ডেমো ডাটা (টেস্টিং এর জন্য রাখা হলো)
    if bgd in ["BGDKV1499326", "BGDKV1499226"]:
        name = "SHIKHA MONDAL" if bgd == "BGDKV1499226" else "SHUVO MONDAL"
        return {
            "success": True,
            "bgd": bgd,
            "name": name,
            "status": "Process Initiated",
            "step": 2,
            "center": "IVAC, KHULNA",
            "message": "ডেমো ডাটা সফলভাবে দেখানো হচ্ছে"
        }

    # ২. আসল IVAC ওয়েবসাইট স্ক্র্যাপিং লজিক
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.ivacbd.com/",
        "Origin": "https://www.ivacbd.com",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    try:
        # IVAC এর ভিসা স্ট্যাটাস পেজের আসল লিংক
        url = "https://www.ivacbd.com/visa-status" 
        res_page = session.get(url, timeout=15)
        
        if res_page.status_code != 200:
            return {"success": False, "message": "IVAC সার্ভার ব্লক করেছে অথবা সাইট ডাউন আছে।"}

        soup = BeautifulSoup(res_page.text, 'html.parser')
        
        # ক্যাপচা ইমেজ খোঁজা
        captcha_img = soup.find("img", {"src": re.compile(r"captcha", re.I)})
        captcha_text = ""

        if captcha_img and captcha_img.get("src"):
            img_url = captcha_img["src"]
            if not img_url.startswith("http"):
                img_url = urljoin("https://www.ivacbd.com/", img_url.lstrip("/"))
            
            img_data = session.get(img_url, timeout=10).content
            
            # ক্যাপচা ডিকোড করা (আপনার আগের কোডে এখানেই ভুল ছিল)
            img_array = np.frombuffer(img_data, np.uint8)
            img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
            captcha_text = ocr.classification(img)
            print(f"Decoded Captcha: {captcha_text}") # লগে দেখার জন্য

        # ফর্ম ডাটা (IVAC এর সাইটের ইনপুট ফিল্ডের নাম অনুযায়ী)
        payload = {
            "web_file_no": bgd,
            "captcha": captcha_text,
            "submit": "Submit"
        }
        
        # পোস্ট রিকোয়েস্ট পাঠানো
        post_url = "https://www.ivacbd.com/visa-status/check" # পেজের ফর্ম অ্যাকশন লিংক
        post_res = session.post(post_url, data=payload, timeout=15)
        text = post_res.text.upper()

        # রেজাল্ট চেক করা
        if "NOT FOUND" in text or "NO RECORD" in text or "INVALID CAPTCHA" in text:
            return {"success": False, "message": "ক্যাপচা ভুল হয়েছে অথবা এই BGD নম্বরটি পাওয়া যায়নি।"}
            
        if "CAPTCHA" in text and "INVALID" in text:
            return {"success": False, "message": "ক্যাপচা মিসম্যাচ করেছে, আবার চেষ্টা করুন।"}

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
            "name": "Applicant", # নাম বের করতে হলে HTML ট্যাগ অ্যানালাইসিস করতে হবে
            "status": status,
            "step": step,
            "center": "IVAC Center",
            "message": "সফলভাবে তথ্য পাওয়া গেছে"
        }

    except Exception as e:
        # আসল এরর প্রিন্ট করা হবে Render এর লগে
        print(f"Critical Error: {str(e)}")
        return {
            "success": False, 
            "message": "সার্ভার এরর। ক্যাপচা বা IVAC সাইট আপডেট হয়েছে। লগ চেক করুন।"
        }
