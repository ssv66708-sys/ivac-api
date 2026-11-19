from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import dddocr
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="IVAC Auto-Detect Visa Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("🚀 OCR মডেল লোড হচ্ছে...")
ocr = dddocr.DdddOcr(show_ad=False)
print("✅ OCR রেডি!")


@app.get("/")
def home():
    return {"status": "online", "message": "IVAC Live Tracker API Running"}


@app.get("/track")
def track_visa(bgd: str = Query(..., description="BGD Number")):
    bgd = bgd.strip().upper()
    print(f"\n==========================================")
    print(f"🔍 [LIVE CHECK] রিকোয়েস্ট এসেছে BGD: {bgd}")

    if not bgd or len(bgd) < 6:
        return {"success": False, "message": "সঠিক Web File (BGD) নম্বর প্রদান করুন।"}

    url = "https://www.passtrack.net/regular_passport.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.passtrack.net/regular_passport.php",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,bn;q=0.8"
    }

    last_server_response = ""

    # ৩ বার রিট্রাই করবে
    for attempt in range(1, 4):
        print(f"📡 চেষ্টা চলছে: {attempt}/3...")
        session = requests.Session()
        session.headers.update(headers)

        try:
            # ১. মূল পেজ লোড
            res_page = session.get(url, timeout=15, verify=False)
            soup = BeautifulSoup(res_page.text, "html.parser")

            form = soup.find("form")
            if not form:
                print("❌ পেজে কোনো ফর্ম পাওয়া যায়নি!")
                continue

            # ২. ফর্মের আসল অ্যাকশন URL নির্ধারণ
            action = form.get("action", "")
            if not action:
                post_url = url
            elif action.startswith("http"):
                post_url = action
            else:
                post_url = "https://www.passtrack.net/" + action.lstrip("/")

            # ৩. ক্যাপচা ইমেজ ও টেক্সট সমাধান
            captcha_img = form.find("img", {"src": re.compile(r"captcha|verification|image", re.I)})
            if not captcha_img:
                captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification|image", re.I)})

            captcha_text = ""
            if captcha_img and captcha_img.get("src"):
                img_url = captcha_img["src"]
                if not img_url.startswith("http"):
                    img_url = "https://www.passtrack.net/" + img_url.lstrip("/")

                img_data = session.get(img_url, timeout=10, verify=False).content
                captcha_text = ocr.classification(img_data).strip().upper()
                print(f"🤖 সমাধানকৃত ক্যাপচা: {captcha_text}")

            # ৪. স্বয়ংক্রিয়ভাবে ফর্মের আসল ইনপুট নাম খুঁজে পেলোড তৈরি
            payload = {}
            for inp in form.find_all("input"):
                name = inp.get("name")
                if not name:
                    continue
                inp_type = inp.get("type", "text").lower()
                val = inp.get("value", "")

                if inp_type == "hidden":
                    payload[name] = val
                elif inp_type == "submit":
                    payload[name] = val or "Submit"

            # ফর্মের টেক্সট ইনপুটগুলো শনাক্ত করা
            text_inputs = form.find_all("input", {"type": lambda t: t in [None, "text"]})
            
            if len(text_inputs) >= 2:
                # সাধারণত প্রথমটি ক্যাপচা এবং দ্বিতীয়টি ওয়েব ফাইল, অথবা নাম দিয়ে শনাক্ত
                assigned_bgd = False
                assigned_cap = False
                for inp in text_inputs:
                    n = inp.get("name", "").lower()
                    if any(k in n for k in ["code", "cap", "val", "ver"]):
                        payload[inp["name"]] = captcha_text
                        assigned_cap = True
                    elif any(k in n for k in ["web", "file", "reg", "bgd", "no"]):
                        payload[inp["name"]] = bgd
                        assigned_bgd = True

                # যদি নাম দিয়ে না মিলে পজিশন অনুযায়ী ফিল করা
                if not assigned_cap and len(text_inputs) > 0:
                    payload[text_inputs[0]["name"]] = captcha_text
                if not assigned_bgd and len(text_inputs) > 1:
                    payload[text_inputs[1]["name"]] = bgd
            else:
                # ডিফল্ট ব্যাকআপ পেলোড
                payload["webfile_no"] = bgd
                payload["code"] = captcha_text
                payload["submit"] = "Submit"

            print(f"📤 সাবমিট ডাটা: {payload}")

            # ৫. সাবমিট করা
            post_res = session.post(post_url, data=payload, timeout=20, verify=False)
            res_html = post_res.text
            res_upper = res_html.upper()

            # ক্যাপচা ভুল হলে আবার চেষ্টা
            if "INVALID CODE" in res_upper or "WRONG CODE" in res_upper or "INCORRECT" in res_upper:
                print("⚠️ ক্যাপচা ভুল হয়েছে, রিট্রাই হচ্ছে...")
                continue

            # পেজের মূল টেক্সট এক্সট্রাক্ট করা (ডিবাগিংয়ের জন্য)
            clean_soup = BeautifulSoup(res_html, "html.parser")
            body_text = clean_soup.get_text(separator=" ", strip=True)
            last_server_response = body_text[:150]

            # ৬. ফলাফল পাওয়া গেছে কি না যাচাই
            # passtrack-এ সফল হলে Step-1, Done, অথবা Delivered ইত্যাদি থাকে
            has_step = any(k in res_upper for k in ["STEP-1", "STEP-2", "STEP-3", "STEP-4", "DONE"])
            has_status = any(k in res_upper for k in ["RECEIVED", "INITIATED", "DELIVERY", "DELIVERED", "UNDER PROCESS"])

            if not has_step and not has_status:
                if "NOT FOUND" in res_upper or "NO RECORD" in res_upper:
                    print("❌ সার্ভারে কোনো রেকর্ড নেই।")
                    return {
                        "success": False,
                        "message": f"passtrack.net-এ {bgd} নম্বরের কোনো রেকর্ড নেই। পাসপোর্ট ডেলিভারি হয়ে গেলে অথবা নতুন ফাইল হলে IVAC-এর সেন্ট্রাল পোর্টালে তথ্য আপডেট হতে কিছুটা সময় লাগতে পারে।"
                    }

            # ৭. স্ট্যাটাস ও স্টেপ নির্ধারণ
            status = "Received At Center"
            step = 1

            if "DELIVERED" in res_upper and ("STEP-4" in res_upper or "DONE" in res_upper):
                status = "Delivered From Center"
                step = 4
            elif "READY FOR DELIVERY" in res_upper or ("STEP-3" in res_upper and "DONE" in res_upper):
                status = "Ready For Delivery"
                step = 3
            elif "PROCESS INITIATED" in res_upper or "UNDER PROCESS" in res_upper or ("STEP-2" in res_upper and "DONE" in res_upper):
                status = "Process Initiated"
                step = 2

            # নাম ও সেন্টারের তথ্য বের করা
            applicant_name = "আবেদনকারী"
            center_name = "IVAC Center"
            for tr in clean_soup.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) >= 2:
                    row_txt = " ".join(cells).upper()
                    if "NAME" in row_txt and len(cells) >= 2:
                        applicant_name = cells[1]
                    elif "CENTER" in row_txt and len(cells) >= 2:
                        center_name = cells[1]

            print(f"🎉 ডেটা সফলভাবে পার্স হয়েছে! Status: {status}, Step: {step}")
            return {
                "success": True,
                "bgd": bgd,
                "name": applicant_name,
                "status": status,
                "step": step,
                "center": center_name,
                "message": "সফলভাবে রেকর্ড পাওয়া গেছে"
            }

        except Exception as e:
            print(f"⚠️ চেষ্টা চলাকালীন ত্রুটি: {e}")
            continue

    # ৩ বার চেষ্টার পরও না হলে
    return {
        "success": False,
        "message": f"সার্ভার থেকে সঠিক রেসপন্স আসেনি। সার্ভারের রেসপন্স সারাংশ: '{last_server_response[:80]}...' অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
