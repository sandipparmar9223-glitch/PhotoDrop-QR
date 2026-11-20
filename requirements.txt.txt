import os
import re
import socket
import threading
import webbrowser
from flask import Flask, request, render_template_string

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY') or os.urandom(24).hex()
PORT = 5000

# ==============================================================================
# यहाँ से आप बाद में कभी भी वेबसाइट का नाम, रंग, टेक्स्ट और सेवाएं बदल सकते हैं
# ==============================================================================
SITE_CONFIG = {
    "brand_badge": "PY",
    "brand_name": "WebCraft Python",
    "tagline": "● Python से बना सुरक्षित और लचीला वेब सिस्टम",
    "primary_color": "#0f172a",
    "accent_color": "#2563eb",
    "accent_hover": "#1d4ed8",
    "hero_title": "आसानी से बदलने और बढ़ाने लायक सुरक्षित वेबसाइट",
    "hero_subtitle": "पूरा लुक और लॉजिक Python के भीतर तैयार है, ताकि आप जब चाहें तब नाम, रंग, सेवाएं या फ़ीचर्स तुरंत अपडेट कर सकें।",
    "hero_cta_text": "संपर्क करें",
    "services_heading": "हमारी मुख्य सेवाएं",
    "services": [
        {
            "title": "आसान कस्टमाइज़ेशन",
            "desc": "SITE_CONFIG में बदलाव करते ही वेबसाइट का टेक्स्ट, ब्रांड नाम और थीम रंग तुरंत अपडेट हो जाते हैं।"
        },
        {
            "title": "सुरक्षित आर्किटेक्चर",
            "desc": "साफ HTML/CSS, सुरक्षित हेडर, rel='noopener noreferrer' और बिना अनजान बाहरी स्क्रिप्ट के तैयार कोड।"
        },
        {
            "title": "मोबाइल और डेस्कटॉप रेडी",
            "desc": "हर स्क्रीन साइज के अनुसार खुद-ब-खुद ढलने वाला रिस्पॉन्सिव लेआउट।"
        },
    ],
    "footer_text": "© 2026 WebCraft Python. सर्वाधिकार सुरक्षित।",
    "external_link_label": "प्राइवेसी व सुरक्षा जानकारी",
    "external_link_url": "https://example.com/privacy",
}
# ==============================================================================


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def sanitize_text(value, max_len=120):
    cleaned = re.sub(r'[\x00-\x1f\x7f]', '', str(value or '')).strip()
    return cleaned[:max_len]


def sanitize_safe_url(url_str):
    u = str(url_str or '').strip()
    if u.startswith(('https://', 'http://')):
        return u
    return "https://example.com"


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="hi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="X-Content-Type-Options" content="nosniff">
<title>{{ cfg.brand_name }} | {{ cfg.hero_title }}</title>
<style>
* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
    font-family: 'Segoe UI', system-ui, -apple-system, sans-serif;
    -webkit-user-select: none;
    -moz-user-select: none;
    -ms-user-select: none;
    user-select: none;
}
img, svg {
    -webkit-user-drag: none;
    user-drag: none;
}
:root {
    --primary: {{ cfg.primary_color }};
    --accent: {{ cfg.accent_color }};
    --accent-hover: {{ cfg.accent_hover }};
    --bg-light: #f8fafc;
    --text-main: #334155;
    --white: #ffffff;
}
body {
    background-color: var(--bg-light);
    color: var(--text-main);
    line-height: 1.6;
    overflow-x: hidden;
}
header {
    background-color: var(--white);
    border-bottom: 1px solid #e2e8f0;
    position: sticky;
    top: 0;
    z-index: 100;
}
.navbar {
    max-width: 1140px;
    margin: 0 auto;
    padding: 14px 20px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    flex-wrap: wrap;
    gap: 12px;
}
.logo {
    font-size: 20px;
    font-weight: 800;
    color: var(--primary);
    display: flex;
    align-items: center;
    gap: 8px;
}
.logo-badge {
    background: var(--accent);
    color: var(--white);
    padding: 4px 9px;
    border-radius: 8px;
    font-size: 13px;
}
.status-tag {
    font-size: 12px;
    font-weight: 700;
    color: #15803d;
}
.hero {
    background: linear-gradient(135deg, var(--primary) 0%, #1e293b 100%);
    color: var(--white);
    padding: 64px 20px;
    text-align: center;
}
.hero-inner {
    max-width: 780px;
    margin: 0 auto;
}
.hero h1 {
    font-size: 34px;
    line-height: 1.25;
    margin-bottom: 14px;
}
.hero p {
    font-size: 16px;
    color: #cbd5e1;
    margin-bottom: 24px;
}
.btn {
    display: inline-block;
    background-color: var(--accent);
    color: var(--white);
    padding: 12px 24px;
    border-radius: 10px;
    text-decoration: none;
    font-weight: 700;
    font-size: 15px;
    border: none;
    cursor: pointer;
    transition: background-color 0.2s, transform 0.2s;
}
.btn:hover {
    background-color: var(--accent-hover);
    transform: translateY(-1px);
}
.container {
    max-width: 1140px;
    margin: 0 auto;
    padding: 52px 20px;
}
.section-title {
    text-align: center;
    font-size: 26px;
    color: var(--primary);
    margin-bottom: 28px;
}
.grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 20px;
}
.card {
    background: var(--white);
    padding: 24px;
    border-radius: 14px;
    border: 1px solid #e2e8f0;
    border-top: 4px solid var(--accent);
    box-shadow: 0 6px 18px rgba(15, 23, 42, 0.04);
}
.card h3 {
    color: var(--primary);
    font-size: 18px;
    margin-bottom: 10px;
}
.contact-box {
    background: var(--white);
    max-width: 640px;
    margin: 0 auto;
    padding: 32px 24px;
    border-radius: 16px;
    border: 1px solid #e2e8f0;
    box-shadow: 0 8px 24px rgba(15, 23, 42, 0.05);
}
.form-group {
    margin-bottom: 16px;
}
.form-group label {
    display: block;
    font-weight: 700;
    color: var(--primary);
    margin-bottom: 6px;
    font-size: 14px;
}
.form-group input,
.form-group textarea {
    width: 100%;
    padding: 11px 14px;
    border: 1.5px solid #cbd5e1;
    border-radius: 10px;
    font-size: 14px;
    outline: none;
    -webkit-user-select: text;
    -moz-user-select: text;
    -ms-user-select: text;
    user-select: text;
}
.form-group input:focus,
.form-group textarea:focus {
    border-color: var(--accent);
}
.msg-box {
    margin-top: 14px;
    padding: 12px 14px;
    border-radius: 10px;
    background: #f0fdf4;
    border: 1px solid #bbf7d0;
    color: #166534;
    font-weight: 700;
    font-size: 14px;
}
footer {
    background: var(--primary);
    color: #94a3b8;
    text-align: center;
    padding: 28px 16px;
    font-size: 14px;
}
footer a {
    color: var(--white);
    text-decoration: none;
    font-weight: 600;
}
@media (max-width: 768px) {
    .hero { padding: 44px 16px; }
    .hero h1 { font-size: 25px; }
    .container { padding: 36px 14px; }
    .contact-box { padding: 24px 16px; }
}
</style>
</head>
<body>
<header>
    <nav class="navbar">
        <div class="logo">
            <span class="logo-badge">{{ cfg.brand_badge }}</span>
            <span>{{ cfg.brand_name }}</span>
        </div>
        <div class="status-tag">{{ cfg.tagline }}</div>
    </nav>
</header>

<section class="hero">
    <div class="hero-inner">
        <h1>{{ cfg.hero_title }}</h1>
        <p>{{ cfg.hero_subtitle }}</p>
        <a href="#contact" class="btn">{{ cfg.hero_cta_text }}</a>
    </div>
</section>

<section class="container">
    <h2 class="section-title">{{ cfg.services_heading }}</h2>
    <div class="grid">
        {% for item in cfg.services %}
        <div class="card">
            <h3>{{ item.title }}</h3>
            <p>{{ item.desc }}</p>
        </div>
        {% endfor %}
    </div>
</section>

<section id="contact" class="container" style="padding-top: 0;">
    <div class="contact-box">
        <h2 class="section-title" style="margin-bottom: 18px;">{{ cfg.hero_cta_text }}</h2>
        <form method="POST" action="/#contact">
            <div class="form-group">
                <label for="name">आपका नाम *</label>
                <input type="text" id="name" name="name" maxlength="80" required placeholder="अपना नाम लिखें">
            </div>
            <div class="form-group">
                <label for="message">आपका संदेश या बदलाव की ज़रूरत *</label>
                <textarea id="message" name="message" rows="4" maxlength="500" required placeholder="यहाँ लिखें..."></textarea>
            </div>
            <button type="submit" class="btn" style="width: 100%;">संदेश भेजें</button>
        </form>
        {% if submitted_reply %}
        <div class="msg-box">{{ submitted_reply }}</div>
        {% endif %}
    </div>
</section>

<footer>
    <p>{{ cfg.footer_text }}</p>
    <p style="margin-top: 8px;">
        <a href="{{ safe_ext_url }}" target="_blank" rel="noopener noreferrer">{{ cfg.external_link_label }}</a>
    </p>
</footer>

<script>
(function() {
    'use strict';

    document.addEventListener('contextmenu', function(e) {
        e.preventDefault();
    });

    document.addEventListener('dragstart', function(e) {
        e.preventDefault();
    });

    document.addEventListener('copy', function(e) {
        const active = document.activeElement;
        if (!active || !['INPUT', 'TEXTAREA'].includes(active.tagName)) {
            e.preventDefault();
        }
    });

    document.addEventListener('cut', function(e) {
        const active = document.activeElement;
        if (!active || !['INPUT', 'TEXTAREA'].includes(active.tagName)) {
            e.preventDefault();
        }
    });

    document.addEventListener('keydown', function(e) {
        if (
            (e.ctrlKey && ['c', 'C', 'u', 'U', 's', 'S', 'p', 'P'].includes(e.key)) ||
            (e.ctrlKey && e.shiftKey && ['I', 'i', 'J', 'j', 'C', 'c'].includes(e.key)) ||
            e.key === 'F12'
        ) {
            e.preventDefault();
        }
    });
})();
</script>
</body>
</html>
"""


@app.after_request
def add_security_headers(response):
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "frame-ancestors 'none'; "
        "base-uri 'self';"
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response


@app.route('/', methods=['GET', 'POST'])
def index():
    submitted_reply = None
    if request.method == 'POST':
        user_name = sanitize_text(request.form.get('name'), 80)
        user_msg = sanitize_text(request.form.get('message'), 500)
        if user_name and user_msg:
            submitted_reply = f"धन्यवाद, {user_name}! आपका संदेश सुरक्षित रूप से दर्ज कर लिया गया है।"

    safe_cfg = dict(SITE_CONFIG)
    safe_ext_url = sanitize_safe_url(SITE_CONFIG.get("external_link_url"))
    return render_template_string(
        PAGE_TEMPLATE,
        cfg=safe_cfg,
        safe_ext_url=safe_ext_url,
        submitted_reply=submitted_reply
    )


if __name__ == '__main__':
    ip = get_local_ip()
    print(f"\nलोकल लिंक: http://127.0.0.1:{PORT}")
    print(f"एक ही Wi-Fi/नेटवर्क से लिंक: http://{ip}:{PORT}\n")
    threading.Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True)