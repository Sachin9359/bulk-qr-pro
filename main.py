import streamlit as st
import pandas as pd
import segno
import io
import zipfile
import sqlite3
import plotly.express as px
from passlib.hash import pbkdf2_sha256
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# ==========================================
# 1. DATABASE & PDF LOGIC
# ==========================================
def init_db():
    conn = sqlite3.connect('bulkqr_v6.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, coins INTEGER, 
                  state TEXT, gender TEXT, email TEXT, mobile TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS history (username TEXT, filename TEXT, count INTEGER, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS sales (username TEXT, amount REAL, coins_bought INTEGER, offer_applied TEXT, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS offers (offer_name TEXT, discount_percent INTEGER, active INTEGER)')
    if c.execute('SELECT COUNT(*) FROM offers').fetchone()[0] == 0:
        c.execute("INSERT INTO offers VALUES ('No Offer', 0, 1)")
    conn.commit()
    return conn, c

conn, c = init_db()

# ==========================================
# 2. APP SETUP
# ==========================================
st.set_page_config(page_title="BulkQR India Pro", layout="wide")

if 'auth' not in st.session_state:
    st.session_state.auth = False

# ==========================================
# 3. AUTHENTICATION (Mandatory Fields)
# ==========================================
if not st.session_state.auth:
    st.title("📸 BulkQR Pro India")
    t1, t2 = st.tabs(["🔑 Login", "📝 Register"])
    with t1:
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Login"):
            res = c.execute('SELECT password FROM users WHERE username=?', (u,)).fetchone()
            if res and pbkdf2_sha256.verify(p, res[0]):
                st.session_state.auth = True
                st.session_state.user = u
                st.rerun()
            else: st.error("Invalid credentials")
    with t2:
        with st.form("reg_form"):
            nu, np = st.text_input("Username*"), st.text_input("Password*", type='password')
            em, mo = st.text_input("Email Address*"), st.text_input("Mobile Number*")
            n_geo = st.selectbox("State*", ["Delhi", "Maharashtra", "Karnataka", "UP", "Other"])
            n_gen = st.radio("Gender*", ["Male", "Female"], horizontal=True)
            if st.form_submit_button("Sign Up"):
                if not (nu and np and em and mo): st.error("All fields mandatory!")
                else:
                    try:
                        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', (nu, pbkdf2_sha256.hash(np), 10, n_geo, n_gen, em, mo))
                        conn.commit()
                        st.success("Account created! 10 Free Coins added.")
                    except: st.error("Username exists.")

# ==========================================
# 4. MAIN APP AREA
# ==========================================
else:
    user = st.session_state.user
    user_row = c.execute('SELECT coins FROM users WHERE username=?', (user,)).fetchone()
    balance = user_row[0]
    active_offer = c.execute('SELECT offer_name, discount_percent FROM offers WHERE active=1 LIMIT 1').fetchone()

    # --- SIDEBAR RECHARGE ---
    st.sidebar.title(f"👤 {user}")
    st.sidebar.metric("Coins Balance", f"🪙 {balance}")
    st.sidebar.write("---")
    st.sidebar.subheader("💳 Recharge (₹1 = 1 Coin)")
    if active_offer[1] > 0: st.sidebar.success(f"🔥 {active_offer[0]} (+{active_offer[1]}%)")
    
    custom_amount = st.sidebar.number_input("Enter Amount (₹)", min_value=0, step=1)
    if st.sidebar.button("Pay Now"):
        if custom_amount >= 10:
            total_added = int(custom_amount * (1 + active_offer[1]/100))
            c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (total_added, user))
            c.execute('INSERT INTO sales VALUES (?,?,?,?,?)', (user, custom_amount, total_added, active_offer[0], datetime.now()))
            conn.commit()
            st.rerun()
        else: st.sidebar.error("Min ₹10")
    
    if st.sidebar.button("Logout"):
        st.session_state.auth = False
        st.rerun()

    # --- ADMIN OVERLAY ---
    admin_active = False
    if user == "admin":
        admin_active = st.sidebar.toggle("🛠️ Admin Dashboard")

    if admin_active:
        st.title("🛠️ Admin Dashboard")
        at1, at2, at3, at4 = st.tabs(["📈 Sales", "👥 Users", "🎁 Offers", "📧 Bulk Email"])
        with at3:
            o_n = st.text_input("Offer Name")
            o_d = st.slider("Extra Coins %", 0, 100, 0)
            if st.button("Set Offer"):
                c.execute('UPDATE offers SET active=0')
                c.execute('INSERT INTO offers VALUES (?,?,1)', (o_n, o_d))
                conn.commit()
                st.success("Offer Live!")
        with at4:
            st.subheader("Send Announcement")
            subject = st.text_input("Email Subject")
            body = st.text_area("Message Body")
            if st.button("Send to All Users"):
                emails = c.execute("SELECT email FROM users").fetchall()
                st.info(f"Drafting email to {len(emails)} users...")
                st.success("Feature Mockup: Emails added to queue!")
    
    else:
        # --- USER MAIN UI (GENERATOR) ---
        st.title("📸 Bulk QR Generator")
        file = st.file_uploader("Step 1: Upload CSV/Excel", type=['csv', 'xlsx'])
        if file:
            df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
            col = st.selectbox("Step 2: Select Column for QR", df.columns)
            if st.button(f"Step 3: Generate {len(df)} QRs"):
                if balance >= len(df):
                    bar = st.progress(0); msg = st.empty(); zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w") as zf:
                        for i, row in df.iterrows():
                            bar.progress((i+1)/len(df))
                            msg.text(f"Processing {i+1}/{len(df)}...")
                            qr = segno.make(str(row[col]), error='h')
                            img_buf = io.BytesIO()
                            qr.save(img_buf, kind='png', scale=20, border=4)
                            zf.writestr(f"qr_{i+1}.png", img_buf.getvalue())
                    c.execute('UPDATE users SET coins = coins - ? WHERE username=?', (len(df), user))
                    c.execute('INSERT INTO history VALUES (?,?,?,?)', (user, file.name, len(df), datetime.now()))
                    conn.commit()
                    st.session_state.zip_data = zip_buf.getvalue()
                    st.rerun()
                else: st.error("Low balance!")

        if 'zip_data' in st.session_state:
            st.download_button("📥 DOWNLOAD ZIP FILE", st.session_state.zip_data, "Bulk_QRs.zip", "application/zip")
            if st.button("Clear Cache"):
                del st.session_state.zip_data
                st.rerun()

        st.write("---")
        st.subheader("📜 Recent Activity")
        h_tab, s_tab = st.tabs(["QR History", "Payment History"])
        with h_tab:
            st.dataframe(pd.read_sql_query("SELECT filename, count, timestamp FROM history WHERE username=?", conn, params=(user,)))
        with s_tab:
            st.dataframe(pd.read_sql_query("SELECT amount, coins_bought, timestamp FROM sales WHERE username=?", conn, params=(user,)))
