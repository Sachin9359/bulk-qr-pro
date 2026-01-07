import streamlit as st
import pandas as pd
import segno
import io
import zipfile
import sqlite3
import re  # Added for Email/Mobile validation
import plotly.express as px
from passlib.hash import pbkdf2_sha256
from datetime import datetime

# ==========================================
# 1. DATABASE & VALIDATION LOGIC
# ==========================================
def init_db():
    conn = sqlite3.connect('bulkqr_v7.db', check_same_thread=False)
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

# Validation Functions
def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def is_valid_mobile(mobile):
    return re.match(r"^[6-9]\d{9}$", mobile) # Indian mobile format

conn, c = init_db()

# ==========================================
# 2. APP SETUP
# ==========================================
st.set_page_config(page_title="BulkQR India", layout="wide")

# Hide Sidebar via CSS
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
    </style>
""", unsafe_allow_html=True)

if 'auth' not in st.session_state:
    st.session_state.auth = False

# ==========================================
# 3. AUTHENTICATION (With Validation)
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
            nu = st.text_input("Username*")
            np = st.text_input("Password*", type='password')
            em = st.text_input("Email Address*")
            mo = st.text_input("Mobile Number*")
            n_geo = st.selectbox("State*", ["Delhi", "Maharashtra", "Karnataka", "UP", "Other"])
            n_gen = st.radio("Gender*", ["Male", "Female"], horizontal=True)
            if st.form_submit_button("Sign Up"):
                if not (nu and np and em and mo):
                    st.error("All fields are mandatory!")
                elif not is_valid_email(em):
                    st.error("Please enter a valid email address!")
                elif not is_valid_mobile(mo):
                    st.error("Please enter a valid 10-digit Indian mobile number!")
                else:
                    try:
                        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', 
                                  (nu, pbkdf2_sha256.hash(np), 10, n_geo, n_gen, em, mo))
                        conn.commit()
                        st.success("Account created! 10 Free Coins added.")
                    except: st.error("Username already exists.")

# ==========================================
# 4. MAIN APP AREA (TOP MENU)
# ==========================================
else:
    user = st.session_state.user
    user_row = c.execute('SELECT coins FROM users WHERE username=?', (user,)).fetchone()
    balance = user_row[0]
    
    # TOP NAVIGATION MENU
    st.write(f"Logged in as: **{user}** | Wallet: **🪙 {balance} Coins**")
    menu = st.tabs(["📸 QR Generator", "💳 Recharge Wallet", "📜 History", "🛠️ Admin (If Admin)", "🚪 Logout"])

    # --- TAB 1: GENERATOR ---
    with menu[0]:
        st.header("Bulk QR Generator")
        file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])
        if file:
            df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
            col = st.selectbox("Select Column", df.columns)
            if st.button(f"Generate {len(df)} QRs"):
                if balance >= len(df):
                    bar = st.progress(0); msg = st.empty(); zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w") as zf:
                        for i, row in df.iterrows():
                            bar.progress((i+1)/len(df))
                            qr = segno.make(str(row[col]), error='h')
                            img_buf = io.BytesIO()
                            qr.save(img_buf, kind='png', scale=20, border=4)
                            zf.writestr(f"qr_{i+1}.png", img_buf.getvalue())
                    c.execute('UPDATE users SET coins = coins - ? WHERE username=?', (len(df), user))
                    c.execute('INSERT INTO history VALUES (?,?,?,?)', (user, file.name, len(df), datetime.now()))
                    conn.commit()
                    st.session_state.zip_data = zip_buf.getvalue()
                    st.rerun()
                else: st.error("Insufficient Coins!")

        if 'zip_data' in st.session_state:
            st.download_button("📥 DOWNLOAD ZIP FILE", st.session_state.zip_data, "Bulk_QRs.zip")
            if st.button("Clear Cache"):
                del st.session_state.zip_data
                st.rerun()

    # --- TAB 2: RECHARGE ---
    with menu[1]:
        st.header("Recharge Your Wallet")
        active_offer = c.execute('SELECT offer_name, discount_percent FROM offers WHERE active=1 LIMIT 1').fetchone()
        if active_offer[1] > 0:
            st.success(f"🔥 Active Offer: {active_offer[0]} (+{active_offer[1]}% Coins Extra!)")
        
        amt = st.number_input("Enter Amount (₹)", min_value=0, step=1)
        if st.button("Purchase Coins"):
            if amt >= 10:
                total_added = int(amt * (1 + active_offer[1]/100))
                c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (total_added, user))
                c.execute('INSERT INTO sales VALUES (?,?,?,?,?)', (user, amt, total_added, active_offer[0], datetime.now()))
                conn.commit()
                st.success(f"Added {total_added} coins!")
                st.rerun()
            else: st.error("Minimum recharge is ₹10")

    # --- TAB 3: HISTORY ---
    with menu[2]:
        st.header("Transaction & QR History")
        h_tab, s_tab = st.tabs(["QR Batches", "Payments"])
        with h_tab:
            st.dataframe(pd.read_sql_query("SELECT filename, count, timestamp FROM history WHERE username=?", conn, params=(user,)))
        with s_tab:
            st.dataframe(pd.read_sql_query("SELECT amount, coins_bought, offer_applied, timestamp FROM sales WHERE username=?", conn, params=(user,)))

    # --- TAB 4: ADMIN ---
    with menu[3]:
        if user == "admin":
            st.header("Admin Dashboard")
            # [Add Admin logic here: Offers, User Manage, Bulk Email]
            st.info("Admin tools active. Set offers or manage users here.")
        else:
            st.warning("Access Denied. Only for Admins.")

    # --- TAB 5: LOGOUT ---
    with menu[4]:
        if st.button("Confirm Logout"):
            st.session_state.auth = False
            st.rerun()
