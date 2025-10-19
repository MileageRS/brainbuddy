# ---------- Premium (Stripe) ----------
import stripe, time
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# tiny local "pro users" db (MVP)
PRO_PATH = os.path.join(APP_DIR, ".pro.json")
def load_pro():
    if os.path.exists(PRO_PATH):
        try:
            with open(PRO_PATH, "r") as f: return json.load(f)
        except Exception: return {}
    return {}
def save_pro(d):
    with open(PRO_PATH, "w") as f: json.dump(d, f, indent=2)

pro_db = load_pro()
is_pro = USER["id"] in pro_db

# handle Stripe return
session_id = st.query_params.get("session_id", [None])[0] if hasattr(st, "query_params") else None
if session_id and STRIPE_SECRET_KEY:
    try:
        s = stripe.checkout.Session.retrieve(session_id)
        if (s.get("payment_status") == "paid") or (s.get("status") in ("complete",)) or (s.get("mode") == "subscription" and s.get("subscription")):
            pro_db[USER["id"]] = {"ts": time.time(), "session": session_id}
            save_pro(pro_db)
            is_pro = True
            st.success("✅ Premium unlocked!")
    except Exception as e:
        st.info(f"Stripe check error: {e}")

# lift limits for pro
if is_pro:
    FREE_DAILY_LIMIT = 10**9
    remaining = 999999

st.markdown("---")
st.subheader("Upgrade to Premium")

if is_pro:
    st.success("You're on **Premium**. Unlimited answers unlocked.")
else:
    if not (STRIPE_SECRET_KEY and STRIPE_PRICE_ID and PUBLIC_BASE_URL):
        st.info("Upgrade unavailable: missing Stripe config. Ask the owner to set STRIPE_SECRET_KEY, STRIPE_PRICE_ID and PUBLIC_BASE_URL on the server.")
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
