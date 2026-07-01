from flask import Flask, request, jsonify
import requests
import time
import re

app = Flask(__name__)

# الهيدرز الأساسية (سيتم تحديث Referer حسب النموذج المختار)
headers = {
    "accept": "*/*",
    "accept-language": "ar-AE,ar;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6",
    "dnt": "1",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
}

MODELS_URLS = {
    "veo": "https://veoaifree.com/veo-video-generator/",
    "seedance": "https://veoaifree.com/seedance-2-0-video-generator-free/"
}

def get_nonce_and_session(proxy_string, model_url):
    session = requests.Session()
    
    # تفعيل البروكسي ومعالجة صيغة (host:port:user:pass)
    if proxy_string:
        parts = proxy_string.split(':')
        if len(parts) == 4:
            proxy_url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        else:
            proxy_url = f"http://{proxy_string}"
            
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        session.proxies.update(proxies)

    try:
        session.headers.update(headers)
        session.headers.update({
            "origin": "https://veoaifree.com",
            "referer": model_url,
        })

        r = session.get(model_url, timeout=30)
        r.raise_for_status() # تفحص إذا كان هناك خطأ في الاتصال (مثل 403 أو 407 بسبب البروكسي)

        nonce_match = re.search(r'"nonce":"([a-f0-9]+)"', r.text)
        if not nonce_match:
            nonce_match = re.search(r'nonce["\s:]+["\']([\w\d]+)["\']', r.text)

        if nonce_match:
            return session, nonce_match.group(1), None
        else:
            return session, "883371da1a", None
            
    except Exception as e:
        # إرجاع تفاصيل الخطأ في حال فشل البروكسي أو الاتصال
        error_msg = str(e)
        return None, None, f"فشل في فتح الصفحة أو جلب Nonce. المشكلة قد تكون من البروكسي: {error_msg}"

def extract_video_url(text):
    urls = re.findall(r'https?://veoaifree\.com/video[s]?/uploads/[^\s"\'<>\\]+\.mp4', text)
    if urls:
        return urls[0].replace("/videos/uploads/", "/video/uploads/")
    urls = re.findall(r'https?://[^\s"\'<>\\]+\.mp4', text)
    if urls:
        return urls[0].replace("/videos/uploads/", "/video/uploads/")
    return None

def wait_for_file(url, session):
    for _ in range(1, 31):
        try:
            r = session.head(url, headers=session.headers, timeout=15)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(10)
    return False

def submit_prompt(prompt, session, nonce, ratio_value):
    try:
        r = session.post(
            "https://veoaifree.com/wp-admin/admin-ajax.php",
            headers=session.headers,
            data={
                "action": "veo_video_generator",
                "nonce": nonce,
                "prompt": prompt,
                "totalVariations": "1",
                "aspectRatio": ratio_value,
                "actionType": "full-video-generate",
            },
            timeout=60,
        )
        r.raise_for_status()
        post_id = r.text.strip()
        if post_id.isdigit():
            return post_id, None
        return None, f"رد غير متوقع من السيرفر عند الإرسال: {post_id}"
    except Exception as e:
        return None, f"حدث خطأ أثناء إرسال البرومبت (تأكد من استقرار البروكسي): {str(e)}"

def poll_video(post_id, session, nonce):
    for attempt in range(1, 61):
        time.sleep(15)
        try:
            pr = session.post(
                "https://veoaifree.com/wp-admin/admin-ajax.php",
                headers=session.headers,
                data={
                    "action": "veo_video_generator",
                    "nonce": nonce,
                    "sceneData": post_id,
                    "actionType": "final-video-results",
                },
                timeout=120,
            )
            raw = pr.text.strip()
        except requests.exceptions.RequestException:
            continue # إذا حدث خطأ مؤقت في الانتظار، نتجاهله ونجرب في المحاولة التالية

        if raw in ("0", "", "false", "null", "-1"):
            continue

        video_url = extract_video_url(raw)
        if video_url:
            if wait_for_file(video_url, session):
                return video_url, None
            else:
                return video_url, "تم العثور على الرابط ولكن الملف لم يكتمل رفعه على السيرفر"
                
    return None, "انتهى وقت الانتظار (Time out) ولم يتم توليد الفيديو"

@app.route('/api', methods=['GET'])
def generate_video():
    prompt = request.args.get('prompt')
    proxy = request.args.get('proxy')
    ratio = request.args.get('ratio', '16:9')
    model = request.args.get('model', 'veo') # الافتراضي veo

    if not prompt:
        return jsonify({"error": "البرومبت (prompt) مطلوب"}), 400
        
    if model not in MODELS_URLS:
         return jsonify({"error": "النموذج المختار غير صحيح. استخدم 'veo' أو 'seedance'"}), 400

    ratio_map = {
        "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "1:1": "VIDEO_ASPECT_RATIO_SQUARE"
    }
    ratio_value = ratio_map.get(ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")
    model_url = MODELS_URLS[model]

    # 1. الاتصال وجلب الجلسة
    session, nonce, err = get_nonce_and_session(proxy, model_url)
    if err:
        return jsonify({"status": "failed", "step": "Initialization / Proxy Connection", "error_details": err}), 500

    # 2. إرسال البرومبت
    post_id, err = submit_prompt(prompt, session, nonce, ratio_value)
    if err:
        return jsonify({"status": "failed", "step": "Submit Prompt", "error_details": err}), 500

    # 3. انتظار الفيديو
    video_url, err = poll_video(post_id, session, nonce)

    if video_url:
        response = {
            "status": "success",
            "model_used": model,
            "prompt": prompt,
            "video_url": video_url,
            "proxy_used": proxy
        }
        if err: # لو الرابط موجود بس الملف لسه متعملوش rendering
            response["warning"] = err
        return jsonify(response)
    else:
        return jsonify({"status": "failed", "step": "Polling Video", "error_details": err}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
