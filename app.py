import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime, date, timedelta
import plotly.express as px
import plotly.graph_objects as go
from contextlib import contextmanager
import calendar
import time 

# ---------- DATABASE UTILITIES ----------
@contextmanager
def get_db_connection():
    """Context manager for database connections"""
    # check_same_thread=False is needed for Streamlit's multiprocessing model
    conn = sqlite3.connect("expenses.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize database with proper schema"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS expenses
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      category TEXT NOT NULL,
                      amount REAL NOT NULL CHECK(amount >= 0),
                      date TEXT NOT NULL,
                      description TEXT,
                      created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()

# ---------- DATA OPERATIONS ----------
def add_expense(category, amount, expense_date, description):
    """Add a new expense to the database"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT INTO expenses (category, amount, date, description) VALUES (?, ?, ?, ?)",
                  (category.strip(), amount, expense_date.isoformat(), description.strip()))
        conn.commit()

def get_all_expenses():
    """Retrieve all expenses as a DataFrame"""
    with get_db_connection() as conn:
        df = pd.read_sql("SELECT * FROM expenses ORDER BY date DESC", conn)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
        return df

def delete_expense(expense_id):
    """Delete an expense by ID"""
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
        conn.commit()
        return c.rowcount > 0

def get_expense_summary():
    """Get comprehensive summary statistics"""
    df = get_all_expenses()
    if df.empty:
        return None
    
    # FIX: Explicitly ensure 'date' is datetime type, preventing AttributeError
    df['date'] = pd.to_datetime(df['date'])
    
    today = datetime.now()
    last_30_days = today - timedelta(days=30)
    last_7_days = today - timedelta(days=7)
    
    # Use to_period() for reliable month filtering
    monthly_expenses = df[df['date'].dt.to_period('M') == today.to_period('M')]['amount'].sum()
    last_30_days_expenses = df[df['date'] >= last_30_days]['amount'].sum()
    last_7_days_expenses = df[df['date'] >= last_7_days]['amount'].sum()
    
    summary = {
        'total_expenses': df['amount'].sum(),
        'average_expense': df['amount'].mean(),
        'expense_count': len(df),
        'top_category': df['category'].mode().iloc[0] if not df['category'].mode().empty else 'N/A',
        'largest_expense': df['amount'].max(),
        'monthly_expenses': monthly_expenses,
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
    df_sorted = df.sort_values('date')
    df_sorted['cumulative_amount'] = df_sorted['amount'].cumsum()
    df_sorted['amount_formatted'] = df_sorted['amount'].apply(format_currency)
    df_sorted['cumulative_formatted'] = df_sorted['cumulative_amount'].apply(format_currency)
    
    fig = go.Figure()
    
    # Add cumulative line
    fig.add_trace(go.Scatter(x=df_sorted['date'], y=df_sorted['cumulative_amount'],
                             mode='lines', name='Cumulative Spending',
                             line=dict(color='#3b82f6', width=3),
                             customdata=df_sorted['cumulative_formatted'], # Use formatted data for hover
                             hovertemplate='<b>%{x}</b><br>Cumulative: %{customdata}<extra></extra>'))
    
    # Add individual expense points
    fig.add_trace(go.Scatter(x=df_sorted['date'], y=df_sorted['amount'],
                             mode='markers', name='Individual Expenses',
                             marker=dict(color='#ef4444', size=6),
                             customdata=df_sorted['amount_formatted'], # Use formatted data for hover
                             hovertemplate='<b>%{x}</b><br>Amount: %{customdata}<extra></extra>'))
    
    fig.update_layout(title='Cumulative Spending Timeline',
                      xaxis_title='Date',
                      yaxis_title='Amount (₹)',
                      hovermode='x unified')
    return fig

# ---------- PAGE CONFIG ----------
st.set_page_config(
    page_title="Expense Tracker", 
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
        /* --- CSS FOR THE APP TITLE --- */
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
        /* --- END APP TITLE CSS --- */
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
            /* FIX: ADDED FOR UNIFORM HEIGHT and ALIGNMENT */
            min-height: 140px; 
            display: flex; 
            flex-direction: column;
            justify-content: center;
        }
        .metric-card h3 {
            margin-bottom: 5px; /* Adjust spacing inside card */
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
    </style>
""", unsafe_allow_html=True)

# ---------- INITIALIZATION ----------
init_db()

# ---------- SESSION STATE ----------
if "page" not in st.session_state:
    st.session_state.page = "Dashboard"

# ---------- NAVIGATION ----------
# ADDED TITLE
st.markdown("<h1 class='app-title'>SmartSpend</h1>", unsafe_allow_html=True) 

# Start the navigation container
st.markdown("<div class='nav-container' style='margin-bottom: 30px;'>", unsafe_allow_html=True)
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

# ---------- PAGE LOGIC ----------
if st.session_state.page == "Dashboard":
    # FONT SIZE REDUCTION: Using st.subheader
    st.subheader("📊 Expense Dashboard") 
    
    df = get_all_expenses()
    summary = get_expense_summary()
    
    if summary and not df.empty:
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
            st.plotly_chart(monthly_chart, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            category_pie = create_category_pie_chart(df)
            st.plotly_chart(category_pie, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        
        # Row 2: Category Bar and Daily Expense Chart 
        col1, col2 = st.columns(2) 
        
        with col1:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            category_bar = create_category_bar_chart(df)
            st.plotly_chart(category_bar, use_container_width=True)
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
            st.plotly_chart(timeline_chart, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
        
        with col2:
            st.markdown("<div class='chart-container'>", unsafe_allow_html=True)
            heatmap = create_expense_calendar_heatmap(df)
            st.plotly_chart(heatmap, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)
    
    else:
        st.info("🎯 No expenses recorded yet. Start by adding your first expense!")

elif st.session_state.page == "Add Expense":
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
                    add_expense(category, amount, expense_date, description)
                    st.markdown("<div class='success-message'>✅ **Expense added successfully!**</div>", unsafe_allow_html=True)
                    st.balloons()
                except Exception as e:
                    st.error(f"Error adding expense: {str(e)}")

elif st.session_state.page == "View All":
    st.header("📋 All Expenses")
    
    df = get_all_expenses()
    if not df.empty:
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
        st.metric("**Total Filtered Expenses**", f"**{format_currency(total_filtered)}**")
        
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

elif st.session_state.page == "Delete Expense":
    st.header("❌ Delete Expense")
    
    df = get_all_expenses()
    if not df.empty:
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
                    success = delete_expense(expense_to_delete)
                    if success:
                        st.markdown("<div class='success-message'>✅ **Expense deleted successfully!**</div>", unsafe_allow_html=True)
                        time.sleep(1.5)
                        st.rerun()
                    else:
                        st.error("Error deleting expense. Please try again.")
    else:
        st.info("No expenses available to delete.")
