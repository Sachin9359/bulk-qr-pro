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
    conn = sqlite3.connect('bulkqr_v5.db', check_same_thread=False)
    c = conn.cursor()
    # Updated User Table with Email and Mobile
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, coins INTEGER, 
                  state TEXT, gender TEXT, email TEXT, mobile TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS history (username TEXT, filename TEXT, count INTEGER, timestamp DATETIME)')
    c.execute('CREATE TABLE IF NOT EXISTS sales (username TEXT, amount REAL, coins_bought INTEGER, offer_applied TEXT, timestamp DATETIME)')
    # New Offer Table
    c.execute('CREATE TABLE IF NOT EXISTS offers (offer_name TEXT, discount_percent INTEGER, active INTEGER)')
    
    # Initialize default offer if empty
    if c.execute('SELECT COUNT(*) FROM offers').fetchone()[0] == 0:
        c.execute("INSERT INTO offers VALUES ('No Offer', 0, 1)")
    conn.commit()
    return conn, c

def generate_receipt(user, amount, coins, offer):
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica-Bold", 20)
    p.drawString(200, 750, "BULKQR PRO INDIA - INVOICE")
    p.setFont("Helvetica", 12)
    p.drawString(50, 700, f"Date: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    p.drawString(50, 680, f"Customer: {user}")
    p.drawString(50, 660, f"Offer Applied: {offer}")
    p.line(50, 640, 550, 640)
    p.drawString(50, 610, f"Coins Added: {coins}")
    p.drawString(50, 590, f"Total Paid: Rs. {amount:.2f}")
    p.line(50, 570, 550, 570)
    p.drawString(50, 550, "Thank you for your business!")
    p.showPage()
    p.save()
    return buffer.getvalue()

conn, c = init_db()

# ==========================================
# 2. APP CONFIG
# ==========================================
st.set_page_config(page_title="BulkQR India Pro", layout="wide")

if 'auth' not in st.session_state:
    st.session_state.auth = False

# ==========================================
# 3. LOGIN / REGISTRATION (Mandatory Fields)
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
            st.write("All fields are mandatory")
            nu = st.text_input("Username*")
            np = st.text_input("Password*", type='password')
            em = st.text_input("Email Address*")
            mo = st.text_input("Mobile Number*")
            n_geo = st.selectbox("State*", ["Delhi", "Maharashtra", "Karnataka", "UP", "Other"])
            n_gen = st.radio("Gender*", ["Male", "Female"], horizontal=True)
            submit = st.form_submit_button("Sign Up")
            
            if submit:
                if not (nu and np and em and mo):
                    st.error("Please fill in all fields!")
                else:
                    try:
                        hashed = pbkdf2_sha256.hash(np)
                        c.execute('INSERT INTO users VALUES (?,?,?,?,?,?,?)', (nu, hashed, 10, n_geo, n_gen, em, mo))
                        conn.commit()
                        st.success("Account created! 10 Free Coins added.")
                    except: st.error("Username already exists.")

# ==========================================
# 4. PROTECTED AREA
# ==========================================
else:
    user = st.session_state.user
    balance = c.execute('SELECT coins FROM users WHERE username=?', (user,)).fetchone()[0]
    active_offer = c.execute('SELECT offer_name, discount_percent FROM offers WHERE active=1 LIMIT 1').fetchone()
    
    # --- SIDEBAR: RECHARGE ---
    st.sidebar.title(f"👤 {user}")
    st.sidebar.metric("Coins Balance", f"🪙 {balance}")
    
    st.sidebar.write("---")
    st.sidebar.subheader("💳 Recharge (₹1 = 1 Coin)")
    if active_offer[1] > 0:
        st.sidebar.success(f"🔥 Offer: {active_offer[0]} ({active_offer[1]}% Extra Coins!)")
    
    custom_amount = st.sidebar.number_input("Enter Amount (₹)", min_value=0, step=1)
    if st.sidebar.button("Pay Now"):
        if custom_amount >= 10:
            extra_coins = int(custom_amount * (active_offer[1]/100))
            total_added = int(custom_amount) + extra_coins
            
            c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (total_added, user))
            c.execute('INSERT INTO sales VALUES (?,?,?,?,?)', (user, custom_amount, total_added, active_offer[0], datetime.now()))
            conn.commit()
            st.session_state.last_receipt = generate_receipt(user, custom_amount, total_added, active_offer[0])
            st.sidebar.success(f"Success! {total_added} Coins added.")
            st.rerun()
        else: st.sidebar.error("Min: ₹10")

    if 'last_receipt' in st.session_state:
        st.sidebar.download_button("📄 Download Receipt", st.session_state.last_receipt, "Receipt.pdf")

    # --- ADMIN: OFFER MANAGEMENT ---
    if user == "admin":
        if st.sidebar.toggle("🛠️ Admin Dashboard"):
            st.title("🛠️ Admin Management")
            at1, at2, at3 = st.tabs(["📈 Sales Analytics", "👥 Users", "🎁 Set Offers"])
            
            with at3:
                st.subheader("Manage Active Offer")
                off_name = st.text_input("Offer Name (e.g. Diwali Special)")
                off_disc = st.slider("Extra Coins %", 0, 100, 0)
                if st.button("Update Active Offer"):
                    c.execute('UPDATE offers SET active=0') # Disable old ones
                    c.execute('INSERT INTO offers VALUES (?, ?, 1)', (off_name, off_disc))
                    conn.commit()
                    st.success("Offer updated successfully!")
            
            with at2:
                search = st.text_input("Manage User Balance")
                if search:
                    u_d = c.execute('SELECT coins, email, mobile FROM users WHERE username=?', (search,)).fetchone()
                    if u_d:
                        st.write(f"Email: {u_d[1]} | Mobile: {u_d[2]}")
                        adj = st.number_input("Add/Sub Coins", value=0)
                        if st.button("Update User"):
                            c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (adj, search))
                            conn.commit()
                            st.rerun()
            st.stop()

    # --- USER MAIN PAGE ---
    st.title("📸 Bulk QR Generator")
    # ... [QR Generation Code remains the same as previous step] ...
    # (Including high-scan quality settings: scale=20, border=4)

    # --- NEW: TRANSACTION HISTORY ---
    st.write("---")
    st.subheader("💰 Transaction History")
    sales_df = pd.read_sql_query("SELECT amount as 'Amount (₹)', coins_bought as 'Coins Received', offer_applied as 'Offer', timestamp as 'Date' FROM sales WHERE username=?", conn, params=(user,))
    if not sales_df.empty:
        st.table(sales_df)
    else: st.info("No recharges yet.")
