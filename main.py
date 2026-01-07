import streamlit as st
import pandas as pd
import segno
import io
import zipfile
import sqlite3
import plotly.express as px
from passlib.hash import pbkdf2_sha256
from datetime import datetime

# ==========================================
# 1. DATABASE SYSTEM
# ==========================================
def init_db():
    conn = sqlite3.connect('bulkqr_v3.db', check_same_thread=False)
    c = conn.cursor()
    # Users Table: Stores profile, balance, and location
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (username TEXT PRIMARY KEY, password TEXT, coins INTEGER, 
                  country TEXT, gender TEXT)''')
    # History Table: Logs every batch created
    c.execute('CREATE TABLE IF NOT EXISTS history (username TEXT, filename TEXT, count INTEGER, timestamp DATETIME)')
    # Settings Table: Admin price controls
    c.execute('CREATE TABLE IF NOT EXISTS settings (price REAL, cost_per_qr INTEGER)')
    
    if c.execute('SELECT COUNT(*) FROM settings').fetchone()[0] == 0:
        c.execute('INSERT INTO settings VALUES (5.0, 1)')
    conn.commit()
    return conn, c

conn, c = init_db()

# ==========================================
# 2. CONFIG & AUTH STATE
# ==========================================
st.set_page_config(page_title="BulkQR Pro 2026", layout="wide", page_icon="📸")

if 'auth' not in st.session_state:
    st.session_state.auth = False

# ==========================================
# 3. LOGIN & REGISTRATION UI
# ==========================================
if not st.session_state.auth:
    st.title("📸 BulkQR Pro: Login or Register")
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
        n_geo = st.selectbox("Country", ["India", "USA", "UK", "Other"])
        n_gen = st.radio("Gender", ["Male", "Female"], horizontal=True)
        if st.button("Sign Up"):
            try:
                hashed_p = pbkdf2_sha256.hash(np)
                c.execute('INSERT INTO users VALUES (?,?,?,?,?)', (nu, hashed_p, 10, n_geo, n_gen))
                conn.commit()
                st.success("Account created with 10 Free Coins!")
            except: st.error("Username taken!")

# ==========================================
# 4. PROTECTED AREA (Logged In)
# ==========================================
else:
    user = st.session_state.user
    balance = c.execute('SELECT coins FROM users WHERE username=?', (user,)).fetchone()[0]
    
    st.sidebar.title(f"👤 {user}")
    st.sidebar.metric("Your Balance", f"🪙 {balance}")
    
    if st.sidebar.button("Logout"):
        st.session_state.auth = False
        st.rerun()

    # --- ADMIN SECTION ---
    if user == "admin":
        admin_mode = st.sidebar.toggle("🛠️ Admin Dashboard")
        if admin_mode:
            st.title("🛠️ Admin Management & Analytics")
            adm_tab1, adm_tab2 = st.tabs(["📊 Analytics", "👥 User Management"])
            
            with adm_tab1: # Analytics View
                st.subheader("Global User Distribution")
                df_geo = pd.read_sql_query("SELECT country, COUNT(*) as count FROM users GROUP BY country", conn)
                st.plotly_chart(px.pie(df_geo, values='count', names='country', hole=0.4))
            
            with adm_tab2: # USER MANAGEMENT CODE ADDED HERE
                st.subheader("Manage User Accounts")
                search_u = st.text_input("Search Username to manage balance/account")
                if search_u:
                    u_info = c.execute('SELECT coins, country, gender FROM users WHERE username=?', (search_u,)).fetchone()
                    if u_info:
                        st.info(f"User: {search_u} | Country: {u_info[1]} | Gender: {u_info[2]}")
                        st.write(f"**Current Balance:** 🪙 {u_info[0]}")
                        
                        adj = st.number_input("Add or Remove Coins (Use minus for subtract)", value=0)
                        if st.button("Update User Coins"):
                            c.execute('UPDATE users SET coins = coins + ? WHERE username=?', (adj, search_u))
                            conn.commit()
                            st.success("Balance Updated!")
                            st.rerun()

                        if st.button("❌ Delete Account Permanently"):
                            c.execute('DELETE FROM users WHERE username=?', (search_u,))
                            conn.commit()
                            st.warning("User Deleted.")
                            st.rerun()
                    else: st.error("User not found.")
            st.stop() # Prevents admin from seeing user tools while in Admin Mode

    # --- USER TOOLS ---
    st.title("📸 Bulk QR Generator")
    file = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])

    if file:
        df = pd.read_csv(file) if file.name.endswith('.csv') else pd.read_excel(file)
        col = st.selectbox("Select Data Column", df.columns)
        
        if st.button(f"Generate {len(df)} QRs"):
            if balance >= len(df):
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w") as zf:
                    for i, row in df.iterrows():
                        qr = segno.make(str(row[col]))
                        img_buf = io.BytesIO()
                        qr.save(img_buf, kind='png', scale=10)
                        zf.writestr(f"qr_{i}.png", img_buf.getvalue())
                
                c.execute('UPDATE users SET coins = coins - ? WHERE username=?', (len(df), user))
                c.execute('INSERT INTO history VALUES (?,?,?,?)', (user, file.name, len(df), datetime.now()))
                conn.commit()
                st.download_button("📥 Download ZIP", data=zip_buffer.getvalue(), file_name="qrcodes.zip")
                st.rerun()
            else: st.error("Not enough coins!")

    # --- HISTORY ---
    st.write("---")
    st.subheader("📜 Your Download History")
    hist = pd.read_sql_query("SELECT filename, count, timestamp FROM history WHERE username=?", conn, params=(user,))
    st.dataframe(hist, use_container_width=True)