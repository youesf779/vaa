from flask import Flask, request, jsonify
import requests
import time
import re

app = Flask(__name__)

headers = {
    "accept": "*/*",
    "accept-language": "ar-AE,ar;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6",
    "dnt": "1",
    "origin": "https://veoaifree.com",
    "referer": "https://veoaifree.com/veo-video-generator/",
    "sec-ch-ua": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
    "x-requested-with": "XMLHttpRequest",
}

def get_nonce_and_session(proxy_string):
    session = requests.Session()
    
    # تفعيل البروكسي ومعالجة صيغة (host:port:user:pass)
    if proxy_string:
        parts = proxy_string.split(':')
        if len(parts) == 4:
            # صياغة البروكسي الذي يحتوي على يوزر وباسورد بالطريقة الصحيحة للمكتبة
            proxy_url = f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
        else:
            # صياغة البروكسي العادي (host:port)
            proxy_url = f"http://{proxy_string}"
            
        proxies = {
            "http": proxy_url,
            "https": proxy_url
        }
        session.proxies.update(proxies)

    try:
        session.headers.update({
            "User-Agent": headers["user-agent"],
            "Accept-Language": "ar-AE,ar;q=0.9,en-GB;q=0.8,en;q=0.7,en-US;q=0.6",
        })

        r = session.get("https://veoaifree.com/veo-video-generator/", timeout=30)
        nonce_match = re.search(r'"nonce":"([a-f0-9]+)"', r.text)
        if not nonce_match:
            nonce_match = re.search(r'nonce["\s:]+["\']([\w\d]+)["\']', r.text)

        if nonce_match:
            return session, nonce_match.group(1)
        else:
            return session, "883371da1a"
    except Exception as e:
        return session, "883371da1a"

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
            r = session.head(url, headers=headers, timeout=15)
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
            headers=headers,
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
        post_id = r.text.strip()
        if post_id.isdigit():
            return post_id
        return None
    except requests.exceptions.RequestException:
        return None

def poll_video(post_id, session, nonce):
    for attempt in range(1, 61):
        time.sleep(15)
        try:
            pr = session.post(
                "https://veoaifree.com/wp-admin/admin-ajax.php",
                headers=headers,
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
            continue

        if raw in ("0", "", "false", "null", "-1"):
            continue

        video_url = extract_video_url(raw)
        if video_url:
            if wait_for_file(video_url, session):
                return video_url
            else:
                return video_url 
    return None

@app.route('/api', methods=['GET'])
def generate_video():
    prompt = request.args.get('prompt')
    proxy = request.args.get('proxy')
    ratio = request.args.get('ratio', '16:9')

    if not prompt:
        return jsonify({"error": "البرومبت (prompt) مطلوب"}), 400

    ratio_map = {
        "16:9": "VIDEO_ASPECT_RATIO_LANDSCAPE",
        "9:16": "VIDEO_ASPECT_RATIO_PORTRAIT",
        "1:1": "VIDEO_ASPECT_RATIO_SQUARE"
    }
    ratio_value = ratio_map.get(ratio, "VIDEO_ASPECT_RATIO_LANDSCAPE")

    session, nonce = get_nonce_and_session(proxy)

    post_id = submit_prompt(prompt, session, nonce, ratio_value)
    
    if not post_id:
        return jsonify({"error": "فشل في إرسال البرومبت أو البروكسي لا يعمل"}), 500

    video_url = poll_video(post_id, session, nonce)

    if video_url:
        return jsonify({
            "status": "success",
            "prompt": prompt,
            "video_url": video_url,
            "proxy_used": proxy
        })
    else:
        return jsonify({"error": "فشل جلب الفيديو بعد الانتظار"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)