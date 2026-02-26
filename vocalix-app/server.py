from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from deep_translator import GoogleTranslator
from gradio_client import Client, handle_file
from urllib.parse import quote
import uvicorn, sqlite3, hashlib, jwt, uuid, tempfile, os, shutil, json, base64
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

app = FastAPI(title="Vocalix API")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Config ────────────────────────────────────────────────────────────────────
MOSS_GRADIO_URL = "https://9c50ee0fcdf5f38b28.gradio.live"  # Update this each Kaggle session
SECRET_KEY = "vocalix-secret-key-change-in-production"
VOICE_SAMPLES_DIR = Path("voice_samples")
VOICE_SAMPLES_DIR.mkdir(exist_ok=True)

try:
    moss_client = Client(MOSS_GRADIO_URL)
    print(f"[MOSS-TTS] Connected to {MOSS_GRADIO_URL}")
except Exception as e:
    moss_client = None
    print(f"[MOSS-TTS] Warning: Could not connect: {e}")

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect("vocalix.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            voice_sample_path TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS friendships (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            friend_id TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id),
            FOREIGN KEY (friend_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            sender_id TEXT NOT NULL,
            receiver_id TEXT NOT NULL,
            text TEXT,
            audio_path TEXT,
            message_type TEXT DEFAULT 'text',
            source_lang TEXT DEFAULT 'english',
            target_lang TEXT DEFAULT 'english',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        );
    """)
    conn.commit()
    conn.close()

init_db()

# ── Auth helpers ──────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def create_token(user_id: str) -> str:
    payload = {"user_id": user_id, "exp": datetime.utcnow() + timedelta(days=7)}
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_token(token: str) -> Optional[str]:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        return payload["user_id"]
    except:
        return None

security = HTTPBearer()

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    user_id = verify_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return dict(user)

# ── Transliteration ───────────────────────────────────────────────────────────
def transliterate_malayalam(text):
    ml_map = {
        'അ':'a','ആ':'aa','ഇ':'i','ഈ':'ee','ഉ':'u','ഊ':'oo','എ':'e','ഏ':'ee',
        'ഐ':'ai','ഒ':'o','ഓ':'oo','ഔ':'au','ക':'k','ഖ':'kh','ഗ':'g','ഘ':'gh',
        'ങ':'ng','ച':'ch','ഛ':'chh','ജ':'j','ഝ':'jh','ഞ':'nj','ട':'t','ഠ':'th',
        'ഡ':'d','ഢ':'dh','ണ':'n','ത':'th','ഥ':'th','ദ':'d','ധ':'dh','ന':'n',
        'പ':'p','ഫ':'ph','ബ':'b','ഭ':'bh','മ':'m','യ':'y','ര':'r','ല':'l',
        'വ':'v','ശ':'sh','ഷ':'sh','സ':'s','ഹ':'h','ള':'l','ഴ':'zh','റ':'r',
        'ാ':'aa','ി':'i','ീ':'ee','ു':'u','ൂ':'oo','െ':'e','േ':'e','ൈ':'ai',
        'ൊ':'o','ോ':'o','ൌ':'au','ൗ':'au','്':'','ൃ':'ru','ൺ':'n','ൻ':'n',
        'ർ':'r','ൽ':'l','ൾ':'l','ൿ':'k','ഃ':'h',
    }
    return "".join(ml_map.get(char, char) for char in text)

def transliterate_hindi(text):
    hi_map = {
        'अ':'a','आ':'aa','इ':'i','ई':'ee','उ':'u','ऊ':'oo','ए':'e','ऐ':'ai',
        'ओ':'o','औ':'au','क':'k','ख':'kh','ग':'g','घ':'gh','ङ':'ng','च':'ch',
        'छ':'chh','ज':'j','झ':'jh','ञ':'nj','ट':'t','ठ':'th','ड':'d','ढ':'dh',
        'ण':'n','त':'t','थ':'th','द':'d','ध':'dh','न':'n','प':'p','फ':'ph',
        'ब':'b','भ':'bh','म':'m','य':'y','र':'r','ल':'l','व':'v','श':'sh',
        'ष':'sh','स':'s','ह':'h','ा':'aa','ि':'i','ी':'ee','ु':'u','ू':'oo',
        'े':'e','ै':'ai','ो':'o','ौ':'au','्':'','ं':'n','ः':'h','ऋ':'ri','ळ':'l',
    }
    return "".join(hi_map.get(char, char) for char in text)

def transliterate(text: str, lang: str) -> str:
    if lang == "malayalam": return transliterate_malayalam(text)
    if lang == "hindi": return transliterate_hindi(text)
    return text

def translate_text(text, src, tgt):
    LANG_CODES = {"english": "en", "hindi": "hi", "malayalam": "ml"}
    if src == tgt: return text
    return GoogleTranslator(source=LANG_CODES.get(src, src), target=LANG_CODES.get(tgt, tgt)).translate(text)

def generate_voice(text, voice_sample_path):
    if not moss_client:
        raise Exception("MOSS-TTS not connected. Update MOSS_GRADIO_URL in server.py")
    result = moss_client.predict(
        text=text, reference_audio=handle_file(voice_sample_path),
        mode_with_reference="Clone", duration_control_enabled=False,
        duration_tokens=1, temperature=1.7, top_p=0.8, top_k=25,
        repetition_penalty=1.0, max_new_tokens=4096, api_name="/run_inference",
    )
    return result[0]

# ── Auth Routes ───────────────────────────────────────────────────────────────
@app.post("/auth/signup")
async def signup(
    name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    voice_sample: UploadFile = File(...),
):
    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail="Email already registered")

    user_id = str(uuid.uuid4())
    voice_path = str(VOICE_SAMPLES_DIR / f"{user_id}.wav")
    with open(voice_path, "wb") as f:
        shutil.copyfileobj(voice_sample.file, f)

    conn.execute(
        "INSERT INTO users (id, name, email, password, voice_sample_path) VALUES (?, ?, ?, ?, ?)",
        (user_id, name, email, hash_password(password), voice_path)
    )
    conn.commit()
    conn.close()
    token = create_token(user_id)
    return {"token": token, "user": {"id": user_id, "name": name, "email": email}}

@app.post("/auth/login")
async def login(email: str = Form(...), password: str = Form(...)):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ? AND password = ?",
                        (email, hash_password(password))).fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_token(user["id"])
    return {"token": token, "user": {"id": user["id"], "name": user["name"], "email": user["email"]}}

@app.get("/auth/me")
def me(current_user=Depends(get_current_user)):
    return {"id": current_user["id"], "name": current_user["name"], "email": current_user["email"]}

# ── Friends Routes ────────────────────────────────────────────────────────────
@app.get("/users/search")
def search_users(email: str, current_user=Depends(get_current_user)):
    conn = get_db()
    users = conn.execute(
        "SELECT id, name, email FROM users WHERE email LIKE ? AND id != ?",
        (f"%{email}%", current_user["id"])
    ).fetchall()
    conn.close()
    return [dict(u) for u in users]

@app.post("/friends/add/{friend_id}")
def add_friend(friend_id: str, current_user=Depends(get_current_user)):
    conn = get_db()
    existing = conn.execute(
        "SELECT id FROM friendships WHERE user_id = ? AND friend_id = ?",
        (current_user["id"], friend_id)
    ).fetchone()
    if existing:
        conn.close()
        return {"message": "Already friends"}
    fid = str(uuid.uuid4())
    conn.execute("INSERT INTO friendships (id, user_id, friend_id) VALUES (?, ?, ?)",
                 (fid, current_user["id"], friend_id))
    conn.execute("INSERT INTO friendships (id, user_id, friend_id) VALUES (?, ?, ?)",
                 (str(uuid.uuid4()), friend_id, current_user["id"]))
    conn.commit()
    conn.close()
    return {"message": "Friend added"}

@app.get("/friends")
def get_friends(current_user=Depends(get_current_user)):
    conn = get_db()
    friends = conn.execute("""
        SELECT u.id, u.name, u.email FROM users u
        JOIN friendships f ON f.friend_id = u.id
        WHERE f.user_id = ?
    """, (current_user["id"],)).fetchall()
    conn.close()
    return [dict(f) for f in friends]

# ── Messages Routes ───────────────────────────────────────────────────────────
@app.get("/messages/{friend_id}")
def get_messages(friend_id: str, current_user=Depends(get_current_user)):
    conn = get_db()
    messages = conn.execute("""
        SELECT m.*, u.name as sender_name FROM messages m
        JOIN users u ON u.id = m.sender_id
        WHERE (m.sender_id = ? AND m.receiver_id = ?)
           OR (m.sender_id = ? AND m.receiver_id = ?)
        ORDER BY m.created_at ASC
    """, (current_user["id"], friend_id, friend_id, current_user["id"])).fetchall()
    conn.close()
    result = []
    for m in messages:
        msg = dict(m)
        if msg["audio_path"] and os.path.exists(msg["audio_path"]):
            with open(msg["audio_path"], "rb") as f:
                msg["audio_base64"] = base64.b64encode(f.read()).decode()
        else:
            msg["audio_base64"] = None
        result.append(msg)
    return result

@app.post("/messages/send")
async def send_message(
    receiver_id: str = Form(...),
    text: str = Form(...),
    source_lang: str = Form(default="english"),
    target_lang: str = Form(default="english"),
    clone_voice: str = Form(default="false"),
    current_user=Depends(get_current_user),
):
    msg_id = str(uuid.uuid4())
    audio_path = None
    message_type = "text"

    if clone_voice.lower() == "true":
        try:
            translated = translate_text(text, source_lang, target_lang)
            tts_input = transliterate(translated, target_lang)
            voice_sample = current_user.get("voice_sample_path")
            if not voice_sample or not os.path.exists(voice_sample):
                raise Exception("No voice sample found for this user")
            audio_file = generate_voice(tts_input, voice_sample)
            audio_path = f"audio_messages/{msg_id}.wav"
            os.makedirs("audio_messages", exist_ok=True)
            shutil.copy(audio_file, audio_path)
            message_type = "voice"
        except Exception as e:
            print(f"[Voice Clone Error] {e}")
            message_type = "text"

    conn = get_db()
    conn.execute(
        "INSERT INTO messages (id, sender_id, receiver_id, text, audio_path, message_type, source_lang, target_lang) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (msg_id, current_user["id"], receiver_id, text, audio_path, message_type, source_lang, target_lang)
    )
    conn.commit()
    conn.close()

    msg = {"id": msg_id, "sender_id": current_user["id"], "receiver_id": receiver_id,
           "text": text, "message_type": message_type, "source_lang": source_lang,
           "target_lang": target_lang, "created_at": datetime.utcnow().isoformat(),
           "sender_name": current_user["name"], "audio_base64": None}

    if audio_path and os.path.exists(audio_path):
        with open(audio_path, "rb") as f:
            msg["audio_base64"] = base64.b64encode(f.read()).decode()

    return msg

@app.get("/")
def root():
    return {"message": "Vocalix API running ✅"}

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8000, reload=True)