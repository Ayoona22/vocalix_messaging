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

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],allow_credentials=True)

# ── Config ────────────────────────────────────────────────────────────────────
MOSS_GRADIO_URL = "gradio-link"  # Update this each Kaggle session
SECRET_KEY = "vocalix-secret-key"
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
     'അ':'a','ആ':'aa','ഇ':'i','ഈ':'ee','ഉ':'u','ഊ':'oo','ഋ':'ru',
     'എ':'e','ഏ':'ee','ഐ':'ai','ഒ':'o','ഓ':'oo','ഔ':'au',
     'ഃ':'h','ം':'m','ൺ':'n','ൻ':'n','ർ':'r','ൽ':'l','ൾ':'l','ൿ':'k',
     # conjuncts (longest first for correct replacement)
     'സ്ത്ര':'sthra','സ്ത്രാ':'sthraa','സ്ത്രി':'sthri','സ്ത്രീ':'sthree','സ്ത്രു':'sthru','സ്ത്രൂ':'sthroo','സ്ത്രെ':'sthre','സ്ത്രേ':'sthraee','സ്ത്രൈ':'sthrai','സ്ത്രൊ':'sthro','സ്ത്രോ':'sthro','സ്ത്രൌ':'sthrau','സ്ത്രൗ':'sthrau','സ്ത്രൃ':'sthrya','സ്ത്ര്':'sthru','സ്ത്രം':'sthram',
     'ക്ഷ':'ksha','ക്ഷാ':'kshaa','ക്ഷി':'kshi','ക്ഷീ':'kshee','ക്ഷു':'kshu','ക്ഷൂ':'kshoo','ക്ഷെ':'kshe','ക്ഷേ':'kshaee','ക്ഷൈ':'kshai','ക്ഷൊ':'ksho','ക്ഷോ':'ksho','ക്ഷൗ':'kshau','ക്ഷൃ':'kshya','ക്ഷ്':'kshu','ക്ഷം':'ksham',
     'ണ്ട':'nda','ണ്ടാ':'ndaa','ണ്ടി':'ndi','ണ്ടീ':'ndee','ണ്ടു':'ndu','ണ്ടൂ':'ndoo','ണ്ടെ':'nde','ണ്ടേ':'ndaee','ണ്ടൈ':'ndai','ണ്ടൊ':'ndo','ണ്ടോ':'ndo','ണ്ടൌ':'ndau','ണ്ടൗ':'ndau','ണ്ടൃ':'ndya','ണ്ട്':'ndu','ണ്ടം':'ndam',
     'ണ്ണ':'nna','ണ്ണാ':'nnaa','ണ്ണി':'nni','ണ്ണീ':'nnee','ണ്ണു':'nnu','ണ്ണൂ':'nnoo','ണ്ണെ':'nne','ണ്ണേ':'nnaee','ണ്ണൈ':'nnai','ണ്ണൊ':'nno','ണ്ണോ':'nno','ണ്ണൗ':'nnau','ണ്ണൃ':'nnya','ണ്ണ്':'nnu','ണ്ണം':'nnam',
     'ന്ന':'nna','ന്നാ':'nnaa','ന്നി':'nni','ന്നീ':'nnee','ന്നു':'nnu','ന്നൂ':'nnoo','ന്നെ':'nne','ന്നേ':'nnaee','ന്നൈ':'nnai','ന്നൊ':'nno','ന്നോ':'nno','ന്നൌ':'nnau','ന്നൗ':'nnau','ന്നൃ':'nnya','ന്ന്':'nnu','ന്നം':'nnam',
     'ന്റ':'nta','ന്റാ':'ntaa','ന്റി':'nti','ന്റീ':'ntee','ന്റു':'ntu','ന്റൂ':'ntoo','ന്റെ':'nte','ന്റേ':'ntaee','ന്റൈ':'ntai','ന്റൊ':'nto','ന്റോ':'nto','ന്റൗ':'ntau','ന്റൃ':'ntya','ന്റ്':'ntu','ന്റം':'ntam',
     'മ്മ':'mma','മ്മാ':'mmaa','മ്മി':'mmi','മ്മീ':'mmee','മ്മു':'mmu','മ്മൂ':'mmoo','മ്മെ':'mme','മ്മേ':'mmaee','മ്മൈ':'mmai','മ്മൊ':'mmo','മ്മോ':'mmo','മ്മൌ':'mmau','മ്മൗ':'mmau','മ്മൃ':'mmya','മ്മ്':'mmu','മ്മം':'mmam',
     'മ്പ':'mba','മ്പാ':'mbaa','മ്പി':'mbi','മ്പീ':'mbee','മ്പു':'mbu','മ്പൂ':'mboo','മ്പെ':'mbe','മ്പേ':'mbaee','മ്പൈ':'mbai','മ്പൊ':'mbo','മ്പോ':'mbo','മ്പൌ':'mbau','മ്പൗ':'mbau','മ്പൃ':'mbya','മ്പ്':'mbu','മ്പം':'mbam',
     'ല്ല':'lla','ല്ലാ':'llaa','ല്ലി':'lli','ല്ലീ':'llee','ല്ലു':'llu','ല്ലൂ':'lloo','ല്ലെ':'lle','ല്ലേ':'llaee','ല്ലൈ':'llai','ല്ലൊ':'llo','ല്ലോ':'llo','ല്ലൌ':'llau','ല്ലൗ':'llau','ല്ലൃ':'llya','ല്ല്':'llu','ല്ലം':'llam',
     'ള്ള':'lla','ള്ളാ':'llaa','ള്ളി':'lli','ള്ളീ':'llee','ള്ളു':'llu','ള്ളൂ':'lloo','ള്ളെ':'lle','ള്ളേ':'llaee','ള്ളൈ':'llai','ള്ളൊ':'llo','ള്ളോ':'llo','ള്ളൗ':'llau','ള്ളൃ':'llya','ള്ള്':'llu','ള്ളം':'llam',
     'ഞ്ഞ':'nja','ഞ്ഞാ':'njaa','ഞ്ഞി':'nji','ഞ്ഞീ':'njee','ഞ്ഞു':'nju','ഞ്ഞൂ':'njoo','ഞ്ഞെ':'nje','ഞ്ഞേ':'njee','ഞ്ഞൈ':'njai','ഞ്ഞൊ':'njo','ഞ്ഞോ':'njoo','ഞ്ഞൗ':'njau','ഞ്ഞൃ':'njru','ഞ്ഞ്':'nnnu','ഞ്ഞം':'njam',
     'ഞ്ച':'nja','ഞ്ചാ':'njaa','ഞ്ചി':'nji','ഞ്ചീ':'njee','ഞ്ചു':'nju','ഞ്ചൂ':'njoo','ഞ്ചെ':'nje','ഞ്ചേ':'njee','ഞ്ചൈ':'njai','ഞ്ചൊ':'njo','ഞ്ചോ':'njoo','ഞ്ചൌ':'njau','ഞ്ചൗ':'njau','ഞ്ചൃ':'njru','ഞ്ച്':'nj','ഞ്ചം':'njam',
     'ങ്ക':'nka','ങ്കാ':'nkaa','ങ്കി':'nki','ങ്കീ':'nkee','ങ്കു':'nku','ങ്കൂ':'nkoo','ങ്കെ':'nke','ങ്കേ':'nkee','ങ്കൈ':'nkai','ങ്കൊ':'nko','ങ്കോ':'nkoo','ങ്കൌ':'nkau','ങ്കൗ':'nkau','ങ്കൃ':'nkru','ങ്ക്':'nk','ങ്കം':'nkam',
     'ദ്ദ':'dda','ദ്ദാ':'ddaa','ദ്ദി':'ddi','ദ്ദീ':'ddee','ദ്ദു':'ddu','ദ്ദൂ':'ddoo','ദ്ദെ':'dde','ദ്ദേ':'ddee','ദ്ദൈ':'ddai','ദ്ദൊ':'ddo','ദ്ദോ':'ddoo','ദ്ദൌ':'ddau','ദ്ദൗ':'ddau','ദ്ദൃ':'ddru','ദ്ദ്':'dd','ദ്ദം':'ddam',
     'ദ്ധ':'ddha','ദ്ധാ':'ddhaa','ദ്ധി':'ddhi','ദ്ധീ':'ddhee','ദ്ധു':'ddhu','ദ്ധൂ':'ddhoo','ദ്ധെ':'ddhe','ദ്ധേ':'ddhee','ദ്ധൈ':'ddhai','ദ്ധൊ':'ddho','ദ്ധോ':'ddhoo','ദ്ധൌ':'ddhau','ദ്ധൗ':'ddhau','ദ്ധൃ':'ddhru','ദ്ധ്':'ddh','ദ്ധം':'ddham',
     'ബ്ബ':'bba','ബ്ബാ':'bbaa','ബ്ബി':'bbi','ബ്ബീ':'bbee','ബ്ബു':'bbu','ബ്ബൂ':'bboo','ബ്ബെ':'bbe','ബ്ബേ':'bbee','ബ്ബൈ':'bbai','ബ്ബൊ':'bbo','ബ്ബോ':'bboo','ബ്ബൌ':'bbau','ബ്ബൗ':'bbau','ബ്ബൃ':'bbru','ബ്ബ്':'bb','ബ്ബം':'bbam',
     'ട്ട':'tta','ട്ടാ':'ttaa','ട്ടി':'tti','ട്ടീ':'ttee','ട്ടു':'ttu','ട്ടൂ':'ttoo','ട്ടെ':'tte','ട്ടേ':'ttee','ട്ടൈ':'ttai','ട്ടൊ':'tto','ട്ടോ':'ttoo','ട്ടൌ':'ttau','ട്ടൗ':'ttau','ട്ടൃ':'ttru','ട്ട്':'tt','ട്ടം':'ttam',
     'ത്ത':'ttha','ത്താ':'tthaa','ത്തി':'tthi','ത്തീ':'tthee','ത്തു':'tthu','ത്തൂ':'tthoo','ത്തെ':'tthe','ത്തേ':'tthee','ത്തൈ':'tthai','ത്തൊ':'ttho','ത്തോ':'tthoo','ത്തൌ':'tthau','ത്തൗ':'tthau','ത്തൃ':'tthru','ത്ത്':'tth','ത്തം':'ttham',
     'ത്ര':'tra','ത്രാ':'traa','ത്രി':'tri','ത്രീ':'tree','ത്രു':'tru','ത്രൂ':'troo','ത്രെ':'tre','ത്രേ':'tree','ത്രൈ':'trai','ത്രൊ':'tro','ത്രോ':'troo','ത്രൌ':'trau','ത്രൗ':'trau','ത്രൃ':'trru','ത്ര്':'tr','ത്രം':'tram',
     'ക്ക':'kka','ക്കാ':'kkaa','ക്കി':'kki','ക്കീ':'kkee','ക്കു':'kku','ക്കൂ':'kkoo','ക്കെ':'kke','ക്കേ':'kkee','ക്കൈ':'kkai','ക്കൊ':'kko','ക്കോ':'kkoo','ക്കൌ':'kkau','ക്കൗ':'kkau','ക്കൃ':'kkru','ക്ക്':'kk','ക്കം':'kkam',
     'ക്ത':'kta','ക്താ':'ktaa','ക്തി':'kti','ക്തീ':'ktee','ക്തു':'ktu','ക്തൂ':'ktoo','ക്തെ':'kte','ക്തേ':'ktee','ക്തൈ':'ktai','ക്തൊ':'kto','ക്തോ':'ktoo','ക്തൌ':'ktau','ക്തൗ':'ktau','ക്തൃ':'ktru','ക്ത്':'kt','ക്തം':'ktam',
     'ഗ്ര':'gra','ഗ്രാ':'graa','ഗ്രി':'gri','ഗ്രീ':'gree','ഗ്രു':'gru','ഗ്രൂ':'groo','ഗ്രെ':'gre','ഗ്രേ':'gree','ഗ്രൈ':'grai','ഗ്രൊ':'gro','ഗ്രോ':'groo','ഗ്രൌ':'grau','ഗ്രൗ':'grau','ഗ്രൃ':'grru','ഗ്ര്':'gr','ഗ്രം':'gram',
     'പ്പ':'ppa','പ്പാ':'ppaa','പ്പി':'ppi','പ്പീ':'ppee','പ്പു':'ppu','പ്പൂ':'ppoo','പ്പെ':'ppe','പ്പേ':'ppee','പ്പൈ':'ppai','പ്പൊ':'ppo','പ്പോ':'ppoo','പ്പൌ':'ppau','പ്പൗ':'ppau','പ്പൃ':'ppru','പ്പ്':'pp','പ്പം':'ppam',
     'ച്ച':'cha','ച്ചാ':'chaa','ച്ചി':'chi','ച്ചീ':'chee','ച്ചു':'chu','ച്ചൂ':'choo','ച്ചെ':'che','ച്ചേ':'chee','ച്ചൈ':'chai','ച്ചൊ':'cho','ച്ചോ':'choo','ച്ചൗ':'chau','ച്ചൃ':'chru','ച്ച്':'ch','ച്ചം':'cham',
     'യ്യ':'yya','യ്യാ':'yyaa','യ്യി':'yyi','യ്യീ':'yyee','യ്യു':'yyu','യ്യൂ':'yyoo','യ്യെ':'yye','യ്യേ':'yyee','യ്യൈ':'yyai','യ്യൊ':'yyo','യ്യോ':'yyoo','യ്യൌ':'yyau','യ്യൗ':'yyau','യ്യൃ':'yyru','യ്യ്':'yy',
     # single consonants + vowel signs
     'ക':'ka','കാ':'kaa','കി':'ki','കീ':'kee','കു':'ku','കൂ':'koo','കെ':'ke','കേ':'kee','കൈ':'kai','കൊ':'ko','കോ':'koo','കൌ':'kau','കൗ':'kau','കൃ':'kru','ക്':'k',
     'ഖ':'kha','ഖാ':'khaa','ഖി':'khi','ഖീ':'khee','ഖു':'khu','ഖൂ':'khoo','ഖെ':'khe','ഖേ':'khee','ഖൈ':'khai','ഖൊ':'kho','ഖോ':'khoo','ഖൌ':'khau','ഖൗ':'khau','ഖൃ':'khru','ഖ്':'kh',
     'ഗ':'ga','ഗാ':'gaa','ഗി':'gi','ഗീ':'gee','ഗു':'gu','ഗൂ':'goo','ഗെ':'ge','ഗേ':'gee','ഗൈ':'gai','ഗൊ':'go','ഗോ':'goo','ഗൌ':'gau','ഗൗ':'gau','ഗൃ':'gru','ഗ്':'g',
     'ഘ':'gha','ഘാ':'ghaa','ഘി':'ghi','ഘീ':'ghee','ഘു':'ghu','ഘൂ':'ghoo','ഘെ':'ghe','ഘേ':'ghee','ഘൈ':'ghai','ഘൊ':'gho','ഘോ':'ghoo','ഘൌ':'ghau','ഘൗ':'ghau','ഘൃ':'ghru','ഘ്':'gh',
     'ങ':'nga','ങാ':'ngaa','ങി':'ngi','ങീ':'ngee','ങു':'ngu','ങൂ':'ngoo','ങെ':'nge','ങേ':'ngee','ങൈ':'ngai','ങൊ':'ngo','ങോ':'ngoo','ങൌ':'ngau','ങൗ':'ngau','ങൃ':'ngru','ങ്':'ng',
     'ച':'cha','ചാ':'chaa','ചി':'chi','ചീ':'chee','ചു':'chu','ചൂ':'choo','ചെ':'che','ചേ':'chee','ചൈ':'chai','ചൊ':'cho','ചോ':'choo','ചൌ':'chau','ചൗ':'chau','ചൃ':'chru','ച്':'ch',
     'ഛ':'chha','ഛാ':'chhaa','ഛി':'chhi','ഛീ':'chhee','ഛു':'chhu','ഛൂ':'chhoo','ഛെ':'chhe','ഛേ':'chhee','ഛൈ':'chhai','ഛൊ':'chho','ഛോ':'chhoo','ഛൌ':'chhau','ഛൗ':'chhau','ഛൃ':'chhru','ഛ്':'chh',
     'ജ':'ja','ജാ':'jaa','ജി':'ji','ജീ':'jee','ജു':'ju','ജൂ':'joo','ജെ':'je','ജേ':'jee','ജൈ':'jai','ജൊ':'jo','ജോ':'joo','ജൌ':'jau','ജൗ':'jau','ജൃ':'jru','ജ്':'j',
     'ഝ':'jha','ഝാ':'jhaa','ഝി':'jhi','ഝീ':'jhee','ഝു':'jhu','ഝൂ':'jhoo','ഝെ':'jhe','ഝേ':'jhee','ഝൈ':'jhai','ഝൊ':'jho','ഝോ':'jhoo','ഝൌ':'jhau','ഝൗ':'jhau','ഝൃ':'jhru','ഝ്':'jh',
     'ഞ':'nja','ഞാ':'njaa','ഞി':'nji','ഞീ':'njee','ഞു':'nju','ഞൂ':'njoo','ഞെ':'nje','ഞേ':'njee','ഞൈ':'njai','ഞൊ':'njo','ഞോ':'njoo','ഞൌ':'njau','ഞൗ':'njau','ഞൃ':'njru','ഞ്':'nj',
     'ട':'ta','ടാ':'taa','ടി':'ti','ടീ':'tee','ടു':'tu','ടൂ':'too','ടെ':'te','ടേ':'tee','ടൈ':'tai','ടൊ':'to','ടോ':'too','ടൌ':'tau','ടൗ':'tau','ടൃ':'tru','ട്':'t',
     'ഠ':'tha','ഠാ':'thaa','ഠി':'thi','ഠീ':'thee','ഠു':'thu','ഠൂ':'thoo','ഠെ':'the','ഠേ':'thee','ഠൈ':'thai','ഠൊ':'tho','ഠോ':'thoo','ഠൌ':'thau','ഠൗ':'thau','ഠൃ':'thru','ഠ്':'th',
     'ഡ':'da','ഡാ':'daa','ഡി':'di','ഡീ':'dee','ഡു':'du','ഡൂ':'doo','ഡെ':'de','ഡേ':'dee','ഡൈ':'dai','ഡൊ':'do','ഡോ':'doo','ഡൌ':'dau','ഡൗ':'dau','ഡൃ':'dru','ഡ്':'d',
     'ഢ':'dha','ഢാ':'dhaa','ഢി':'dhi','ഢീ':'dhee','ഢു':'dhu','ഢൂ':'dhoo','ഢെ':'dhe','ഢേ':'dhee','ഢൈ':'dhai','ഢൊ':'dho','ഢോ':'dhoo','ഢൌ':'dhau','ഢൗ':'dhau','ഢൃ':'dhru','ഢ്':'dh',
     'ണ':'na','ണാ':'naa','ണി':'ni','ണീ':'nee','ണു':'nu','ണൂ':'noo','ണെ':'ne','ണേ':'nee','ണൈ':'nai','ണൊ':'no','ണോ':'noo','ണൌ':'nau','ണൗ':'nau','ണൃ':'nru','ണ്':'n',
     'ത':'tha','താ':'thaa','തി':'thi','തീ':'thee','തു':'thu','തൂ':'thoo','തെ':'the','തേ':'thee','തൈ':'thai','തൊ':'tho','തോ':'thoo','തൌ':'thau','തൗ':'thau','തൃ':'thru','ത്':'t',
     'ഥ':'tha','ഥാ':'thaa','ഥി':'thi','ഥീ':'thee','ഥു':'thu','ഥൂ':'thoo','ഥെ':'the','ഥേ':'thee','ഥൈ':'thai','ഥൊ':'tho','ഥോ':'thoo','ഥൌ':'thau','ഥൗ':'thau','ഥൃ':'thru','ഥ്':'th',
     'ദ':'da','ദാ':'daa','ദി':'di','ദീ':'dee','ദു':'du','ദൂ':'doo','ദെ':'de','ദേ':'dee','ദൈ':'dai','ദൊ':'do','ദോ':'doo','ദൌ':'dau','ദൗ':'dau','ദൃ':'dru','ദ്':'d',
     'ധ':'dha','ധാ':'dhaa','ധി':'dhi','ധീ':'dhee','ധു':'dhu','ധൂ':'dhoo','ധെ':'dhe','ധേ':'dhee','ധൈ':'dhai','ധൊ':'dho','ധോ':'dhoo','ധൌ':'dhau','ധൗ':'dhau','ധൃ':'dhru','ധ്':'dh',
     'ന':'na','നാ':'naa','നി':'ni','നീ':'nee','നു':'nu','നൂ':'noo','നെ':'ne','നേ':'nee','നൈ':'nai','നൊ':'no','നോ':'noo','നൌ':'nau','നൗ':'nau','നൃ':'nru','ന്':'n',
     'പ':'pa','പാ':'paa','പി':'pi','പീ':'pee','പു':'pu','പൂ':'poo','പെ':'pe','പേ':'pee','പൈ':'pai','പൊ':'po','പോ':'poo','പൌ':'pau','പൗ':'pau','പൃ':'pru','പ്':'p',
     'ഫ':'pha','ഫാ':'phaa','ഫി':'phi','ഫീ':'phee','ഫു':'phu','ഫൂ':'phoo','ഫെ':'phe','ഫേ':'phee','ഫൈ':'phai','ഫൊ':'pho','ഫോ':'phoo','ഫൌ':'phau','ഫൗ':'phau','ഫൃ':'phru','ഫ്':'ph',
     'ബ':'ba','ബാ':'baa','ബി':'bi','ബീ':'bee','ബു':'bu','ബൂ':'boo','ബെ':'be','ബേ':'bee','ബൈ':'bai','ബൊ':'bo','ബോ':'boo','ബൌ':'bau','ബൗ':'bau','ബൃ':'bru','ബ്':'b',
     'ഭ':'bha','ഭാ':'bhaa','ഭി':'bhi','ഭീ':'bhee','ഭു':'bhu','ഭൂ':'bhoo','ഭെ':'bhe','ഭേ':'bhee','ഭൈ':'bhai','ഭൊ':'bho','ഭോ':'bhoo','ഭൌ':'bhau','ഭൗ':'bhau','ഭൃ':'bhru','ഭ്':'bh',
     'മ':'ma','മാ':'maa','മി':'mi','മീ':'mee','മു':'mu','മൂ':'moo','മെ':'me','മേ':'mee','മൈ':'mai','മൊ':'mo','മോ':'moo','മൌ':'mau','മൗ':'mau','മൃ':'mru','മ്':'m',
     'യ':'ya','യാ':'yaa','യി':'yi','യീ':'yee','യു':'yu','യൂ':'yoo','യെ':'ye','യേ':'yee','യൈ':'yai','യൊ':'yo','യോ':'yoo','യൌ':'yau','യൗ':'yau','യൃ':'yru','യ്':'y',
     'ര':'ra','രാ':'raa','രി':'ri','രീ':'ree','രു':'ru','രൂ':'roo','രെ':'re','രേ':'ree','രൈ':'rai','രൊ':'ro','രോ':'roo','രൌ':'rau','രൗ':'rau','രൃ':'rru','ര്':'r',
     'ല':'la','ലാ':'laa','ലി':'li','ലീ':'lee','ലു':'lu','ലൂ':'loo','ലെ':'le','ലേ':'lee','ലൈ':'lai','ലൊ':'lo','ലോ':'loo','ലൌ':'lau','ലൗ':'lau','ലൃ':'lru','ല്':'l',
     'വ':'va','വാ':'vaa','വി':'vi','വീ':'vee','വു':'vu','വൂ':'voo','വെ':'ve','വേ':'vee','വൈ':'vai','വൊ':'vo','വോ':'voo','വൌ':'vau','വൗ':'vau','വൃ':'vru','വ്':'v',
     'ശ':'sha','ശാ':'shaa','ശി':'shi','ശീ':'shee','ശു':'shu','ശൂ':'shoo','ശെ':'she','ശേ':'shee','ശൈ':'shai','ശൊ':'sho','ശോ':'shoo','ശൌ':'shau','ശൗ':'shau','ശൃ':'shru','ശ്':'sh',
     'ഷ':'sha','ഷാ':'shaa','ഷി':'shi','ഷീ':'shee','ഷു':'shu','ഷൂ':'shoo','ഷേ':'shee','ഷൈ':'shai','ഷൊ':'sho','ഷോ':'shoo','ഷൌ':'shau','ഷൗ':'shau','ഷൃ':'shru','ഷ്':'sh',
     'സ':'sa','സാ':'saa','സി':'si','സീ':'see','സു':'su','സൂ':'soo','സെ':'se','സേ':'see','സൈ':'sai','സൊ':'so','സോ':'soo','സൌ':'sau','സൗ':'sau','സൃ':'sru','സ്':'s',
     'ഹ':'ha','ഹാ':'haa','ഹി':'hi','ഹീ':'hee','ഹു':'hu','ഹൂ':'hoo','ഹെ':'he','ഹേ':'hee','ഹൈ':'hai','ഹൊ':'ho','ഹോ':'hoo','ഹൌ':'hau','ഹൗ':'hau','ഹൃ':'hru','ഹ്':'h',
     'ള':'la','ളാ':'laa','ളി':'li','ളീ':'lee','ളു':'lu','ളൂ':'loo','ളെ':'le','ളേ':'lee','ളൈ':'lai','ളൊ':'lo','ളോ':'loo','ളൌ':'lau','ളൗ':'lau','ളൃ':'lru','ള്':'l',
     'ഴ':'zha','ഴാ':'zhaa','ഴി':'zhi','ഴീ':'zhee','ഴു':'zhu','ഴൂ':'zhoo','ഴെ':'zhe','ഴേ':'zhee','ഴൈ':'zhai','ഴൊ':'zho','ഴോ':'zhoo','ഴൌ':'zhau','ഴൗ':'zhau','ഴൃ':'zhru','ഴ്':'zh',
     'റ':'ra','റാ':'raa','റി':'ri','റീ':'ree','റു':'ru','റൂ':'roo','റെ':'re','റേ':'ree','റൈ':'rai','റൊ':'ro','റോ':'roo','റൌ':'rau','റൗ':'rau','റൃ':'rru','റ്':'r',
    }
    result = text
    for k in sorted(ml_map, key=len, reverse=True):
        result = result.replace(k, ml_map[k])
    print(result)
    return result


def transliterate_hindi(text):
    hi_map = {
     'अ':'a','आ':'aa','इ':'i','ई':'ee','उ':'u','ऊ':'oo','ऋ':'ru',
     'ए':'e','ऐ':'ai','ओ':'o','औ':'au','ं':'n','ः':'h','ँ':'n',
     'क':'ka','का':'kaa','कि':'ki','की':'kee','कु':'ku','कू':'koo','के':'ke','कै':'kai','को':'ko','कौ':'kau','कृ':'kru','कॅ':'ke','कॆ':'ke','कॉ':'ko','क्':'k',
     'ख':'kha','खा':'khaa','खि':'khi','खी':'khee','खु':'khu','खू':'khoo','खे':'khe','खै':'khai','खो':'kho','खौ':'khau','खृ':'khru','खॅ':'khe','खॆ':'khe','खॉ':'kho','ख्':'kh',
     'ग':'ga','गा':'gaa','गि':'gi','गी':'gee','गु':'gu','गू':'goo','गे':'ge','गै':'gai','गो':'go','गौ':'gau','गृ':'gru','गॅ':'ge','गॆ':'ge','गॉ':'go','ग्':'g',
     'घ':'gha','घा':'ghaa','घि':'ghi','घी':'ghee','घु':'ghu','घू':'ghoo','घे':'ghe','घै':'ghai','घो':'gho','घौ':'ghau','घृ':'ghru','घॅ':'ghe','घॆ':'ghe','घॉ':'gho','घ्':'gh',
     'ङ':'nga','ङा':'ngaa','ङि':'ngi','ङी':'ngee','ङे':'nge','ङै':'ngai','ङो':'ngo','ङौ':'ngau','ङृ':'ngru','ङ्':'ng',
     'च':'cha','चा':'chaa','चि':'chi','ची':'chee','चु':'chu','चू':'choo','चे':'che','चै':'chai','चो':'cho','चौ':'chau','चृ':'chru','चॅ':'che','चॆ':'che','चॉ':'cho','च्':'ch',
     'छ':'chha','छा':'chhaa','छि':'chhi','छी':'chhee','छु':'chhu','छू':'chhoo','छे':'chhe','छै':'chhai','छो':'chho','छौ':'chhau','छृ':'chhru','छॅ':'chhe','छॆ':'chhe','छॉ':'chho','छ्':'chh',
     'ज':'ja','जा':'jaa','जि':'ji','जी':'jee','जु':'ju','जू':'joo','जे':'je','जै':'jai','जो':'jo','जौ':'jau','जृ':'jru','जॅ':'je','जॆ':'je','जॉ':'jo','ज्':'j',
     'झ':'jha','झा':'jhaa','झि':'jhi','झी':'jhee','झू':'jhoo','झे':'jhe','झै':'jhai','झो':'jho','झौ':'jhau','झृ':'jhru','झॅ':'jhe','झॆ':'jhe','झॉ':'jho','झ्':'jh',
     'ञ':'nja','ञा':'njaa','ञि':'nji','ञी':'njee','ञू':'njoo','ञे':'nje','ञै':'njai','ञो':'njo','ञौ':'njau','ञृ':'njru','ञॅ':'nje','ञॆ':'nje','ञॉ':'njo','ञ्':'nj',
     'ट':'ta','टा':'taa','टि':'ti','टी':'tee','टु':'tu','टू':'too','टे':'te','टै':'tai','टो':'to','टौ':'tau','टृ':'tru','टॅ':'te','टॆ':'te','टॉ':'to','ट्':'t',
     'ठ':'tha','ठा':'thaa','ठि':'thi','ठी':'thee','ठु':'thu','ठू':'thoo','ठे':'the','ठै':'thai','ठो':'tho','ठौ':'thau','ठृ':'thru','ठॅ':'the','ठॆ':'the','ठॉ':'tho','ठ्':'th',
     'ड':'da','डा':'daa','डि':'di','डी':'dee','डु':'du','डू':'doo','डे':'de','डै':'dai','डो':'do','डौ':'dau','डृ':'dru','डॅ':'de','डॆ':'de','डॉ':'do','ड्':'d',
     'ढ':'dha','ढा':'dhaa','ढि':'dhi','ढी':'dhee','ढु':'dhu','ढू':'dhoo','ढे':'dhe','ढै':'dhai','ढो':'dho','ढौ':'dhau','ढृ':'dhru','ढॅ':'dhe','ढॆ':'dhe','ढॉ':'dho','ढ्':'dh',
     'ण':'na','णा':'naa','णि':'ni','णी':'nee','णु':'nu','णू':'noo','णे':'ne','णै':'nai','णो':'no','णौ':'nau','णृ':'nru','णॅ':'ne','णॆ':'ne','णॉ':'no','ण्':'n',
     'त':'ta','ता':'taa','ति':'ti','ती':'tee','तु':'tu','तू':'too','ते':'te','तै':'tai','तो':'to','तौ':'tau','तृ':'tru','तॅ':'te','तॆ':'te','तॉ':'to','त्':'t',
     'थ':'tha','था':'thaa','थि':'thi','थी':'thee','थु':'thu','थू':'thoo','थे':'the','थै':'thai','थो':'tho','थौ':'thau','थृ':'thru','थॅ':'the','थॆ':'the','थॉ':'tho','थ्':'th',
     'द':'da','दा':'daa','दि':'di','दी':'dee','दु':'du','दू':'doo','दे':'de','दै':'dai','दो':'do','दौ':'dau','दृ':'dru','दॅ':'de','दॆ':'de','दॉ':'do','द्':'d',
     'ध':'dha','धा':'dhaa','धि':'dhi','धी':'dhee','धू':'dhoo','धे':'dhe','धै':'dhai','धो':'dho','धौ':'dhau','धृ':'dhru','धॅ':'dhe','धॆ':'dhe','धॉ':'dho','ध्':'dh',
     'न':'na','ना':'naa','नि':'ni','नी':'nee','नु':'nu','नू':'noo','ने':'ne','नै':'nai','नो':'no','नौ':'nau','नृ':'nru','नॅ':'ne','नॆ':'ne','नॉ':'no','न्':'n',
     'प':'pa','पा':'paa','पि':'pi','पी':'pee','पु':'pu','पू':'poo','पे':'pe','पै':'pai','पो':'po','पौ':'pau','पृ':'pru','पॅ':'pe','पॆ':'pe','पॉ':'po','प्':'p',
     'फ':'pha','फा':'phaa','फि':'phi','फी':'phee','फु':'phu','फू':'phoo','फे':'phe','फै':'phai','फो':'pho','फौ':'phau','फृ':'phru','फॅ':'phe','फॆ':'phe','फॉ':'pho','फ्':'ph',
     'ब':'ba','बा':'baa','बि':'bi','बी':'bee','बु':'bu','बू':'boo','बे':'be','बै':'bai','बो':'bo','बौ':'bau','बृ':'bru','बॅ':'be','बॆ':'be','बॉ':'bo','ब्':'b',
     'भ':'bha','भा':'bhaa','भि':'bhi','भी':'bhee','भु':'bhu','भू':'bhoo','भे':'bhe','भै':'bhai','भो':'bho','भौ':'bhau','भृ':'bhru','भॅ':'bhe','भॆ':'bhe','भॉ':'bho','भ्':'bh',
     'म':'ma','मा':'maa','मि':'mi','मी':'mee','मु':'mu','मू':'moo','मे':'me','मै':'mai','मो':'mo','मौ':'mau','मृ':'mru','मॅ':'me','मॆ':'me','मॉ':'mo','म्':'m',
     'य':'ya','या':'yaa','यि':'yi','यी':'yee','यु':'yu','यू':'yoo','ये':'ye','यै':'yai','यो':'yo','यौ':'yau','यृ':'yru','यॅ':'ye','यॆ':'ye','यॉ':'yo','य्':'y',
     'र':'ra','रा':'raa','रि':'ri','री':'ree','रु':'ru','रू':'roo','रे':'re','रै':'rai','रो':'ro','रौ':'rau','रृ':'rru','रॅ':'re','रॆ':'re','रॉ':'ro','र्':'r',
     'ल':'la','ला':'laa','लि':'li','ली':'lee','लु':'lu','लू':'loo','ले':'le','लै':'lai','लो':'lo','लौ':'lau','लृ':'lru','लॅ':'le','लॆ':'le','लॉ':'lo','ल्':'l',
     'व':'va','वा':'vaa','वि':'vi','वी':'vee','वु':'vu','वू':'voo','वे':'ve','वै':'vai','वो':'vo','वौ':'vau','वृ':'vru','वॅ':'ve','वॆ':'ve','वॉ':'vo','व्':'v',
     'श':'sha','शा':'shaa','शि':'shi','शी':'shee','शु':'shu','शू':'shoo','शे':'she','शै':'shai','शो':'sho','शौ':'shau','शृ':'shru','शॅ':'she','शॆ':'she','शॉ':'sho','श्':'sh',
     'ष':'sha','षा':'shaa','षि':'shi','षी':'shee','षु':'shu','षू':'shoo','षे':'she','षै':'shai','षो':'sho','षौ':'shau','षृ':'shru','षॅ':'she','षॆ':'she','षॉ':'sho','ष्':'sh',
     'स':'sa','सा':'saa','सि':'si','सी':'see','सु':'su','सू':'soo','से':'se','सै':'sai','सो':'so','सौ':'sau','सृ':'sru','सॅ':'se','सॆ':'se','सॉ':'so','स्':'s',
     'ह':'ha','हा':'haa','हि':'hi','ही':'hee','हु':'hu','हू':'hoo','हे':'he','है':'hai','हो':'ho','हौ':'hau','हृ':'hru','हॅ':'he','हॆ':'he','हॉ':'ho','ह्':'h',
     'ळ':'la','ळा':'laa','ळि':'li','ळी':'lee','ळु':'lu','ळू':'loo','ळे':'le','ळै':'lai','ळो':'lo','ळौ':'lau','ळृ':'lru','ळॅ':'le','ळॆ':'le','ळॉ':'lo','ळ्':'l',
    }
    result = text
    for k in sorted(hi_map, key=len, reverse=True):
        result = result.replace(k, hi_map[k])
    return result


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
            if target_lang == "english":
                tts_input = translated
            else:
                tts_input = transliterate(translated, target_lang)
            print(f"[TTS Input] lang={target_lang} | text={tts_input}")
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
