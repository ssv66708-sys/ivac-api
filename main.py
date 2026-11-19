from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import requests
from bs4 import BeautifulSoup
import dddocr
import re
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="IVAC Live Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("🚀 Initializing dddocr...")
ocr = dddocr.DdddOcr(show_ad=False)
print("✅ OCR Model Ready!")


@app.get("/")
def home():
    return {"status": "online", "message": "IVAC Live Tracker is Active"}


@app.get("/track")
def track_visa(bgd: str = Query(..., description="BGD Web File Number")):
    bgd = bgd.strip().upper()
    print(f"\n==========================================")
    print(f"🎯 Searching live passtrack for BGD: {bgd}")

    url = "https://www.passtrack.net/regular_passport.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.passtrack.net/regular_passport.php",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
    }

    last_debug_text = ""

    # ৩ বার স্বয়ংক্রিয়ভাবে চেষ্টা করার লুপ
    for attempt in range(1, 4):
        print(f"🔄 Attempt {attempt} of 3...")
        session = requests.Session()
        session.headers.update(headers)

        try:
            # ১. পেজ লোড করা
            res = session.get(url, timeout=15, verify=False)
            soup = BeautifulSoup(res.text, "html.parser")
            form = soup.find("form")

            if not form:
                print("❌ কোনো ফর্ম পাওয়া যায়নি!")
                continue

            # ২. ক্যাপচা ইমেজ খুঁজে কোড পড়া
            captcha_img = form.find("img", {"src": re.compile(r"captcha|verification|code|\.php", re.I)})
            if not captcha_img:
                captcha_img = soup.find("img", {"src": re.compile(r"captcha|verification|code|\.php", re.I)})

            captcha_code = ""
            if captcha_img and captcha_img.get("src"):
                img_url = captcha_img["src"]
                if not img_url.startswith("http"):
                    img_url = "https://www.passtrack.net/" + img_url.lstrip("/")

                img_bytes = session.get(img_url, timeout=10, verify=False).content
                captcha_code = ocr.classification(img_bytes).strip().upper()
                print(f"🧩 Decoded Captcha: {captcha_code}")

            # ৩. ফর্মের ইনপুট নামগুলো অটোমেটিক ডিটেক্ট করা (স্মার্ট ম্যাপিং)
            payload = {}
            text_inputs = []

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
                elif inp_type in ["text", "search"]:
                    text_inputs.append(inp)

            # ফর্মের কোন ফিল্ড BGD এবং কোনটি ক্যাপচা তা শনাক্ত করা
            assigned_bgd = False
            assigned_captcha = False

            for inp in text_inputs:
                name_attr = inp.get("name", "")
                name_lower = name_attr.lower()

                # ক্যাপচা ফিল্ড চেনার উপায়
                if any(k in name_lower for k in ["code", "cap", "ver", "val"]):
                    payload[name_attr] = captcha_code
                    assigned_captcha = True
                # BGD ফিল্ড চেনার উপায়
                elif any(k in name_lower for k in ["web", "file", "reg", "bgd", "num", "pass"]):
                    payload[name_attr] = bgd
                    assigned_bgd = True

            # নাম দিয়ে না মিললে পজিশন অনুযায়ী বসানো (সাধারণত ১ম টি BGD, ২য় টি ক্যাপচা)
            if not assigned_bgd and len(text_inputs) >= 1:
                payload[text_inputs[0].get("name")] = bgd
            if not assigned_captcha and len(text_inputs) >= 2:
                payload[text_inputs[1].get("name")] = captcha_code

            # ব্যাকআপ ফিল্ড নিশ্চিতকরণ
            payload["webfile_no"] = bgd
            payload["code"] = captcha_code
            payload["submit"] = "Submit"

            print(f"📤 Auto Payload Sent: {payload}")

            # ৪. সাবমিট করা
            post_action = form.get("action", "")
            if not post_action:
                post_url = url
            elif post_action.startswith("http"):
                post_url = post_action
            else:
                post_url = "https://www.passtrack.net/" + post_action.lstrip("/")

            post_res = session.post(post_url, data=payload, timeout=20, verify=False)
            res_html = post_res.text
            res_upper = res_html.upper()

            # ক্যাপচা ভুল হলে পরের চেষ্টায় যাবে
            if "INVALID CODE" in res_upper or "WRONG CODE" in res_upper:
                print("⚠️ Captcha mismatch, retrying...")
                continue

            # পেজের মূল টেক্সট বের করা
            res_soup = BeautifulSoup(res_html, "html.parser")
            clean_body = res_soup.get_text(separator=" ", strip=True)
            last_debug_text = clean_body[:200]

            # ৫. রেজাল্ট যাচাই
            # সফল হলে পেজে এই শব্দগুলো থাকবে
            is_found = False
            status = "Received At Center"
            step = 1

            if "DELIVERED" in res_upper:
                status = "Delivered From Center"
                step = 4
                is_found = True
            elif "READY FOR DELIVERY" in res_upper:
                status = "Ready For Delivery"
                step = 3
                is_found = True
            elif "PROCESS INITIATED" in res_upper or "UNDER PROCESS" in res_upper:
                status = "Process Initiated"
                step = 2
                is_found = True
            elif "RECEIVED" in res_upper or "ACCEPTED" in res_upper:
                status = "Received At Center"
                step = 1
                is_found = True

            # যদি টেবিল পাওয়া যায়
            applicant_name = "ভিসা আবেদনকারী"
            center_name = "IVAC Center"

            for tr in res_soup.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if len(cells) >= 2:
                    joined = " ".join(cells).upper()
                    if bgd in joined:
                        is_found = True
                    if "NAME" in joined:
                        applicant_name = cells[1]
                    elif "CENTER" in joined:
                        center_name = cells[1]

            if is_found:
                print(f"✅ Success found for {bgd}! Status: {status}")
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
            print(f"⚠️ Error on attempt {attempt}: {e}")
            continue

    # যদি ৩ বারেই কোনো ফলাফল না মেলে
    print(f"❌ Failed after 3 attempts. Last reply: {last_debug_text}")
    return {
        "success": False,
        "message": f"passtrack থেকে সরাসরি রেসপন্স: '{last_debug_text[:120]}...' (ক্যাপচা মিস অথবা সার্ভার সাময়িক ব্যস্ত, আবার চেষ্টা করুন)"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
