import os, io, re, json, time, shutil, base64, zipfile, secrets, threading, subprocess, tempfile
from flask import (Flask, request, render_template_string, send_from_directory,
                   send_file, abort, session, redirect, after_this_request)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image, ImageOps
import qrcode

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(BASE, 'uploads')
META = os.path.join(BASE, 'albums_meta.json')
IMG = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}
VID = {'.mp4', '.mov', '.webm'}
MAX_FILES = 30
GRACE = 600
os.makedirs(UPLOADS, exist_ok=True)
Image.MAX_IMAGE_PIXELS = 80_000_000


def secret():
    k = os.environ.get('FLASK_SECRET_KEY')
    if k:
        return k
    p = os.path.join(BASE, '.secret_key')
    if os.path.exists(p):
        return open(p).read().strip()
    k = secrets.token_hex(32)
    open(p, 'w').write(k)
    return k


app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config.update(SECRET_KEY=secret(), MAX_CONTENT_LENGTH=500 * 1024 * 1024,
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
lock = threading.Lock()
fails = {}


def load():
    try:
        with open(META, encoding='utf-8') as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save(m):
    tmp = META + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(m, f, ensure_ascii=False)
    os.replace(tmp, META)


def adir(aid):
    return os.path.join(UPLOADS, aid)


def rm(aid):
    shutil.rmtree(adir(aid), ignore_errors=True)


def dead(i, now):
    mv = i.get('max_views', 0)
    return now > i.get('expires_at', 0) or (
        mv and i.get('views', 0) >= mv and now > i.get('last_view', now) + GRACE)


def sweeper():
    while True:
        try:
            with lock:
                m, now = load(), time.time()
                gone = [a for a, i in m.items() if dead(i, now)]
                for a in gone:
                    rm(a)
                    del m[a]
                if gone:
                    save(m)
        except Exception:
            pass
        time.sleep(60)


threading.Thread(target=sweeper, daemon=True).start()

valid_aid = lambda a: isinstance(a, str) and re.fullmatch(r'[0-9a-f]{16}', a)
valid_name = lambda n: isinstance(n, str) and re.fullmatch(
    r'[0-9a-f]{10}\.(jpg|png|webp|gif|mp4|mov|webm)', n)


def get_album(aid):
    if not valid_aid(aid):
        return None
    with lock:
        i = load().get(aid)
    return None if not i or dead(i, time.time()) else i


def files_of(aid):
    d = adir(aid)
    if not os.path.isdir(d):
        return []
    fs = [f for f in os.listdir(d) if valid_name(f)]
    return sorted(fs, key=lambda f: (os.path.getmtime(os.path.join(d, f)), f))


def clean_image(fs, out, ext):
    img = Image.open(fs.stream)
    img.verify()
    fs.stream.seek(0)
    img = Image.open(fs.stream)
    if ext == '.gif':
        img.save(out, save_all=True, loop=img.info.get('loop', 0))
        return
    img = ImageOps.exif_transpose(img)
    kw = {}
    if ext == '.jpg':
        if img.mode != 'RGB':
            img = img.convert('RGB')
        kw = {'quality': 92, 'optimize': True}
    elif ext == '.webp':
        kw = {'quality': 92}
    elif img.mode not in ('RGB', 'RGBA', 'L', 'P'):
        img = img.convert('RGB')
    img.save(out, **kw)


def clean_video(fs, out):
    raw = out + '.raw'
    fs.save(raw)
    ff = shutil.which('ffmpeg')
    if ff:
        try:
            r = subprocess.run([ff, '-y', '-i', raw, '-map_metadata', '-1', '-c', 'copy', out],
                               capture_output=True, timeout=300)
            if r.returncode == 0 and os.path.getsize(out) > 0:
                os.remove(raw)
                return True
        except Exception:
            pass
    if os.path.exists(out):
        os.remove(out)
    os.replace(raw, out)
    return False


def csrf():
    if 't' not in session:
        session['t'] = secrets.token_hex(16)
    return session['t']


def csrf_ok():
    return secrets.compare_digest(request.form.get('t', ''), session.get('t', 'x'))


def allowed(aid, i):
    if i.get('pin') and aid not in session.get('ok', []):
        return False
    if i.get('max_views') and aid not in session.get('seen', []):
        return False
    return True


def left(i):
    s = max(0, int(i['expires_at'] - time.time()))
    h, m = s // 3600, s % 3600 // 60
    return f'{h // 24}d {h % 24}h' if h >= 24 else f'{h}h {m}m'


@app.after_request
def headers(r):
    r.headers.update({
        'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
        'X-Robots-Tag': 'noindex, nofollow, noarchive', 'Referrer-Policy': 'no-referrer',
        'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; media-src 'self'; "
                                   "style-src 'unsafe-inline'; script-src 'unsafe-inline'; form-action 'self'"})
    if request.path != '/':
        r.headers['Cache-Control'] = 'no-store'
    return r


LAYOUT = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">
<title>Fuse: share photos and videos that burn out</title><style>
:root{--bg:#dde6ea;--ink:#14213d;--mute:#51607a;--card:#f7fafb;--line:#b9c7cf;--hot:#ff5a1f;--sea:#12706b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 Verdana,Tahoma,sans-serif}
.wrap{max-width:560px;margin:0 auto;padding:22px 16px 60px}
.brand{font:800 30px/1 Rockwell,'Roboto Slab',Georgia,serif;letter-spacing:-1px;display:flex;align-items:center;gap:10px}
.fuse{width:46px;height:8px;border-radius:8px;background:linear-gradient(90deg,var(--ink) 70%,var(--hot) 70%);position:relative}
.fuse:after{content:"";position:absolute;right:-3px;top:-4px;width:14px;height:14px;border-radius:50%;background:var(--hot);box-shadow:0 0 0 4px #ff5a1f33;animation:b 1.4s infinite alternate}
@keyframes b{to{box-shadow:0 0 0 8px #ff5a1f00}}@media(prefers-reduced-motion:reduce){.fuse:after{animation:none}}
h1{font:800 34px/1.1 Rockwell,'Roboto Slab',Georgia,serif;margin:26px 0 8px;letter-spacing:-1px}
.sub{color:var(--mute);margin:0 0 22px}
.card{background:var(--card);border:2px solid var(--ink);border-radius:6px 22px 6px 22px;padding:20px;box-shadow:6px 6px 0 var(--ink)}
label,.lab{display:block;font-weight:700;font-size:14px;margin:16px 0 6px}
input[type=text],input[type=password]{width:100%;padding:12px;border:2px solid var(--line);border-radius:10px;font:inherit;background:#fff}
input:focus-visible,button:focus-visible,a:focus-visible,summary:focus-visible,.chip:focus-within{outline:3px solid var(--hot);outline-offset:2px}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{position:relative}
.chip input{position:absolute;opacity:0}.chip span{display:block;padding:9px 14px;border:2px solid var(--line);border-radius:30px;background:#fff;font-size:14px;cursor:pointer}
.chip input:checked+span{background:var(--ink);border-color:var(--ink);color:#fff}
.drop{display:block;margin-top:18px;border:2px dashed var(--mute);border-radius:12px;padding:26px 12px;text-align:center;cursor:pointer;background:#fff}
.drop b{font:700 18px Rockwell,Georgia,serif}.drop small{display:block;color:var(--mute)}
.btn{display:block;width:100%;margin-top:18px;padding:14px;border:2px solid var(--ink);border-radius:12px;background:var(--hot);color:#fff;font:800 17px Verdana,sans-serif;cursor:pointer}
.btn.alt{background:#fff;color:var(--ink)}.btn:disabled{opacity:.6}
.err{background:#ffe3dc;border:2px solid var(--hot);padding:10px 12px;border-radius:10px;margin-bottom:14px;font-weight:700;font-size:14px}
.warn{background:#fff3c4;border:2px solid #d9a800;padding:10px 12px;border-radius:10px;font-size:13px;margin-top:12px}
.res{margin-top:24px;text-align:center}.res img.qr{width:220px;height:220px;image-rendering:pixelated;border:2px solid var(--ink);border-radius:8px;padding:8px;background:#fff}
.link{display:flex;gap:6px;margin-top:12px}.link input{flex:1;font-size:13px}.link button{padding:0 14px;border:2px solid var(--ink);border-radius:10px;background:var(--sea);color:#fff;font-weight:700;cursor:pointer}
.meta{color:var(--mute);font-size:13px;margin-top:10px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px;margin-top:16px}
.grid a,.grid video{display:block;width:100%;aspect-ratio:1;object-fit:cover;border-radius:8px;border:2px solid var(--ink);background:#000}
.grid img{width:100%;height:100%;object-fit:cover;display:block;border-radius:6px}.grid a{overflow:hidden}
.timer{display:inline-block;background:var(--ink);color:#fff;border-radius:30px;padding:5px 14px;font-size:13px;font-weight:700}
.foot{margin-top:22px;color:var(--mute);font-size:12px;text-align:center}
</style></head><body><div class="wrap"><div class="brand">Fuse<i class="fuse"></i></div>
<!--BODY--></div></body></html>"""

HOME = """<h1>Share it. Then it's gone.</h1>
<p class="sub">Upload photos or videos, get a QR code. The album deletes itself when the fuse runs out.</p>
<div class="card">{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method="POST" enctype="multipart/form-data" onsubmit="b.disabled=true;b.textContent='Uploading, please wait...'">
<input type="hidden" name="t" value="{{ t }}">
<label for="title">Album name (optional)</label>
<input type="text" id="title" name="title" maxlength="80" placeholder="Goa trip, Sam's birthday">
<div class="lab">Delete after</div><div class="chips">
{% for v,l in [(24,'24 hours'),(96,'4 days'),(120,'5 days')] %}
<label class="chip"><input type="radio" name="expiry" value="{{ v }}" {{ 'checked' if v==24 }}><span>{{ l }}</span></label>{% endfor %}</div>
<div class="lab">Opens allowed</div><div class="chips">
