import streamlit as st
import pandas as pd
import segno
import io
import zipfile
import sqlite3
import re
import plotly.express as px
from passlib.hash import pbkdf2_sha256
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# ==========================================
# 1. DATABASE & VALIDATION
# ==========================================
def init_db():
    conn = sqlite3.connect('bulkqr_v11.db', check_same_thread=False)
    c = conn.cursor()
    # Email is the Primary Key (Unique)
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (email TEXT PRIMARY KEY, password TEXT, name TEXT, 
                  coins INTEGER, state TEXT, gender TEXT, mobile TEXT, status TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS history (email TEXT, filename TEXT, count INTEGER, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS sales (email TEXT, amount REAL, coins_bought INTEGER, offer_applied TEXT, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS offers (offer_name TEXT, discount_percent INTEGER, active INTEGER)')
    
    if c.execute('SELECT COUNT(*) FROM offers').fetchone()[0] == 0:
        c.execute("INSERT INTO offers VALUES ('No Offer', 0, 1)")
    conn.commit()
    return conn, c

def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def is_valid_mobile(mobile):
    return re.match(r"^[6-9]\d{9}$", mobile)

conn, c = init_db()

# ==========================================
# 2. SETTINGS & SECURITY
# ==========================================
# SET YOUR MASTER ADMIN EMAIL HERE
ADMIN_EMAIL = "admin@bulkqrpro.com" 

st.set_page_config(page_title="BulkQR India Pro", layout="wide")
st.markdown("<style>[data-testid='stSidebar'] {display: none;} .main {padding-top: 0rem;}</style>", unsafe_allow_html=True)

if 'auth' not in st.session_state:
    st.session_state.auth = False

# ==========================================
# 3. LOGIN & REGISTRATION
# ==========================================
if not st.session_state.auth:
    st.title("📸 BulkQR Pro India")
    t1, t2 = st.tabs(["🔑 Login", "📝 Register"])
    
    with t1:
        log_email = st.text_input("Email Address")
        log_pass = st.text_input("Password", type='password')
        if st.button("Login"):
            res = c.execute('SELECT password, status, name FROM users WHERE email=?', (log_email,)).fetchone()
            if res:
                if pbkdf2_sha256.verify(log_pass, res[0]):
                    if res[1] == "Locked":
                        st.error("🚫 Account Locked. Contact support.")
                    else:
                        st.session_state.auth = True
                        st.session_state.user_email = log_email
                        st.session_state.user_name = res[2]
                        st.rerun()
                else: st.error("Incorrect password.")
            else: st.error("Email not found.")
            
    with t2:
        with st.form("reg_form"):
            reg_name = st.text_input("Full Name*")
            reg_email = st.text_input("Email Address*")
            reg_pass = st.text_input("Password*", type='password')
            reg_mob = st.text_input("Mobile Number*")
            reg_state = st.selectbox("State*", ["Delhi", "Maharashtra", "Karnataka", "UP", "Other"])
            if st.form_submit_button("Sign Up"):
                if not (reg_name and reg_email and reg_pass and reg_mob): st.error("All fields mandatory!")
                elif not is_valid_email(reg_email): st.error("Invalid Email!")
                elif not is_valid_mobile(reg_mob): st.error("Invalid Mobile!")
                else:
                    try:
                        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)', 
                                  (reg_email, pbkdf2_sha256.hash(reg_pass), reg_name, 10, reg_state, "N/A", reg_mob, 'Active'))
                        conn.commit()
                        st.success("Registration Successful! Please Login.")
                    except: st.error("This email is already registered.")

# ==========================================
# 4. DASHBOARD (Email-Based Access)
# ==========================================
else:
    u_email = st.session_state.user_email
    u_name = st.session_state.user_name
    balance = c.execute('SELECT coins FROM users WHERE email=?', (u_email,)).fetchone()[0]
    
    # Header Info
    h1, h2 = st.columns([4,1])
    h1.subheader(f"👋 {u_name} | 🪙 {balance} Coins")
    if h2.button("Logout", use_container_width=True):
        st.session_state.auth = False
        st.rerun()

    # NAVIGATION TABS
    nav_list = ["📸 Generator", "💳 Recharge", "📜 My History"]
    # Check if logged-in email matches the MASTER ADMIN EMAIL
    if u_email.lower() == ADMIN_EMAIL.lower():
        nav_list.append("🛠️ Admin Panel")
    
    menu = st.tabs(nav_list)

    # --- TAB 1: QR GENERATOR ---
    with menu[0]:
        file = st.file_uploader("Upload Data File", type=['csv', 'xlsx'])
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
                    c.execute('UPDATE users SET coins = coins - ? WHERE email=?', (len(df), u_email))
                    c.execute('INSERT INTO history VALUES (?,?,?,?)', (u_email, file.name, len(df), datetime.now()))
                    conn.commit()
                    st.session_state.zip_data = zip_buf.getvalue()
                    st.rerun()
                else: st.error("Insufficient balance.")
        
        if 'zip_data' in st.session_state:
            st.download_button("📥 DOWNLOAD ZIP FILE", st.session_state.zip_data, "Bulk_QRs.zip")
            if st.button("Clear Cache"):
                del st.session_state.zip_data
                st.rerun()

    # --- TAB 2: RECHARGE ---
    with menu[1]:
        off = c.execute('SELECT offer_name, discount_percent FROM offers WHERE active=1 LIMIT 1').fetchone()
        if off[1] > 0: st.success(f"🔥 {off[0]} Active: +{off[1]}% Extra Coins!")
        amt = st.number_input("Recharge Amount (₹)", min_value=0)
        if st.button("Pay & Add Coins"):
            if amt >= 10:
                total = int(amt * (1 + off[1]/100))
                c.execute('UPDATE users SET coins = coins + ? WHERE email=?', (total, u_email))
                c.execute('INSERT INTO sales VALUES (?,?,?,?,?)', (u_email, amt, total, off[0], datetime.now()))
                conn.commit()
                st.success(f"Added {total} Coins!")
                st.rerun()

    # --- TAB 3: HISTORY ---
    with menu[2]:
        h_qr, h_pay = st.tabs(["Batches", "Payments"])
        with h_qr: st.dataframe(pd.read_sql_query("SELECT filename, count, timestamp FROM history WHERE email=?", conn, params=(u_email,)))
        with h_pay: st.dataframe(pd.read_sql_query("SELECT amount, coins_bought, timestamp FROM sales WHERE email=?", conn, params=(u_email,)))

    # --- TAB 4: ADMIN PANEL (SECURE) ---
    if u_email.lower() == ADMIN_EMAIL.lower():
        with menu[3]:
            adm = st.tabs(["📊 Stats", "👥 User Manage", "🎁 Offers", "📧 Bulk Email"])
            
            with adm[1]: # User Management
                all_u = pd.read_sql_query("SELECT name, email, mobile, coins, status FROM users", conn)
                st.dataframe(all_u, use_container_width=True)
                
                # Export to Excel
                buf = io.BytesIO()
                all_u.to_excel(buf, index=False)
                st.download_button("📥 Export Users to Excel", buf.getvalue(), "Users_List.xlsx")
                
                # Duplicate Check
                if st.button("🔍 Find Duplicate Mobiles"):
                    st.write(all_u[all_u.duplicated('mobile', keep=False)])
                
                # Single User Edit
                target = st.text_input("Enter Email to Manage Account")
                if target:
                    t_data = c.execute('SELECT coins, status FROM users WHERE email=?', (target,)).fetchone()
                    if t_data:
                        st.write(f"Balance: {t_data[0]} | Status: {t_data[1]}")
                        adj = st.number_input("Adjust Coins", value=0)
                        if st.button("Update"):
                            c.execute('UPDATE users SET coins = coins + ? WHERE email=?', (adj, target))
                            conn.commit(); st.rerun()
                        if st.button("🔒 Toggle Lock"):
                            new_s = "Locked" if t_data[1] == "Active" else "Active"
                            c.execute('UPDATE users SET status=? WHERE email=?', (new_s, target))
                            conn.commit(); st.rerun()
