# brainbuddy_app.py
import os
import json
import time
import hashlib
from datetime import datetime
from textwrap import dedent

import requests
import streamlit as st


# Try to import Stripe safely so app never crashes if package isn't installed
try:
    import stripe
    STRIPE_AVAILABLE = True
except Exception:
    stripe = None
    STRIPE_AVAILABLE = False

# =========================
# Config / Environment
# =========================
APP_DIR = os.path.dirname(__file__)

# Freemium usage limits
USAGE_PATH = os.path.join(APP_DIR, ".usage.json")  # local usage db (MVP)
FREE_DAILY_LIMIT = int(os.getenv("FREE_DAILY_LIMIT", "5"))

# Local (free) model via Ollama (builder/dev mode)
USE_OLLAMA = os.getenv("USE_OLLAMA", "0") == "1"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:latest")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# Optional cloud model (OpenAI or any OpenAI-compatible provider)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # only if you use a compatible host

# Stripe (Premium)
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
if STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# =========================
# Streamlit UI setup
# =========================
st.set_page_config(page_title="🧠 BrainBuddy", page_icon="🧠", layout="centered")
st.title("🧠 BrainBuddy — Study Copilot")
st.caption("Free tier with daily limits. Upgrade unlocks unlimited answers + upcoming study tools.")

# =========================
# Auth (simple nickname sign-in stored in session)
# =========================
def uhash(name: str) -> str:
    return hashlib.sha256(name.strip().lower().encode("utf-8")).hexdigest()[:16]

if "user" not in st.session_state:
    st.session_state.user = None

if st.session_state.user is None:
    st.subheader("Sign in (no email needed)")
    username = st.text_input("Pick a nickname:", placeholder="e.g., mattj")
    if st.button("Sign in"):
        if username.strip():
            st.session_state.user = {"name": username.strip(), "id": uhash(username)}
            st.success(f"Signed in as {username.strip()}")
            st.rerun()
    st.stop()

USER = st.session_state.user

# =========================
# Usage tracking (local JSON)
# =========================
def load_usage() -> dict:
    if os.path.exists(USAGE_PATH):
        try:
            with open(USAGE_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_usage(db: dict):
    with open(USAGE_PATH, "w") as f:
        json.dump(db, f, indent=2)

def today_key() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def get_count(db: dict, uid: str, day: str) -> int:
    return db.get(uid, {}).get(day, 0)

def inc_count(db: dict, uid: str, day: str) -> int:
    db.setdefault(uid, {})
    db[uid][day] = db[uid].get(day, 0) + 1
    save_usage(db)
    return db[uid][day]

db = load_usage()
today = today_key()
used_today = get_count(db, USER["id"], today)
remaining = max(0, FREE_DAILY_LIMIT - used_today)

# Sidebar info
st.sidebar.subheader("Account")
st.sidebar.write(f"User: **{USER['name']}**")
st.sidebar.metric("Free answers left today", remaining)
st.sidebar.caption(f"Daily reset at midnight • Limit: {FREE_DAILY_LIMIT}")

# =========================
# Answer engines
# =========================
def local_template_answer(question: str, points: int, tone: str) -> str:
    if not question.strip():
        return "Type something first 🙂"
    intro = f"Here’s a {tone} explanation of **{question.strip()}**:"
    bullets = [f"{i}. Key idea {i}: explain plainly with a short example." for i in range(1, points + 1)]
    steps = [
        "1) Restate the question in your own words.",
        "2) Identify key terms and define them simply.",
        "3) Connect terms (cause/effect, compare/contrast).",
        "4) Give a short example or analogy.",
        "5) Summarize in 2–3 sentences.",
    ]
    study = [
        "- Make 5 flashcards: term → definition.",
        "- Write a 3-sentence summary from memory.",
        "- Do a 2-minute ‘teach-back’ out loud.",
    ]
    return dedent(f"""
    {intro}

    **Main points to know:**
    - """ + "\n    - ".join(bullets) + """

    **How to solve / study this quickly:**
    """ + "\n".join(steps) + """

    **Mini study plan (5–10 minutes):**
    """ + "\n".join(study) + """
    """)

def answer_with_ollama(question: str, tone: str):
    """Calls local Ollama chat API (free local model)."""
    try:
        url = f"{OLLAMA_URL}/api/chat"
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": "You are a friendly, accurate teen study tutor. Be concise and clear."},
                {"role": "user", "content": f"Tone: {tone}. Explain this topic step-by-step with examples:\n\n{question}"},
            ],
            "stream": False,
        }
        r = requests.post(url, json=payload, timeout=120)
        r.raise_for_status()
        data = r.json()
        return data.get("message", {}).get("content", ""), None
    except Exception as e:
        return None, f"Ollama error: {e}"

def answer_with_openai(question: str, tone: str):
    """Uses OpenAI (or compatible) only if API key is set. Otherwise returns (None, reason)."""
    if not OPENAI_API_KEY:
        return None, "No OpenAI API key set."
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL) if OPENAI_BASE_URL else OpenAI(api_key=OPENAI_API_KEY)
        msg = [
            {"role": "system", "content": "You are a friendly, accurate teen study tutor. Be concise and clear."},
            {"role": "user", "content": f"Tone: {tone}. Explain this topic step-by-step with examples:\n\n{question}"},
        ]
        resp = client.chat.completions.create(model=OPENAI_MODEL, messages=msg, temperature=0.4)
        return resp.choices[0].message.content, None
    except Exception as e:
        return None, f"OpenAI error: {e}"

def get_answer(question: str, points: int, tone: str) -> str:
    # Priority: local free model → cloud model → template fallback
    if USE_OLLAMA:
        content, err = answer_with_ollama(question, tone)
        if content:
            return content
        if err:
            st.info(err)
    content, err = answer_with_openai(question, tone)
    if content:
        return content
    if err:
        st.info(err)
    return local_template_answer(question, points, tone)

# =========================
# Main UI
# =========================
st.markdown("**Ask your homework question.** Free plan has daily limits.")
q = st.text_area("Your question / topic", height=120, placeholder="e.g., Explain photosynthesis in simple terms")

col1, col2 = st.columns(2)
with col1:
    max_points = st.slider("Detail level", 3, 8, 5)
with col2:
    tone = st.selectbox("Tone", ["simple", "normal", "exam-ready"])

# Paywall gate for free tier
if remaining <= 0:
    st.warning("You’ve reached your free limit for today. Come back tomorrow or upgrade to Premium.")
else:
    if st.button("Explain"):
        if not q.strip():
            st.warning("Type a question first.")
        else:
            inc_count(db, USER["id"], today)  # consume one credit
            st.caption(f"Free answers left after this: {max(0, remaining-1)}")
            st.markdown(get_answer(q, max_points, tone))

# =========================
# Premium (Stripe Checkout)
# =========================
# tiny local "pro users" db (MVP)
PRO_PATH = os.path.join(APP_DIR, ".pro.json")
def load_pro():
    if os.path.exists(PRO_PATH):
        try:
            with open(PRO_PATH, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_pro(d):
    with open(PRO_PATH, "w") as f:
        json.dump(d, f, indent=2)

pro_db = load_pro()
is_pro = USER["id"] in pro_db

# handle Stripe return (if configured)
session_id = st.query_params.get("session_id", [None])[0] if hasattr(st, "query_params") else None
if session_id and STRIPE_AVAILABLE and STRIPE_SECRET_KEY:
    try:
        s = stripe.checkout.Session.retrieve(session_id)
        # Treat paid/complete/subscription as success
        if (s.get("payment_status") == "paid") or (s.get("status") in ("complete",)) or (s.get("mode") == "subscription" and s.get("subscription")):
            pro_db[USER["id"]] = {"ts": time.time(), "session": session_id}
            save_pro(pro_db)
            is_pro = True
            st.success("✅ Premium unlocked!")
    except Exception as e:
        st.info(f"Stripe check error: {e}")

# Lift limits for pro users
if is_pro:
    FREE_DAILY_LIMIT = 10**9
    remaining = 999999

st.markdown("---")
st.subheader("Upgrade to Premium")

if is_pro:
    st.success("You're on **Premium** — unlimited answers unlocked.")
else:
    # Only show the button if Stripe and required env vars are present
    if not (STRIPE_AVAILABLE and STRIPE_SECRET_KEY and STRIPE_PRICE_ID and PUBLIC_BASE_URL):
        st.info("Upgrade unavailable: missing Stripe config or 'stripe' package. Ensure STRIPE_SECRET_KEY, STRIPE_PRICE_ID, PUBLIC_BASE_URL are set on the server and 'stripe' is listed in requirements.txt.")
    else:
        success = f"{PUBLIC_BASE_URL}?status=success&session_id={{CHECKOUT_SESSION_ID}}"
        cancel = f"{PUBLIC_BASE_URL}?status=cancel"
        if st.button("Upgrade — $5/month via Stripe"):
            try:
                session = stripe.checkout.Session.create(
                    mode="subscription",
                    line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
                    success_url=success,
                    cancel_url=cancel,
                    ui_mode="hosted",
                )
                st.markdown(f"[Click to continue to Stripe Checkout]({session.url})")
                st.stop()
            except Exception as e:
                st.error(f"Stripe error: {e}")
