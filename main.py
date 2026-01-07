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
# 1. DATABASE & PDF LOGIC (Updated for ₹)
# ==========================================
def init_db():
    conn = sqlite3.connect('bulkqr_v4.db', check_same_thread=False)
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, coins INTEGER, country TEXT, gender TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS history (username TEXT, filename TEXT, count INTEGER, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS sales (username TEXT, amount REAL, coins_bought INTEGER, timestamp DATETIME)')
    conn.commit()
    return conn, c

def generate_receipt(user, amount, coins):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 20)
    p.drawString(200, 750, "BULKQR PRO - INVOICE")
    p.setFont("Helvetica", 12)
    p.drawString(50, 700, f"Date: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    p.drawString(50, 680, f"Customer: {user}")
    p.line(50, 660, 550, 660)
    p.drawString(50, 630, "Description: QR Coin Recharge (1:1 Ratio)")
    p.drawString(50, 610, f"Coins Added: {coins}")
    p.drawString(50, 590, f"Total Paid: Rs. {amount:.2f}")
    p.line(50, 570, 550, 570)
    p.drawString(50, 550, "Thank you for using BulkQR Pro India!")
    p.showPage()
    p.save()
    return buffer.getvalue()

conn, c = init_db()

# ==========================================
# 2. APP CONFIG
# ==========================================
st.set_page_config(page_title="BulkQR India", layout="wide", page_icon="📸")

if 'auth' not in st.session_state:
    st.session_state.auth = False

# ==========================================
# 3. LOGIN / REGISTRATION
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
        nu = st.text_input("New Username")
        np = st.text_input("New Password", type='password')
        n_geo = st.selectbox("State", ["Delhi", "Maharashtra", "Karnataka", "UP", "Other"])
        n_gen = st.radio("Gender", ["Male", "Female"], horizontal=True)
        if st.button("Sign Up"):
            try:
                hashed = pbkdf2_sha256.hash(np)
                c.execute('INSERT INTO users VALUES (?,?,?,?,?)', (nu, hashed, 10, n_geo, n_gen))
                conn.commit()
                st.success("Account created! 10 Free Welcome Coins added.")
            except: st.error("Username taken.")

# ==========================================
# 4. PROTECTED APP AREA
# ==========================================
else:
    user = st.session_state.user
    balance = c.execute('SELECT coins FROM users WHERE username=?', (user,)).fetchone()[0]
    
    # --- SIDEBAR: WALLET & CUSTOM RECHARGE ---
    st.sidebar.title(f"👤 {user}")
    st.sidebar.metric("Your Balance", f"🪙 {balance} Coins")
    
    st.sidebar.write("---")
    st.sidebar.subheader("💳 Custom Recharge")
    st.sidebar.caption("Min: ₹10 | 1 Rupee = 1 Coin")
    
    # Custom Amount Input
    custom_amount = st.sidebar.number_input("Enter Amount (₹)", min_value=0, step=1)
    
    if st.sidebar.button("Pay Now"):
        if custom_amount >= 10:
            # 1 Rupee = 1 Coin logic
            coins_to_add = int(custom_amount)
            c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (coins_to_add, user))
            c.execute('INSERT INTO sales VALUES (?,?,?,?)', (user, custom_amount, coins_to_add, datetime.now()))
            conn.commit()
            st.session_state.last_receipt = generate_receipt(user, custom_amount, coins_to_add)
            st.sidebar.success(f"Added {coins_to_add} Coins!")
            st.rerun()
        else:
            st.sidebar.error("Minimum recharge is ₹10")

    if 'last_receipt' in st.session_state:
        st.sidebar.download_button("📄 Download Receipt (PDF)", st.session_state.last_receipt, "Receipt.pdf", "application/pdf")

    if st.sidebar.button("Logout"):
        st.session_state.auth = False
        st.rerun()

    # --- ADMIN DASHBOARD ---
    if user == "admin":
        if st.sidebar.toggle("🛠️ Admin Dashboard"):
            st.title("🛠️ Admin Management")
            at1, at2 = st.tabs(["📊 Revenue", "👥 Users"])
            with at1:
                df_rev = pd.read_sql_query("SELECT SUM(amount) as revenue, country as state FROM sales JOIN users ON sales.username = users.username GROUP BY country", conn)
                st.plotly_chart(px.bar(df_rev, x='state', y='revenue', title="Revenue by State (₹)"))
            with at2:
                search = st.text_input("Search User")
                if search:
                    u_data = c.execute('SELECT coins FROM users WHERE username=?', (search,)).fetchone()
                    if u_data:
                        adj = st.number_input("Adjust Coins", value=0)
                        if st.button("Update"):
                            c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (adj, search))
                            conn.commit()
                            st.success("Updated")
            st.stop()

    # --- QR GENERATOR (Improved for Scanning) ---
    st.title("📸 Bulk QR Generator")
    file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])
    if file:
        df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
        col = st.selectbox("Select Data Column", df.columns)
        if st.button(f"Generate {len(df)} QRs"):
            if balance >= len(df):
                bar = st.progress(0)
                msg = st.empty()
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w") as zf:
                    for i, row in df.iterrows():
                        bar.progress((i+1)/len(df))
                        msg.text(f"Processing {i+1}/{len(df)}")
                        # HIGH SCAN QUALITY SETTINGS
                        qr = segno.make(str(row[col]), error='h')
                        img_buf = io.BytesIO()
                        qr.save(img_buf, kind='png', scale=20, border=4)
                        zf.writestr(f"qr_{i+1}.png", img_buf.getvalue())
                
                c.execute('UPDATE users SET coins = coins - ? WHERE username=?', (len(df), user))
                c.execute('INSERT INTO history VALUES (?,?,?,?)', (user, file.name, len(df), datetime.now()))
                conn.commit()
                st.session_state.zip_data = zip_buf.getvalue()
                st.rerun()
            else: st.error(f"You need {len(df)} coins. Please recharge ₹{len(df) - balance} more.")

    if 'zip_data' in st.session_state:
        st.download_button("📥 DOWNLOAD ZIP FILE", st.session_state.zip_data, "Bulk_QRs.zip", "application/zip")
        if st.button("Clear Download"):
            del st.session_state.zip_data
            st.rerun()

    st.write("---")
    st.subheader("📜 History")
    st.dataframe(pd.read_sql_query("SELECT filename, count, timestamp FROM history WHERE username=?", conn, params=(user,)), use_container_width=True)
