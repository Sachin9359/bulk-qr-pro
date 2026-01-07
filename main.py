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
# 1. DATABASE & VALIDATION LOGIC
# ==========================================
def init_db():
    # New database version to handle schema change
    conn = sqlite3.connect('bulkqr_v10.db', check_same_thread=False)
    c = conn.cursor()
    # Unique identification is now Email
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

def generate_receipt(user_name, email, amount, coins, offer):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 20)
    p.drawString(200, 750, "BULKQR PRO INDIA - INVOICE")
    p.setFont("Helvetica", 12)
    p.drawString(50, 700, f"Date: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    p.drawString(50, 680, f"Customer Name: {user_name}")
    p.drawString(50, 660, f"Email: {email}")
    p.line(50, 640, 550, 640)
    p.drawString(50, 610, f"Coins Added: {coins} (Offer: {offer})")
    p.drawString(50, 590, f"Total Paid: Rs. {amount:.2f}")
    p.line(50, 570, 550, 570)
    p.showPage()
    p.save()
    return buffer.getvalue()

conn, c = init_db()

# ==========================================
# 2. UI CONFIG & CSS
# ==========================================
st.set_page_config(page_title="BulkQR India Pro", layout="wide")
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        .main {padding-top: 0rem;}
        .stTabs [data-baseweb="tab-list"] {gap: 15px;}
        .stTabs [data-baseweb="tab"] {background-color: #f0f2f6; border-radius: 5px; padding: 10px;}
    </style>
""", unsafe_allow_html=True)

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
            else: st.error("Account not found.")
            
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
                elif not is_valid_mobile(reg_mob): st.error("Invalid 10-digit Mobile!")
                else:
                    try:
                        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)', 
                                  (reg_email, pbkdf2_sha256.hash(reg_pass), reg_name, 10, reg_state, "N/A", reg_mob, 'Active'))
                        conn.commit()
                        st.success("Registered! 10 Welcome Coins added. Please Login.")
                    except: st.error("Email already registered.")

# ==========================================
# 4. PROTECTED APP AREA
# ==========================================
else:
    u_email = st.session_state.user_email
    u_name = st.session_state.user_name
    balance = c.execute('SELECT coins FROM users WHERE email=?', (u_email,)).fetchone()[0]
    
    # Top Header
    h1, h2 = st.columns([4,1])
    h1.subheader(f"👋 {u_name} | 🪙 {balance} Coins")
    if h2.button("Logout", use_container_width=True):
        st.session_state.auth = False
        st.rerun()

    # Top Navigation Tabs
    tabs = ["📸 Generator", "💳 Recharge", "📜 History"]
    if u_name.lower() == "admin": tabs.append("🛠️ Admin Panel")
    menu = st.tabs(tabs)

    # --- TAB: QR GENERATOR ---
    with menu[0]:
        file = st.file_uploader("Upload Data File", type=['csv', 'xlsx'])
        if file:
            df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
            col = st.selectbox("Select Column for QR", df.columns)
            if st.button(f"Generate {len(df)} QRs"):
                if balance >= len(df):
                    bar = st.progress(0); msg = st.empty(); zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w") as zf:
                        for i, row in df.iterrows():
                            bar.progress((i+1)/len(df))
                            msg.text(f"Processing... {i+1}/{len(df)}")
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
            st.download_button("📥 DOWNLOAD ZIP FILE", st.session_state.zip_data, "Bulk_QRs.zip", type="primary")
            if st.button("Clear Cache"):
                del st.session_state.zip_data
                st.rerun()

    # --- TAB: RECHARGE ---
    with menu[1]:
        offer = c.execute('SELECT offer_name, discount_percent FROM offers WHERE active=1 LIMIT 1').fetchone()
        if offer[1] > 0: st.success(f"🔥 {offer[0]}: Get {offer[1]}% extra coins!")
        
        amt = st.number_input("Enter Amount (₹)", min_value=0)
        if st.button("Pay Now"):
            if amt >= 10:
                total = int(amt * (1 + offer[1]/100))
                c.execute('UPDATE users SET coins = coins + ? WHERE email=?', (total, u_email))
                c.execute('INSERT INTO sales VALUES (?,?,?,?,?)', (u_email, amt, total, offer[0], datetime.now()))
                conn.commit()
                st.session_state.last_receipt = generate_receipt(u_name, u_email, amt, total, offer[0])
                st.rerun()
            else: st.error("Minimum ₹10")
        
        if 'last_receipt' in st.session_state:
            st.download_button("📄 Download Receipt", st.session_state.last_receipt, "Receipt.pdf")

    # --- TAB: HISTORY ---
    with menu[2]:
        t_qr, t_pay = st.tabs(["QR Batches", "Recharges"])
        with t_qr: st.dataframe(pd.read_sql_query("SELECT filename, count, timestamp FROM history WHERE email=?", conn, params=(u_email,)), use_container_width=True)
        with t_pay: st.dataframe(pd.read_sql_query("SELECT amount, coins_bought, timestamp FROM sales WHERE email=?", conn, params=(u_email,)), use_container_width=True)

    # --- TAB: ADMIN PANEL ---
    if u_name.lower() == "admin":
        with menu[3]:
            adm_menu = st.tabs(["📈 Stats", "👥 Users", "🎁 Offers", "📧 Bulk Email"])
            
            with adm_menu[0]: # Stats
                df_s = pd.read_sql_query("SELECT state, SUM(amount) as Revenue FROM sales JOIN users ON sales.email = users.email GROUP BY state", conn)
                st.plotly_chart(px.bar(df_s, x='state', y='Revenue'))
            
            with adm_nav[1]: # User Management (Lock, Export, Duplicate Check)
                all_u = pd.read_sql_query("SELECT name, email, mobile, coins, status FROM users", conn)
                st.dataframe(all_u, use_container_width=True)
                
                # Duplicate Check
                if st.button("🔍 Find Duplicate Mobiles"):
                    st.write(all_u[all_u.duplicated('mobile', keep=False)])
                
                # Export
                buf = io.BytesIO()
                all_u.to_excel(buf, index=False)
                st.download_button("📥 Export User List to Excel", buf.getvalue(), "Users.xlsx")
                
                # Individual Control
                target = st.text_input("Enter Email to Manage User")
                if target:
                    t_info = c.execute('SELECT coins, status FROM users WHERE email=?', (target,)).fetchone()
                    if t_info:
                        st.write(f"Current Status: {t_info[1]}")
                        if st.button("🔒 Toggle Lock/Unlock"):
                            new_s = "Locked" if t_info[1] == "Active" else "Active"
                            c.execute('UPDATE users SET status=? WHERE email=?', (new_s, target))
                            conn.commit(); st.rerun()
            
            with adm_nav[2]: # Offers logic...
                st.write("Set global discounts here.")
                # ... [Offer setting code]

            with adm_nav[3]: # Bulk Email logic...
                st.write("Draft notification to all users.")
