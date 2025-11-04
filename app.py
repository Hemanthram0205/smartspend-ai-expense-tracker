import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import plotly.express as px
import plotly.graph_objects as go
from contextlib import contextmanager
import calendar
import time 
import hashlib

# ---------- DATABASE UTILITIES ----------
@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    conn = sqlite3.connect("expenses.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize database with proper schema and handle migrations"""
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Check if expenses table exists and has user_id column
        c.execute("PRAGMA table_info(expenses)")
        columns = [column[1] for column in c.fetchall()]
        
        # Create expenses table if it doesn't exist
        if 'expenses' not in [table[0] for table in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            c.execute('''CREATE TABLE expenses
                         (id INTEGER PRIMARY KEY AUTOINCREMENT,
                          category TEXT NOT NULL,
                          amount REAL NOT NULL CHECK(amount >= 0),
                          date TEXT NOT NULL,
                          description TEXT,
                          user_id INTEGER,
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        elif 'user_id' not in columns:
            # Migrate existing table to add user_id column
            c.execute('''ALTER TABLE expenses ADD COLUMN user_id INTEGER''')
        
        # Users table for authentication
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE NOT NULL,
                      password_hash TEXT NOT NULL,
                      email TEXT,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        
        # For existing data without user_id, assign to a default user (user_id = 1)
        c.execute("UPDATE expenses SET user_id = 1 WHERE user_id IS NULL")
        
        conn.commit()

# ---------- AUTHENTICATION FUNCTIONS ----------
def hash_password(password):
    """Hash a password for storing."""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, password_hash):
    """Verify a stored password against one provided by user"""
    return hash_password(password) == password_hash

def create_user(username, password, email=None):
    """Create a new user"""
    with get_db_connection() as conn:
        c = conn.cursor()
        try:
            password_hash = hash_password(password)
            c.execute("INSERT INTO users (username, password_hash, email) VALUES (?, ?, ?)",
                     (username, password_hash, email))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

def authenticate_user(username, password):
    """Authenticate a user"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        user = c.fetchone()
        if user and verify_password(password, user['password_hash']):
            return user['id']
        return None

def get_current_user_expenses(user_id):
    """Get expenses for current user"""
    with get_db_connection() as conn:
        try:
            df = pd.read_sql("SELECT * FROM expenses WHERE user_id = ? ORDER BY date DESC", 
                            conn, params=(user_id,))
            if not df.empty and 'date' in df.columns:
                df['date'] = pd.to_datetime(df['date'])
            return df
        except Exception as e:
            st.error(f"Error loading expenses: {str(e)}")
            return pd.DataFrame()

# ---------- DATA OPERATIONS ----------
def add_expense(category, amount, expense_date, description, user_id):
    """Add a new expense to the database"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO expenses (category, amount, date, description, user_id) VALUES (?, ?, ?, ?, ?)",
                  (category.strip(), amount, expense_date.isoformat(), description.strip(), user_id))
        conn.commit()

def delete_expense(expense_id, user_id):
    """Delete an expense by ID (with user verification)"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM expenses WHERE id=? AND user_id=?", (expense_id, user_id))
        conn.commit()
        return c.rowcount > 0

def get_expense_summary(user_id):
    """Get comprehensive summary statistics for a user"""
    df = get_current_user_expenses(user_id)
    if df.empty:
        return None
    
    # Ensure 'date' is datetime type and handle potential missing columns
    if 'date' not in df.columns:
        return None
        
    df['date'] = pd.to_datetime(df['date'])
    
    today = datetime.now()
    last_30_days = today - timedelta(days=30)
    last_7_days = today - timedelta(days=7)
    
    # FIX: Compare months and years to get current month expenses
    current_month_expenses = df[
        (df['date'].dt.month == today.month) & 
        (df['date'].dt.year == today.year)
    ]['amount'].sum()
    
    last_30_days_expenses = df[df['date'] >= last_30_days]['amount'].sum()
    last_7_days_expenses = df[df['date'] >= last_7_days]['amount'].sum()
    
    summary = {
        'total_expenses': df['amount'].sum(),
        'average_expense': df['amount'].mean(),
        'expense_count': len(df),
        'top_category': df['category'].mode().iloc[0] if not df['category'].mode().empty else 'N/A',
        'largest_expense': df['amount'].max(),
        'monthly_expenses': current_month_expenses,
        'last_30_days': last_30_days_expenses,
        'last_7_days': last_7_days_expenses,
        'daily_average': last_30_days_expenses / 30 if last_30_days_expenses else 0
    }
    return summary

def format_currency(amount):
    """Format amount in Indian Rupees"""
    return f"₹{amount:,.2f}"

# ---------- CHART FUNCTIONS ----------
def create_monthly_trend_chart(df):
    """Create monthly expense trend chart"""
    if df.empty or 'date' not in df.columns:
        return None
        
    monthly = df.groupby(df['date'].dt.to_period('M')).agg({'amount': 'sum', 'id': 'count'}).reset_index()
    monthly['date'] = monthly['date'].astype(str)
    monthly['amount_formatted'] = monthly['amount'].apply(format_currency)
    
    fig = px.line(monthly, x='date', y='amount', 
                  title='Monthly Expense Trends',
                  labels={'amount': 'Amount (₹)', 'date': 'Month'},
                  line_shape='spline',
                  custom_data=[monthly['amount_formatted'], monthly['id']])
    fig.update_traces(line=dict(width=4, color='#3b82f6'),
                      hovertemplate='<b>%{x}</b><br>Amount: %{customdata[0]}<br>Transactions: %{customdata[1]}<extra></extra>')
    fig.update_layout(hoverlabel=dict(bgcolor="white", font_size=12))
    return fig

def create_category_pie_chart(df):
    """Create category-wise pie chart"""
    if df.empty:
        return None
        
    category_totals = df.groupby('category')['amount'].sum().reset_index()
    category_totals = category_totals.sort_values('amount', ascending=False)
    category_totals['amount_formatted'] = category_totals['amount'].apply(format_currency)
    
    fig = px.pie(category_totals, values='amount', names='category',
                 title='Expense Distribution by Category',
                 hole=0.4,
                 custom_data=[category_totals['amount_formatted']])
    fig.update_traces(hovertemplate='<b>%{label}</b><br>Amount: %{customdata[0]}<br>Percentage: %{percent}<extra></extra>')
    return fig

def create_daily_expense_chart(df):
    """Create daily expense chart for last 30 days"""
    if df.empty or 'date' not in df.columns:
        return None
        
    last_30_days = datetime.now() - timedelta(days=30)
    recent_expenses = df[df['date'] >= last_30_days]
    
    if recent_expenses.empty:
        return None
        
    daily = recent_expenses.groupby(recent_expenses['date'].dt.date)['amount'].sum().reset_index()
    daily['amount_formatted'] = daily['amount'].apply(format_currency)
    
    fig = px.bar(daily, x='date', y='amount',
                 title='Daily Expenses (Last 30 Days)',
                 labels={'amount': 'Amount (₹)', 'date': 'Date'},
                 custom_data=[daily['amount_formatted']])
    fig.update_traces(marker_color='#10b981',
                      hovertemplate='<b>%{x}</b><br>Amount: %{customdata[0]}<extra></extra>')
    return fig

def create_category_bar_chart(df):
    """Create horizontal bar chart for categories"""
    if df.empty:
        return None
        
    category_totals = df.groupby('category')['amount'].sum().reset_index()
    category_totals = category_totals.sort_values('amount', ascending=True)
    category_totals['amount_formatted'] = category_totals['amount'].apply(format_currency)
    
    fig = px.bar(category_totals, y='category', x='amount',
                 title='Expenses by Category',
                 labels={'amount': 'Amount (₹)', 'category': 'Category'},
                 orientation='h',
                 custom_data=[category_totals['amount_formatted']])
    fig.update_traces(marker_color='#8b5cf6',
                      hovertemplate='<b>%{y}</b><br>Amount: %{customdata[0]}<extra></extra>')
    return fig

def create_expense_calendar_heatmap(df):
    """Create calendar heatmap of expenses"""
    if df.empty or 'date' not in df.columns:
        return None
        
    daily_expenses = df.groupby(df['date'].dt.date).agg({'amount': 'sum', 'id': 'count'}).reset_index()
    daily_expenses['day_name'] = daily_expenses['date'].apply(lambda x: x.strftime('%A'))
    daily_expenses['month'] = daily_expenses['date'].apply(lambda x: x.strftime('%B'))
    daily_expenses['year'] = daily_expenses['date'].apply(lambda x: x.year)
    
    fig = px.density_heatmap(daily_expenses, x='day_name', y='month', z='amount',
                             title='Expense Calendar Heatmap',
                             category_orders={'day_name': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
                                             'month': list(calendar.month_name[1:])},
                             color_continuous_scale="Blues")
    return fig

def create_spending_timeline(df):
    """Create cumulative spending timeline"""
    if df.empty or 'date' not in df.columns:
        return None
        
    df_sorted = df.sort_values('date')
    df_sorted['cumulative_amount'] = df_sorted['amount'].cumsum()
    df_sorted['amount_formatted'] = df_sorted['amount'].apply(format_currency)
    df_sorted['cumulative_formatted'] = df_sorted['cumulative_amount'].apply(format_currency)
    
    fig = go.Figure()
    
    # Add cumulative line
    fig.add_trace(go.Scatter(x=df_sorted['date'], y=df_sorted['cumulative_amount'],
                             mode='lines', name='Cumulative Spending',
                             line=dict(color='#3b82f6', width=3),
                             customdata=df_sorted['cumulative_formatted'],
                             hovertemplate='<b>%{x}</b><br>Cumulative: %{customdata}<extra></extra>'))
    
    # Add individual expense points
    fig.add_trace(go.Scatter(x=df_sorted['date'], y=df_sorted['amount'],
                             mode='markers', name='Individual Expenses',
                             marker=dict(color='#ef4444', size=6),
                             customdata=df_sorted['amount_formatted'],
                             hovertemplate='<b>%{x}</b><br>Amount: %{customdata}<extra></extra>'))
    
    fig.update_layout(title='Cumulative Spending Timeline',
                      xaxis_title='Date',
                      yaxis_title='Amount (₹)',
                      hovermode='x unified')
    return fig

# ---------- PAGE CONFIG ----------
st.set_page_config(
    page_title="SmartSpend - Expense Tracker", 
    page_icon="💰", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# ---------- CUSTOM CSS ----------
st.markdown("""
    <style>
        .main {
            background-color: #0f1115;
            color: white;
        }
        .app-title {
            text-align: center;
            font-size: 4em; 
            font-weight: 900;
            color: transparent; 
            background: linear-gradient(90deg, #4f46e5, #3b82f6, #1e40af); 
            -webkit-background-clip: text;
            background-clip: text;
            padding: 30px 0;
            margin-bottom: 20px;
            letter-spacing: 2px;
        }
        .nav-container {
            background: linear-gradient(135deg, #1e1e1e 0%, #2d2d2d 100%);
            padding: 25px;
            border-radius: 16px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 20px;
            border: 1px solid #333;
        }
        .stButton button {
            background: linear-gradient(135deg, #3b82f6 0%, #1e40af 100%);
            color: white;
            font-weight: 600;
            border: none;
            border-radius: 12px;
            padding: 12px 24px;
            transition: all 0.3s ease;
            font-size: 16px;
            min-width: 140px;
        }
        .stButton button:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.4);
        }
        .metric-card {
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            padding: 20px;
            border-radius: 12px;
            border: 1px solid #475569;
            text-align: center;
            min-height: 140px; 
            display: flex; 
            flex-direction: column;
            justify-content: center;
        }
        .metric-card h3 {
            margin-bottom: 5px;
            font-size: 0.9em;
        }
        .metric-card h2 {
            font-size: 1.3em;
            margin: 0;
        }
        .success-message {
            padding: 12px;
            background: #10b981;
            color: white;
            border-radius: 8px;
            margin: 10px 0;
        }
        .chart-container {
            background: #1e1e1e;
            padding: 20px;
            border-radius: 12px;
            margin-bottom: 20px;
            border: 1px solid #333;
        }
        .auth-container {
            max-width: 400px;
            margin: 50px auto;
            padding: 30px;
            background: linear-gradient(135deg, #1e293b 0%, #334155 100%);
            border-radius: 16px;
            border: 1px solid #475569;
        }
    </style>
""", unsafe_allow_html=True)

# ---------- INITIALIZATION ----------
init_db()

# ---------- SESSION STATE ----------
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"
if "user_id" not in st.session_state:
    st.session_state.user_id = None
if "username" not in st.session_state:
    st.session_state.username = None
if "show_login" not in st.session_state:
    st.session_state.show_login = True
if "show_register" not in st.session_state:
    st.session_state.show_register = False

# ---------- AUTHENTICATION PAGE ----------
def show_auth_page():
    """Show authentication page (login/register)"""
    st.markdown("<h1 class='app-title'>SmartSpend</h1>", unsafe_allow_html=True)
    
    if st.session_state.show_register:
        show_register_form()
    else:
        show_login_form()

def show_login_form():
    """Show login form"""
    st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
    st.subheader("🔐 Login to SmartSpend")
    
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")
        
        if submitted:
            if username and password:
                user_id = authenticate_user(username, password)
                if user_id:
                    st.session_state.user_id = user_id
                    st.session_state.username = username
                    st.session_state.show_login = False
                    st.success("Login successful!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Invalid username or password")
            else:
                st.error("Please fill in all fields")
    
    if st.button("Create Account"):
        st.session_state.show_register = True
        st.rerun()
    
    st.markdown("</div>", unsafe_allow_html=True)

def show_register_form():
    """Show registration form"""
    st.markdown("<div class='auth-container'>", unsafe_allow_html=True)
    st.subheader("🚀 Create Account")
    
    with st.form("register_form"):
        username = st.text_input("Username")
        email = st.text_input("Email (optional)")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm Password", type="password")
        submitted = st.form_submit_button("Create Account", type="primary")
        
        if submitted:
            if username and password:
                if password == confirm_password:
                    if len(password) >= 6:
                        if create_user(username, password, email):
                            st.success("Account created successfully! Please login.")
                            st.session_state.show_register = False
                            time.sleep(2)
                            st.rerun()
                        else:
                            st.error("Username already exists")
                    else:
                        st.error("Password must be at least 6 characters long")
                else:
                    st.error("Passwords do not match")
            else:
                st.error("Please fill in all required fields")
    
    if st.button("← Back to Login"):
        st.session_state.show_register = False
        st.rerun()
    
    st.markdown("</div>", unsafe_allow_html=True)

# ---------- MAIN APP ----------
def show_main_app():
    """Show the main application after authentication"""
    # User info in sidebar
    with st.sidebar:
        st.success(f"👋 Welcome, **{st.session_state.username}**!")
        if st.button("🚪 Logout"):
            st.session_state.user_id = None
            st.session_state.username = None
            st.session_state.show_login = True
            st.rerun()
        
        st.markdown("---")
        st.markdown("### 💡 Quick Stats")
        df = get_current_user_expenses(st.session_state.user_id)
        if not df.empty and 'amount' in df.columns:
            total = df['amount'].sum()
            count = len(df)
            st.metric("Total Expenses", format_currency(total))
            st.metric("Transaction Count", count)
        else:
            st.info("No expenses yet")
    
    # Navigation
    st.markdown("<h1 class='app-title'>SmartSpend</h1>", unsafe_allow_html=True)
    
    st.markdown("<div class='nav-container'>", unsafe_allow_html=True)
    col1, col2, col3, col4 = st.columns([1, 1, 1, 1])

    with col1:
        if st.button("📊 Dashboard", use_container_width=True):
            st.session_state.page = "Dashboard"
    with col2:
        if st.button("➕ Add Expense", use_container_width=True):
            st.session_state.page = "Add Expense"
    with col3:
        if st.button("📋 View All", use_container_width=True):
            st.session_state.page = "View All"
    with col4:
        if st.button("❌ Delete Expense", use_container_width=True):
            st.session_state.page = "Delete Expense"

    st.markdown("</div>", unsafe_allow_html=True)

    # Page Logic
    if st.session_state.page == "Dashboard":
        show_dashboard()
    elif st.session_state.page == "Add Expense":
        show_add_expense()
    elif st.session_state.page == "View All":
        show_view_all()
    elif st.session_state.page == "Delete Expense":
        show_delete_expense()

def show_dashboard():
    """Show dashboard page"""
    st.subheader("📊 Expense Dashboard")
    
    df = get_current_user_expenses(st.session_state.user_id)
    summary = get_expense_summary(st.session_state.user_id)
    
    if summary and not df.empty and 'amount' in df.columns:
        st.subheader("📈 Key Metrics")
        
        # Row 1 of Metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>💰 Total Spent</h3>
                    <h2>{format_currency(summary['total_expenses'])}</h2>
                </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>📅 This Month</h3>
                    <h2>{format_currency(summary['monthly_expenses'])}</h2>
                </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>📝 Total Transactions</h3>
                    <h2>{summary['expense_count']}</h2>
                </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>📊 Daily Average</h3>
                    <h2>{format_currency(summary['daily_average'])}</h2>
                </div>
            """, unsafe_allow_html=True)

        # Row 2 of Metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>🔥 Last 7 Days</h3>
                    <h2>{format_currency(summary['last_7_days'])}</h2>
                </div>
            """, unsafe_allow_html=True)
        
        with col2:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>📆 Last 30 Days</h3>
                    <h2>{format_currency(summary['last_30_days'])}</h2>
                </div>
            """, unsafe_allow_html=True)
        
        with col3:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>📊 Average Expense</h3>
                    <h2>{format_currency(summary['average_expense'])}</h2>
                </div>
            """, unsafe_allow_html=True)
        
        with col4:
            st.markdown(f"""
                <div class="metric-card">
                    <h3>🏆 Top Category</h3>
                    <h2>{summary['top_category']}</h2>
                </div>
            """, unsafe_allow_html=True)
        
        # Charts Section
        st.subheader("📊 Visual Analytics")
        
        # Row 1: Monthly Trend and Category Pie
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            monthly_chart = create_monthly_trend_chart(df)
            if monthly_chart:
                st.plotly_chart(monthly_chart, use_container_width=True)
            else:
                st.info("No data for monthly trends")
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            category_pie = create_category_pie_chart(df)
            if category_pie:
                st.plotly_chart(category_pie, use_container_width=True)
            else:
                st.info("No data for category distribution")
            st.markdown("</div>", unsafe_allow_html=True)
        
        # Row 2: Category Bar and Daily Expense Chart
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            category_bar = create_category_bar_chart(df)
            if category_bar:
                st.plotly_chart(category_bar, use_container_width=True)
            else:
                st.info("No data for category breakdown")
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            daily_chart = create_daily_expense_chart(df)
            if daily_chart:
                st.plotly_chart(daily_chart, use_container_width=True)
            else:
                st.info("No expenses in the last 30 days")
            st.markdown("</div>", unsafe_allow_html=True)
        
        # Row 3: Advanced Charts
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            timeline_chart = create_spending_timeline(df)
            if timeline_chart:
                st.plotly_chart(timeline_chart, use_container_width=True)
            else:
                st.info("No data for spending timeline")
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            heatmap = create_expense_calendar_heatmap(df)
            if heatmap:
                st.plotly_chart(heatmap, use_container_width=True)
            else:
                st.info("No data for calendar heatmap")
            st.markdown("</div>", unsafe_allow_html=True)
    
    else:
        st.info("🎯 No expenses recorded yet. Start by adding your first expense!")

def show_add_expense():
    """Show add expense page"""
    st.header("➕ Add New Expense")
    
    with st.form("expense_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        
        with col1:
            category = st.selectbox(
                "Category *",
                ["Food", "Transport", "Entertainment", "Groceries", "Utilities", 
                 "Healthcare", "Shopping", "Education", "Rent", "Travel", "Bills", "Other"]
            )
            amount = st.number_input("Amount (₹) *", min_value=0.0, step=1.0, format="%.2f")
        
        with col2:
            expense_date = st.date_input("Date *", value=date.today())
            description = st.text_area("Description", placeholder="Optional description")
        
        submitted = st.form_submit_button("💾 Save Expense", type="primary")
        
        if submitted:
            if not category.strip():
                st.error("Please enter a category")
            elif amount <= 0:
                st.error("Please enter a valid amount")
            else:
                try:
                    add_expense(category, amount, expense_date, description, st.session_state.user_id)
                    st.markdown("<div class='success-message'>✅ **Expense added successfully!**</div>", unsafe_allow_html=True)
                    st.balloons()
                    time.sleep(2)
                    st.session_state.page = "Dashboard"
                    st.rerun()
                except Exception as e:
                    st.error(f"Error adding expense: {str(e)}")

def show_view_all():
    """Show view all expenses page"""
    st.header("📋 All Expenses")
    
    df = get_current_user_expenses(st.session_state.user_id)
    if not df.empty and 'amount' in df.columns:
        # Search and filter functionality
        col1, col2, col3 = st.columns(3)
        with col1:
            search_term = st.text_input("🔍 Search by category or description")
        with col2:
            date_filter = st.selectbox("Filter by", ["All time", "Last 30 days", "Last 90 days", "This month"])
        with col3:
            category_filter = st.selectbox("Category filter", ["All categories"] + list(df['category'].unique()))
        
        # Apply filters
        filtered_df = df.copy()
        if search_term:
            filtered_df = filtered_df[
                filtered_df['category'].str.contains(search_term, case=False, na=False) |
                filtered_df['description'].str.contains(search_term, case=False, na=False)
            ]
        
        if date_filter == "Last 30 days":
            cutoff_date = datetime.now() - timedelta(days=30)
            filtered_df = filtered_df[filtered_df['date'] >= cutoff_date]
        elif date_filter == "Last 90 days":
            cutoff_date = datetime.now() - timedelta(days=90)
            filtered_df = filtered_df[filtered_df['date'] >= cutoff_date]
        elif date_filter == "This month":
            current_month = datetime.now().replace(day=1)
            filtered_df = filtered_df[filtered_df['date'] >= current_month]
        
        if category_filter != "All categories":
            filtered_df = filtered_df[filtered_df['category'] == category_filter]
        
        # Display summary
        total_filtered = filtered_df['amount'].sum()
        st.metric("Total Filtered Expenses", format_currency(total_filtered))
        
        # Display data
        display_df = filtered_df[['id', 'category', 'amount', 'date', 'description']].copy()
        display_df['amount'] = display_df['amount'].apply(lambda x: f"₹{x:,.2f}")
        display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
        
        st.dataframe(
            display_df.rename(
                columns={'id': 'ID', 'category': 'Category', 'amount': 'Amount', 
                         'date': 'Date', 'description': 'Description'}
            ),
            use_container_width=True,
            hide_index=True
        )
        
        # Export option
        csv_data = filtered_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export to CSV",
            data=csv_data,
            file_name=f"expenses_{date.today()}.csv",
            mime="text/csv"
        )
    else:
        st.info("No expenses found. Add some expenses to see them here!")

def show_delete_expense():
    """Show delete expense page"""
    st.header("❌ Delete Expense")
    
    df = get_current_user_expenses(st.session_state.user_id)
    if not df.empty and 'amount' in df.columns:
        # Create a user-friendly selection
        df_display = df.copy()
        df_display['display'] = df_display.apply(
            lambda x: f"ID: {x['id']} | {x['date'].strftime('%Y-%m-%d')} | {x['category']} | ₹{x['amount']:,.2f}", 
            axis=1
        )
        
        expense_to_delete = st.selectbox(
            "Select expense to delete:",
            options=df_display['id'].tolist(),
            format_func=lambda x: df_display[df_display['id'] == x]['display'].iloc[0]
        )
        
        if expense_to_delete:
            selected_expense = df[df['id'] == expense_to_delete].iloc[0]
            
            st.warning("⚠️ This action cannot be undone!")
            st.info(f"""
            **Expense Details:**
            - **Category:** {selected_expense['category']}
            - **Amount:** **{format_currency(selected_expense['amount'])}**
            - **Date:** {selected_expense['date'].strftime('%Y-%m-%d')}
            - **Description:** {selected_expense['description'] or 'N/A'}
            """)
            
            col1, col2 = st.columns([1, 4])
            with col1:
                if st.button("🗑️ Confirm Delete", type="primary"):
                    success = delete_expense(expense_to_delete, st.session_state.user_id)
                    if success:
                        st.markdown("<div class='success-message'>✅ **Expense deleted successfully!**</div>", unsafe_allow_html=True)
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("Error deleting expense. Please try again.")
    else:
        st.info("No expenses available to delete.")

# ---------- MAIN APP FLOW ----------
def main():
    """Main application flow"""
    if st.session_state.user_id is None:
        show_auth_page()
    else:
        show_main_app()

if __name__ == "__main__":
    main()
