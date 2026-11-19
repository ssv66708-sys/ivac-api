from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import dddocr
import re
import urllib3

# SSL সতর্কবার্তা নিষ্ক্রিয় করার জন্য
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="IVAC 100% Dynamic Visa Tracker API")

# যেকোনো ডোমেইন/মোবাইল অ্যাপ থেকে কল করার জন্য CORS ওপেন
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# সার্ভার স্টার্ট হওয়ার সময় OCR মডেল লোড হবে (একবারই)
print("🚀 লাইভ ক্যাপচা মডেল লোড হচ্ছে...")
ocr = dddocr.DdddOcr(show_ad=False)
print("✅ OCR মডেল প্রস্তুত! এখন যেকোনো নম্বরের জন্য রিয়েল-টাইম কাজ করবে।")


@app.get("/")
def home():
    return {
        "status": "online",
        "message": "IVAC Live 100% Dynamic API is Running!"
    }


@app.get("/track")
def track_visa(bgd: str = Query(..., description="ব্যবহারকারীর দেওয়া BGD নম্বর")):
    bgd = bgd.strip().upper()
    print(f"\n🔍 [LIVE REQUEST] BGD ট্র্যাক করা হচ্ছে: {bgd}")

    # নম্বর সঠিক কি না প্রাথমিক যাচাই
    if not bgd or len(bgd) < 6:
        return {
            "success": False,
            "message": "অনুগ্রহ করে একটি সঠিক Web File (BGD) নম্বর লিখুন।"
        }

    passtrack_url = "https://www.passtrack.net/regular_passport.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.passtrack.net/regular_passport.php",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }

    # ক্যাপচা কখনো ১ বারে ভুল রিড হলে অটোমেটিক ৩ বার পর্যন্ত রিট্রাই করবে
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"📡 লাইভ সার্ভারে চেষ্টা চলছে ({attempt}/{max_retries})...")
        session = requests.Session()
        session.headers.update(headers)

        try:
            # ১. পাসট্র্যাকের পেজ লোড
            res_page = session.get(passtrack_url, timeout=15, verify=False)
            soup = BeautifulSoup(res_page.text, "html.parser")

            # ২. ক্যাপচা ছবি বের করা
            captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification", re.I)})
            captcha_code = ""

            if captcha_img and captcha_img.get("src"):
                img_url = captcha_img["src"]
                if not img_url.startswith("http"):
                    img_url = "https://www.passtrack.net/" + img_url.lstrip("/")

                # ক্যাপচা ছবি নামিয়ে dddocr দিয়ে কোড পড়া
                img_bytes = session.get(img_url, timeout=10, verify=False).content
                captcha_code = ocr.classification(img_bytes).strip().upper()
                print(f"🤖 স্বয়ংক্রিয় ক্যাপচা সমাধান: {captcha_code}")

            # ৩. লাইভ সার্ভারে সাবমিট করা
            payload = {
                "webfile_no": bgd,
                "code": captcha_code,
                "submit": "Submit"
            }

            post_res = session.post(passtrack_url, data=payload, timeout=20, verify=False)
            html_text = post_res.text
            html_upper = html_text.upper()

            # ক্যাপচা মিসম্যাচ হলে পরের চেষ্টায় যাবে
            if "INVALID CODE" in html_upper or "WRONG CODE" in html_upper:
                print("⚠️ ক্যাপচা রিড মেলেনি, পুনরায় চেষ্টা করা হচ্ছে...")
                continue

            # ৪. কোনো রেকর্ড না পাওয়া গেলে
            if "NOT FOUND" in html_upper or "NO RECORD" in html_upper or not html_text.strip():
                print(f"❌ কোনো রেকর্ড পাওয়া যায়নি: {bgd}")
                return {
                    "success": False,
                    "message": "এই BGD নম্বরে কোনো তথ্য পাওয়া যায়নি! নম্বরটি ঠিক আছে কি না পুনরায় যাচাই করুন।"
                }

            # ৫. রেসপন্স থেকে লাইভ তথ্য পার্সিং
            result_soup = BeautifulSoup(html_text, "html.parser")

            # নাম ও সেন্টারের ফিল্ড খোঁজা
            applicant_name = "আবেদনকারী"
            center_name = "IVAC Center"

            # টেবিল থেকে ডেটা পার্স করার চেষ্টা
            for tr in result_soup.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) >= 2:
                    joined = " ".join(cells).upper()
                    if "NAME" in joined and len(cells) >= 2:
                        applicant_name = cells[1]
                    elif "CENTER" in joined and len(cells) >= 2:
                        center_name = cells[1]

            # ৬. লাইভ স্ট্যাটাস এবং স্টেপ নির্ধারণ
            status = "Received At Center"
            step = 1

            if "DELIVERED" in html_upper:
                status = "Delivered From Center"
                step = 4
            elif "READY FOR DELIVERY" in html_upper:
                status = "Ready For Delivery"
                step = 3
            elif "PROCESS INITIATED" in html_upper or "UNDER PROCESS" in html_upper or "HIGH COMMISSION" in html_upper:
                status = "Process Initiated"
                step = 2

            print(f"🎉 [লাইভ ডেটা পাওয়া গেছে] Status: {status} | Step: {step}")

            # সম্পূর্ণ ডাইনামিক লাইভ রেসপন্স
            return {
                "success": True,
                "bgd": bgd,
                "name": applicant_name,
                "status": status,
                "step": step,
                "center": center_name,
                "message": "সফলভাবে লাইভ তথ্য পাওয়া গেছে।"
            }

        except Exception as e:
            print(f"⚠️ চেষ্টার সময় ত্রুটি: {e}")
            continue

    # সব চেষ্টা ব্যর্থ হলে
    return {
        "success": False,
        "message": "ভিসা সার্ভারটি এই মুহূর্তে ধীরগতির অথবা ক্যাপচা পড়তে সমস্যা হচ্ছে। অনুগ্রহ করে ২ মিনিট পর আবার চেষ্টা করুন।"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
