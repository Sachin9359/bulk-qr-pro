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
    # Using v8 to ensure all new columns (status, email, mobile) are created
    conn = sqlite3.connect('bulkqr_v8.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, coins INTEGER, 
                  state TEXT, gender TEXT, email TEXT, mobile TEXT, status TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS history (username TEXT, filename TEXT, count INTEGER, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS sales (username TEXT, amount REAL, coins_bought INTEGER, offer_applied TEXT, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS offers (offer_name TEXT, discount_percent INTEGER, active INTEGER)')
    
    if c.execute('SELECT COUNT(*) FROM offers').fetchone()[0] == 0:
        c.execute("INSERT INTO offers VALUES ('No Offer', 0, 1)")
    conn.commit()
    return conn, c

def is_valid_email(email):
    return re.match(r"[^@]+@[^@]+\.[^@]+", email)

def is_valid_mobile(mobile):
    return re.match(r"^[6-9]\d{9}$", mobile)

def generate_receipt(user, amount, coins, offer):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 20)
    p.drawString(200, 750, "BULKQR PRO INDIA - INVOICE")
    p.setFont("Helvetica", 12)
    p.drawString(50, 700, f"Date: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    p.drawString(50, 680, f"Customer: {user}")
    p.line(50, 660, 550, 660)
    p.drawString(50, 630, f"Coins Added: {coins} (Offer: {offer})")
    p.drawString(50, 610, f"Total Paid: Rs. {amount:.2f}")
    p.line(50, 590, 550, 590)
    p.showPage()
    p.save()
    return buffer.getvalue()

conn, c = init_db()

# ==========================================
# 2. APP UI CONFIG
# ==========================================
st.set_page_config(page_title="BulkQR India Pro", layout="wide")

# Custom CSS to hide the sidebar and style the top header
st.markdown("""
    <style>
        [data-testid="stSidebar"] {display: none;}
        .main {padding-top: 0rem;}
        .stTabs [data-baseweb="tab-list"] {gap: 20px;}
        .stTabs [data-baseweb="tab"] {height: 50px; white-space: pre-wrap; background-color: #f0f2f6; border-radius: 5px; padding: 10px;}
    </style>
""", unsafe_allow_html=True)

if 'auth' not in st.session_state:
    st.session_state.auth = False

# ==========================================
# 3. AUTHENTICATION (Login/Signup)
# ==========================================
if not st.session_state.auth:
    st.title("📸 BulkQR Pro India")
    t1, t2 = st.tabs(["🔑 Login", "📝 Register"])
    
    with t1:
        u = st.text_input("Username")
        p = st.text_input("Password", type='password')
        if st.button("Login"):
            res = c.execute('SELECT password, status FROM users WHERE username=?', (u,)).fetchone()
            if res:
                if pbkdf2_sha256.verify(p, res[0]):
                    if res[1] == "Locked":
                        st.error("🚫 Account Locked. Contact support.")
                    else:
                        st.session_state.auth = True
                        st.session_state.user = u
                        st.rerun()
                else: st.error("Wrong password.")
            else: st.error("User not found.")
            
    with t2:
        with st.form("reg_form"):
            nu, np = st.text_input("Username*"), st.text_input("Password*", type='password')
            em, mo = st.text_input("Email*"), st.text_input("Mobile*")
            n_geo = st.selectbox("State*", ["Delhi", "Maharashtra", "Karnataka", "UP", "Other"])
            n_gen = st.radio("Gender*", ["Male", "Female"], horizontal=True)
            if st.form_submit_button("Sign Up"):
                if not (nu and np and em and mo): st.error("Fill all fields!")
                elif not is_valid_email(em): st.error("Invalid Email!")
                elif not is_valid_mobile(mo): st.error("Invalid Mobile!")
                else:
                    try:
                        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?,?)', (nu, pbkdf2_sha256.hash(np), 10, n_geo, n_gen, em, mo, 'Active'))
                        conn.commit()
                        st.success("Registered! 10 Free Coins Added.")
                    except: st.error("Username taken.")

# ==========================================
# 4. LOGGED IN AREA
# ==========================================
else:
    user = st.session_state.user
    user_data = c.execute('SELECT coins FROM users WHERE username=?', (user,)).fetchone()
    balance = user_data[0]
    
    # --- Top Banner ---
    c1, c2 = st.columns([4,1])
    c1.subheader(f"Welcome, {user} | 🪙 {balance} Coins")
    if c2.button("🚪 Logout", use_container_width=True):
        st.session_state.auth = False
        st.rerun()

    # --- Horizontal Navigation ---
    nav_tabs = ["📸 QR Generator", "💳 Recharge", "📜 My History"]
    if user == "admin": nav_tabs.append("🛠️ Admin Panel")
    
    main_menu = st.tabs(nav_tabs)

    # --- TAB: QR GENERATOR ---
    with main_menu[0]:
        file = st.file_uploader("Upload Excel/CSV", type=['csv', 'xlsx'])
        if file:
            df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
            col = st.selectbox("Select QR Content Column", df.columns)
            if st.button(f"Generate {len(df)} QRs"):
                if balance >= len(df):
                    bar = st.progress(0); msg = st.empty(); zip_buf = io.BytesIO()
                    with zipfile.ZipFile(zip_buf, "w") as zf:
                        for i, row in df.iterrows():
                            bar.progress((i+1)/len(df))
                            msg.text(f"Scanning row {i+1}...")
                            qr = segno.make(str(row[col]), error='h')
                            img_buf = io.BytesIO()
                            qr.save(img_buf, kind='png', scale=20, border=4)
                            zf.writestr(f"qr_{i+1}.png", img_buf.getvalue())
                    c.execute('UPDATE users SET coins = coins - ? WHERE username=?', (len(df), user))
                    c.execute('INSERT INTO history VALUES (?,?,?,?)', (user, file.name, len(df), datetime.now()))
                    conn.commit()
                    st.session_state.zip_data = zip_buf.getvalue()
                    st.rerun()
                else: st.error("Low Coins!")

        if 'zip_data' in st.session_state:
            st.download_button("📥 DOWNLOAD ZIP", st.session_state.zip_data, "Bulk_QRs.zip", type="primary")
            if st.button("Clear Cache"):
                del st.session_state.zip_data
                st.rerun()

    # --- TAB: RECHARGE ---
    with main_menu[1]:
        active_offer = c.execute('SELECT offer_name, discount_percent FROM offers WHERE active=1 LIMIT 1').fetchone()
        st.write(f"**Current Valuation:** ₹1 = 1 Coin")
        if active_offer[1] > 0:
            st.success(f"🔥 Active Offer: {active_offer[0]} (Get {active_offer[1]}% extra coins!)")
        
        amt = st.number_input("Amount to Recharge (₹)", min_value=0)
        if st.button("Proceed to Pay"):
            if amt >= 10:
                extra = int(amt * (active_offer[1]/100))
                total = amt + extra
                c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (total, user))
                c.execute('INSERT INTO sales VALUES (?,?,?,?,?)', (user, amt, total, active_offer[0], datetime.now()))
                conn.commit()
                st.session_state.last_receipt = generate_receipt(user, amt, total, active_offer[0])
                st.success(f"Added {total} coins!")
                st.rerun()
            else: st.error("Minimum ₹10 required.")
        
        if 'last_receipt' in st.session_state:
            st.download_button("📄 Download Receipt", st.session_state.last_receipt, "Receipt.pdf")

    # --- TAB: HISTORY ---
    with main_menu[2]:
        h1, h2 = st.tabs(["QR Batches", "Recharge History"])
        with h1: st.dataframe(pd.read_sql_query("SELECT filename, count, timestamp FROM history WHERE username=?", conn, params=(user,)), use_container_width=True)
        with h2: st.dataframe(pd.read_sql_query("SELECT amount, coins_bought, offer_applied, timestamp FROM sales WHERE username=?", conn, params=(user,)), use_container_width=True)

    # --- TAB: ADMIN ---
    if user == "admin":
        with main_menu[3]:
            adm_nav = st.tabs(["📊 Analytics", "👥 User Management", "🎁 Offers", "📧 Bulk Mail"])
            
            with adm_nav[0]: # Analytics
                df_rev = pd.read_sql_query("SELECT state, SUM(amount) as Revenue FROM sales JOIN users ON sales.username = users.username GROUP BY state", conn)
                st.plotly_chart(px.bar(df_rev, x='state', y='Revenue', title="Revenue by State (₹)"))
            
            with adm_nav[1]: # User Management & Export
                all_u = pd.read_sql_query("SELECT username, email, mobile, coins, status FROM users", conn)
                # Duplicate Check
                if st.button("🔍 Check Duplicates"):
                    dupes = all_u[all_u.duplicated('mobile', keep=False)]
                    st.write(dupes if not dupes.empty else "No duplicates!")
                
                # Excel Export
                exp_buf = io.BytesIO()
                all_u.to_excel(exp_buf, index=False)
                st.download_button("📥 Export Users to Excel", exp_buf.getvalue(), "UserList.xlsx")
                
                # Lock/Coins Manage
                target = st.text_input("Username to manage")
                if target:
                    t_data = c.execute('SELECT coins, status FROM users WHERE username=?', (target,)).fetchone()
                    if t_data:
                        st.write(f"Coins: {t_data[0]} | Status: {t_data[1]}")
                        adj = st.number_input("Adjust Coins", value=0)
                        if st.button("Update Coins"):
                            c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (adj, target))
                            conn.commit()
                            st.rerun()
                        if st.button("🔒 Toggle Lock"):
                            new_s = "Locked" if t_data[1] == "Active" else "Active"
                            c.execute('UPDATE users SET status = ? WHERE username=?', (new_s, target))
                            conn.commit()
                            st.rerun()

            with adm_nav[2]: # Offers
                off_n = st.text_input("Offer Name")
                off_p = st.slider("Extra Coins %", 0, 100, 0)
                if st.button("Set Active Offer"):
                    c.execute('UPDATE offers SET active=0')
                    c.execute('INSERT INTO offers VALUES (?,?,1)', (off_n, off_p))
                    conn.commit()
                    st.success("Offer Updated!")

            with adm_nav[3]: # Bulk Email Mockup
                st.subheader("Send Bulk Notification")
                subj = st.text_input("Subject")
                body = st.text_area("Message")
                if st.button("Send to All Users"):
                    st.info("Emails fetched and sent to SMTP queue successfully!")
