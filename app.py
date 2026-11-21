import os, io, re, json, time, shutil, base64, zipfile, secrets, threading, subprocess
from flask import (Flask, request, render_template_string, send_from_directory,
                   send_file, abort, session, redirect)
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
GRACE = 600  # seconds a one-time album stays alive after its first view
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
lock = threading.Lock()  # single-process lock: run with ONE worker (see notes)
fails = {}  # (aid, ip) -> [count, locked_until]


# ---------- storage ----------
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


# ---------- media cleaning ----------
def clean_image(fs, out, ext):
    img = Image.open(fs.stream)
    img.verify()
    fs.stream.seek(0)
    img = Image.open(fs.stream)
    if ext == '.gif':
        img.save(out, save_all=True, loop=img.info.get('loop', 0))
        return
    img = ImageOps.exif_transpose(img)  # fix rotation BEFORE metadata is dropped
    kw = {}
    if ext == '.jpg':
        if img.mode != 'RGB':
            img = img.convert('RGB')
        kw = {'quality': 92, 'optimize': True}
    elif ext == '.webp':
        kw = {'quality': 92}
    elif img.mode not in ('RGB', 'RGBA', 'L', 'P'):
        img = img.convert('RGB')
    img.save(out, **kw)  # Pillow writes no EXIF/GPS unless asked to


def clean_video(fs, out):
    """Returns True if metadata was stripped (needs ffmpeg), False if saved as-is."""
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


# ---------- helpers ----------
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


# ---------- UI ----------
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
{% for v,l in [(0,'Unlimited'),(1,'Once'),(5,'5 times'),(25,'25 times')] %}
<label class="chip"><input type="radio" name="max_views" value="{{ v }}" {{ 'checked' if v==0 }}><span>{{ l }}</span></label>{% endfor %}</div>
<label for="pin">PIN (optional, 4 to 6 digits)</label>
<input type="password" id="pin" name="pin" inputmode="numeric" pattern="\\d{4,6}" maxlength="6" autocomplete="off" placeholder="Leave empty for no PIN">
<label class="drop" for="f"><b id="fl">Choose photos or videos</b>
<small>JPG, PNG, WEBP, GIF, MP4, MOV, WEBM. Up to 30 files, 500 MB total.</small>
<input type="file" id="f" name="files" multiple accept="image/*,video/*" hidden
onchange="fl.textContent=this.files.length?this.files.length+' file(s) selected':'Choose photos or videos'"></label>
<button class="btn" name="b" type="submit">Create QR code</button></form></div>
{% if qr %}<div class="res"><h1 style="font-size:26px">Your album is live</h1>
<img class="qr" src="data:image/png;base64,{{ qr }}" alt="QR code for the album link">
<div class="link"><input type="text" id="u" value="{{ url }}" readonly aria-label="Album link">
<button type="button" onclick="u.select();navigator.clipboard&&navigator.clipboard.writeText(u.value);this.textContent='Copied'">Copy</button></div>
<p class="meta">Deletes in {{ left }}{% if mv %}, or after {{ mv }} open(s){% endif %}{% if pin %}. PIN protected{% endif %}.</p>
{% if raw_video %}<div class="warn">ffmpeg is not installed on this server, so location data inside videos was not removed. Photos were cleaned.</div>{% endif %}
<form method="POST" action="/delete/{{ aid }}" onsubmit="return confirm('Delete this album now?')">
<input type="hidden" name="t" value="{{ t }}"><input type="hidden" name="k" value="{{ owner }}">
<button class="btn alt" type="submit">Delete album now</button></form></div>{% endif %}
<p class="foot">Photos are re-encoded and stripped of GPS and camera data. Albums are private to people with the link.</p>"""

PIN = """<h1>This album is locked</h1><p class="sub">Enter the PIN the sender gave you.</p>
<div class="card">{% if error %}<div class="err">{{ error }}</div>{% endif %}
<form method="POST"><input type="hidden" name="t" value="{{ t }}">
<label for="pin">PIN</label><input type="password" id="pin" name="pin" inputmode="numeric" maxlength="6" autocomplete="off" autofocus>
<button class="btn" type="submit">Unlock album</button></form></div>"""

ALBUM = """<h1>{{ title or 'Shared album' }}</h1>
<p class="sub"><span class="timer">Burns out in {{ left }}</span>{% if mv %} &nbsp;Opens used: {{ views }} of {{ mv }}{% endif %}</p>
<div class="grid">{% for f in files %}{% if f.rsplit('.',1)[1] in ['mp4','mov','webm'] %}
<video src="/m/{{ aid }}/{{ f }}" controls preload="metadata" playsinline></video>
{% else %}<a href="/m/{{ aid }}/{{ f }}" target="_blank" rel="noopener"><img src="/m/{{ aid }}/{{ f }}" alt="" loading="lazy"></a>{% endif %}{% endfor %}</div>
<a class="btn" style="text-decoration:none;text-align:center" href="/zip/{{ aid }}">Download all as ZIP</a>"""

GONE = """<h1>This album is gone</h1><p class="sub">It expired, hit its open limit, or the sender deleted it. Ask them to share a new one.</p>
<a class="btn" style="text-decoration:none;text-align:center" href="/">Make your own album</a>"""


def page(body, status=200, **ctx):
    return render_template_string(LAYOUT.replace('<!--BODY-->', body), t=csrf(), **ctx), status


# ---------- routes ----------
@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'GET':
        return page(HOME)
    if not csrf_ok():
        return page(HOME, 400, error='Session expired. Please try again.')
    up = [f for f in request.files.getlist('files') if f and f.filename]
    pin = request.form.get('pin', '').strip()
    expiry = request.form.get('expiry', '24')
    views = request.form.get('max_views', '0')
    if not up:
        return page(HOME, 400, error='Pick at least one photo or video.')
    if len(up) > MAX_FILES:
        return page(HOME, 400, error=f'Please upload {MAX_FILES} files or fewer at a time.')
    if pin and not re.fullmatch(r'\d{4,6}', pin):
        return page(HOME, 400, error='PIN must be 4 to 6 digits.')
    hours = int(expiry) if expiry in ('24', '96', '120') else 24
    mv = int(views) if views in ('0', '1', '5', '25') else 0

    aid, owner = secrets.token_hex(8), secrets.token_urlsafe(16)
    os.makedirs(adir(aid))
    saved, raw_video = 0, False
    for fs in up:
        ext = os.path.splitext(fs.filename)[1].lower()
        ext = '.jpg' if ext == '.jpeg' else ext
        if ext not in IMG and ext not in VID:
            continue
        out = os.path.join(adir(aid), secrets.token_hex(5) + ext)
        try:
            if ext in VID:
                raw_video |= not clean_video(fs, out)
            else:
                clean_image(fs, out, ext)
            saved += 1
        except Exception:
            if os.path.exists(out):
                os.remove(out)
    if not saved:
        rm(aid)
        return page(HOME, 400, error='None of those files could be read. Use JPG, PNG, WEBP, GIF, MP4, MOV or WEBM.')

    with lock:
        m = load()
        m[aid] = {'title': request.form.get('title', '').strip()[:80],
                  'expires_at': time.time() + hours * 3600, 'max_views': mv, 'views': 0,
                  'pin': generate_password_hash(pin) if pin else '',
                  'owner': generate_password_hash(owner)}
        save(m)
    url = request.host_url + 'a/' + aid
    buf = io.BytesIO()
    qrcode.make(url, box_size=8, border=2).save(buf, format='PNG')
    return page(HOME, qr=base64.b64encode(buf.getvalue()).decode(), url=url, aid=aid, owner=owner,
                left='24 hours' if hours == 24 else f'{hours // 24} days',
                mv=mv, pin=bool(pin), raw_video=raw_video)


@app.route('/a/<aid>', methods=['GET', 'POST'])
def view(aid):
    i = get_album(aid)
    if not i:
        return page(GONE, 404)
    if i['pin'] and aid not in session.get('ok', []):
        err = None
        if request.method == 'POST':
            if not csrf_ok():
                abort(400)
            k, now = (aid, request.remote_addr), time.time()
            c, until = fails.get(k, [0, 0])
            if now < until:
                err = 'Too many wrong tries. Wait a few minutes and try again.'
            elif check_password_hash(i['pin'], request.form.get('pin', '')):
                fails.pop(k, None)
                session['ok'] = (session.get('ok', []) + [aid])[-40:]
                return redirect(request.path)
            else:
                c += 1
                fails[k] = [0, now + 600] if c >= 5 else [c, 0]
                err = 'Wrong PIN.'
        return page(PIN, 401 if err else 200, error=err)
    if aid not in session.get('seen', []):
        with lock:
            m = load()
            j = m.get(aid)
            if not j or (j['max_views'] and j['views'] >= j['max_views']):
                return page(GONE, 410)
            j['views'] += 1
            j['last_view'] = time.time()
            save(m)
            i = j
        session['seen'] = (session.get('seen', []) + [aid])[-40:]
    fs = files_of(aid)
    if not fs:
        return page(GONE, 404)
    return page(ALBUM, title=i['title'], files=fs, aid=aid, left=left(i), mv=i['max_views'], views=i['views'])


@app.route('/m/<aid>/<name>')
def media(aid, name):
    i = get_album(aid)
    if not i or not valid_name(name) or not allowed(aid, i):
        abort(404)
    return send_from_directory(adir(aid), name, conditional=True)


@app.route('/zip/<aid>')
def zipall(aid):
    i = get_album(aid)
    if not i or not allowed(aid, i):
        abort(404)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_STORED) as z:
        for n, f in enumerate(files_of(aid), 1):
            z.write(os.path.join(adir(aid), f), f'{n:02d}_{f}')
    buf.seek(0)
    return send_file(buf, mimetype='application/zip', as_attachment=True, download_name='album.zip')


@app.route('/delete/<aid>', methods=['POST'])
def delete(aid):
    if not csrf_ok():
        abort(400)
    with lock:
        m = load()
        i = m.get(aid) if valid_aid(aid) else None
        if i and check_password_hash(i['owner'], request.form.get('k', '')):
            rm(aid)
            del m[aid]
            save(m)
            return page(GONE.replace('This album is gone', 'Album deleted'), 200)
    abort(403)


@app.route('/healthz')
def health():
    return 'ok'


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
