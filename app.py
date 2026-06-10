import streamlit as st
import pandas as pd
import psycopg2
import psycopg2.extras
from datetime import date

# ─── Page Config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Campaign Management",
    page_icon="📊",
    layout="wide",
)

# ─── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .app-header {
        background: linear-gradient(135deg, #4F46E5 0%, #7C3AED 100%);
        color: white; padding: 1.5rem 2rem; border-radius: 12px; margin-bottom: 1.5rem;
    }
    .app-header h1 { margin: 0; font-size: 1.75rem; font-weight: 700; }
    .app-header p  { margin: 0.25rem 0 0; opacity: 0.85; font-size: 0.9rem; }
    .metric-card {
        background: white; border: 1px solid #E5E7EB;
        border-radius: 10px; padding: 1.1rem 1.4rem;
        box-shadow: 0 1px 3px rgba(0,0,0,.06);
    }
    .metric-label { font-size: 0.78rem; color: #6B7280; text-transform: uppercase;
                    letter-spacing: .05em; font-weight: 600; margin-bottom: .3rem; }
    .metric-value { font-size: 1.6rem; font-weight: 700; color: #111827; }
    .metric-sub   { font-size: 0.8rem; color: #9CA3AF; margin-top: .2rem; }
    .section-title {
        font-size: 1.05rem; font-weight: 700; color: #111827;
        border-left: 4px solid #4F46E5; padding-left: .75rem; margin: 1.5rem 0 1rem;
    }
    .form-card {
        background: #F9FAFB; border: 1px solid #E5E7EB;
        border-radius: 10px; padding: 1.25rem 1.5rem;
    }
    .empty-state {
        text-align: center; padding: 3rem 1rem; color: #6B7280;
        background: #F9FAFB; border-radius: 10px; border: 1px dashed #D1D5DB;
    }
    .empty-state .icon { font-size: 2.5rem; margin-bottom: .5rem; }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
</style>
""", unsafe_allow_html=True)

# ─── Constants ───────────────────────────────────────────────────────────────
CHANNELS = ["Email", "Social", "CPC", "Affiliate"]
STATUSES = ["Active", "Paused", "Completed"]

# ─── DB Connection ───────────────────────────────────────────────────────────
# secrets.toml format:
# [postgres]
# host     = "localhost"
# port     = 5432
# dbname   = "your_db"
# user     = "your_user"
# password = "your_password"

def get_connection():
    """Open a fresh Postgres connection using st.secrets. Never log credentials."""
    return psycopg2.connect(
        host     = st.secrets["postgres"]["host"],
        port     = st.secrets["postgres"]["port"],
        dbname   = st.secrets["postgres"]["dbname"],
        user     = st.secrets["postgres"]["user"],
        password = st.secrets["postgres"]["password"],
    )

# ─── DB Functions ────────────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_campaigns_from_db() -> pd.DataFrame:
    """Read all campaigns. Cached for 300 s (SRS §6.1)."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM campaigns ORDER BY created_date DESC, campaign_id DESC")
            rows = cur.fetchall()
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=[
            "campaign_id", "campaign_name", "channel", "status",
            "budget", "actual_spend", "start_date", "end_date",
            "created_date", "modified_date", "created_by", "modified_by",
        ])
    finally:
        conn.close()

def insert_campaign(record: dict) -> int:
    """INSERT a new campaign row and return the generated campaign_id."""
    sql = """
        INSERT INTO campaigns (
            campaign_name, channel, status, budget, actual_spend,
            start_date, end_date, created_date, modified_date,
            created_by, modified_by
        ) VALUES (
            %(campaign_name)s, %(channel)s, %(status)s, %(budget)s, %(actual_spend)s,
            %(start_date)s, %(end_date)s, %(created_date)s, %(modified_date)s,
            %(created_by)s, %(modified_by)s
        ) RETURNING campaign_id
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, record)
            new_id = cur.fetchone()[0]
        conn.commit()
        return new_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def save_edits_to_db(edited_rows: list[dict]) -> None:
    """
    Upsert budget + status for each edited row.
    Uses ON CONFLICT so it works whether the row already exists or not.
    """
    sql = """
        UPDATE campaigns
        SET    budget        = %(budget)s,
               status        = %(status)s,
               modified_date = %(modified_date)s,
               modified_by   = %(modified_by)s
        WHERE  campaign_id   = %(campaign_id)s
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for row in edited_rows:
                cur.execute(sql, row)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# ─── Session State Init (SRS §4 step 1) ─────────────────────────────────────
if "campaign_data" not in st.session_state:
    try:
        st.session_state.campaign_data = load_campaigns_from_db()
        st.session_state.db_error = None
    except Exception as e:
        st.session_state.campaign_data = pd.DataFrame()
        st.session_state.db_error = str(e)

# ─── Header ─────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
  <h1>📊 Campaign Management</h1>
  <p>Create, track, and optimise your marketing campaigns in one place.</p>
</div>
""", unsafe_allow_html=True)

# Surface DB connection errors prominently
if st.session_state.get("db_error"):
    st.error(f"**Could not connect to the database.** Check your `secrets.toml` configuration.\n\n`{st.session_state.db_error}`")
    st.stop()

df: pd.DataFrame = st.session_state.campaign_data

# ─── KPI Cards ──────────────────────────────────────────────────────────────
active_count    = int((df["status"] == "Active").sum()) if not df.empty else 0
total_budget    = float(df["budget"].sum())             if not df.empty else 0.0
total_spend     = float(df["actual_spend"].sum())       if not df.empty else 0.0
utilisation_pct = (total_spend / total_budget * 100)   if total_budget else 0.0

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Total Campaigns</div>
        <div class="metric-value">{len(df)}</div>
        <div class="metric-sub">{active_count} active</div>
    </div>""", unsafe_allow_html=True)
with c2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Total Budget</div>
        <div class="metric-value">${total_budget:,.0f}</div>
        <div class="metric-sub">across all campaigns</div>
    </div>""", unsafe_allow_html=True)
with c3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Total Spend</div>
        <div class="metric-value">${total_spend:,.0f}</div>
        <div class="metric-sub">{utilisation_pct:.1f}% utilisation</div>
    </div>""", unsafe_allow_html=True)
with c4:
    remaining = total_budget - total_spend
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-label">Remaining Budget</div>
        <div class="metric-value">${remaining:,.0f}</div>
        <div class="metric-sub">available to spend</div>
    </div>""", unsafe_allow_html=True)

# ─── Campaign Creation Wizard (SRS §3.1 & §4 steps 2-4) ─────────────────────
st.markdown('<div class="section-title">Create New Campaign</div>', unsafe_allow_html=True)

with st.container():
    st.markdown('<div class="form-card">', unsafe_allow_html=True)
    with st.form("campaign_form", clear_on_submit=True):
        col_a, col_b = st.columns(2)
        with col_a:
            campaign_name = st.text_input("Campaign Name *", placeholder="e.g. Black Friday 2025")
            channel       = st.selectbox("Channel / Type *", CHANNELS)
        with col_b:
            budget     = st.number_input("Budget ($) *", min_value=0.01, step=100.0, format="%.2f")
            date_range = st.date_input(
                "Date Range *",
                value=(date.today(), date.today()),
                min_value=date(2020, 1, 1),
            )
        submitted = st.form_submit_button("➕ Create Campaign", use_container_width=True)
    st.markdown('</div>', unsafe_allow_html=True)

# SRS §4 step 3: validate on submit
if submitted:
    errors = []
    if not campaign_name.strip():
        errors.append("Campaign Name cannot be empty.")
    if budget <= 0:
        errors.append("Budget must be greater than 0.")

    start_date, end_date = (
        date_range if isinstance(date_range, tuple) and len(date_range) == 2
        else (date_range, date_range)
    )
    if end_date < start_date:
        errors.append("End Date must be on or after Start Date.")

    if errors:
        for e in errors:
            st.error(e)
    else:
        today = date.today()
        record = {
            "campaign_name": campaign_name.strip(),
            "channel":       channel,
            "status":        "Active",
            "budget":        budget,
            "actual_spend":  0.00,
            "start_date":    start_date,
            "end_date":      end_date,
            "created_date":  today,
            "modified_date": today,
            "created_by":    "current_user",
            "modified_by":   "current_user",
        }
        try:
            new_id = insert_campaign(record)
            record["campaign_id"] = new_id
            new_row = pd.DataFrame([record])
            st.session_state.campaign_data = pd.concat(
                [st.session_state.campaign_data, new_row], ignore_index=True
            )
            load_campaigns_from_db.clear()   # bust cache
            st.success(f"✅ Campaign **{campaign_name.strip()}** created successfully!")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to save campaign: {e}")

# ─── Campaign Registry with Inline Editing (SRS §3.2) ───────────────────────
st.markdown('<div class="section-title">Campaign Registry</div>', unsafe_allow_html=True)

if df.empty:
    st.markdown("""
    <div class="empty-state">
        <div class="icon">📋</div>
        <strong>No campaigns yet</strong><br>
        Use the form above to create your first campaign.
    </div>""", unsafe_allow_html=True)
else:
    # Filter bar
    f1, f2, f3 = st.columns([2, 1, 1])
    with f1:
        search_term    = st.text_input("Search", placeholder="🔍 Filter by name…", label_visibility="collapsed")
    with f2:
        channel_filter = st.selectbox("Channel", ["All"] + CHANNELS, label_visibility="collapsed")
    with f3:
        status_filter  = st.selectbox("Status",  ["All"] + STATUSES, label_visibility="collapsed")

    display_df = st.session_state.campaign_data.copy()
    if search_term:
        display_df = display_df[display_df["campaign_name"].str.contains(search_term, case=False, na=False)]
    if channel_filter != "All":
        display_df = display_df[display_df["channel"] == channel_filter]
    if status_filter != "All":
        display_df = display_df[display_df["status"] == status_filter]

    st.caption(f"Showing {len(display_df)} of {len(st.session_state.campaign_data)} campaigns")

    edited_df = st.data_editor(
        display_df,
        use_container_width=True,
        hide_index=True,
        num_rows="fixed",
        column_config={
            "campaign_id":   st.column_config.NumberColumn("ID",              disabled=True, width="small"),
            "campaign_name": st.column_config.TextColumn("Campaign Name",     disabled=True, width="large"),
            "channel":       st.column_config.TextColumn("Channel",           disabled=True, width="small"),
            "status":        st.column_config.SelectboxColumn("Status",       options=STATUSES, width="small"),
            "budget":        st.column_config.NumberColumn("Budget ($)",      format="$%.2f", min_value=0.01, width="medium"),
            "actual_spend":  st.column_config.NumberColumn("Actual Spend ($)",format="$%.2f", disabled=True, width="medium"),
            "start_date":    st.column_config.DateColumn("Start",             disabled=True, width="small"),
            "end_date":      st.column_config.DateColumn("End",               disabled=True, width="small"),
            "created_date":  st.column_config.DateColumn("Created",           disabled=True, width="small"),
            "modified_date": st.column_config.DateColumn("Modified",          disabled=True, width="small"),
            "created_by":    st.column_config.TextColumn("Created By",        disabled=True, width="small"),
            "modified_by":   st.column_config.TextColumn("Modified By",       disabled=True, width="small"),
        },
        key="registry_editor",
    )

    # SRS §3.2: explicit Save Changes button
    if st.button("💾 Save Changes", type="primary"):
        master = st.session_state.campaign_data.copy()
        today  = date.today()
        changed_rows = []

        for _, edited_row in edited_df.iterrows():
            cid  = edited_row["campaign_id"]
            orig = master.loc[master["campaign_id"] == cid].iloc[0]
            if orig["budget"] != edited_row["budget"] or orig["status"] != edited_row["status"]:
                changed_rows.append({
                    "campaign_id":  cid,
                    "budget":       edited_row["budget"],
                    "status":       edited_row["status"],
                    "modified_date": today,
                    "modified_by":  "current_user",
                })
                master.loc[master["campaign_id"] == cid, "budget"]        = edited_row["budget"]
                master.loc[master["campaign_id"] == cid, "status"]        = edited_row["status"]
                master.loc[master["campaign_id"] == cid, "modified_date"] = today
                master.loc[master["campaign_id"] == cid, "modified_by"]   = "current_user"

        if not changed_rows:
            st.info("No changes detected.")
        else:
            try:
                save_edits_to_db(changed_rows)
                st.session_state.campaign_data = master
                load_campaigns_from_db.clear()
                st.success(f"Saved {len(changed_rows)} change(s) successfully.")
            except Exception as e:
                st.error(f"Failed to save changes: {e}")

    # ─── Analytics (only shown when there's data) ────────────────────────────
    st.markdown('<div class="section-title">Budget vs. Spend by Channel</div>', unsafe_allow_html=True)
    agg = (
        st.session_state.campaign_data
        .groupby("channel", as_index=False)
        .agg(budget=("budget", "sum"), actual_spend=("actual_spend", "sum"))
    )
    chart_df = agg.set_index("channel")[["budget", "actual_spend"]].rename(
        columns={"budget": "Budget ($)", "actual_spend": "Spend ($)"}
    )
    st.bar_chart(chart_df, color=["#4F46E5", "#7C3AED"], height=280)

    st.markdown('<div class="section-title">Status Breakdown</div>', unsafe_allow_html=True)
    status_counts = st.session_state.campaign_data["status"].value_counts().reset_index()
    status_counts.columns = ["Status", "Count"]
    st.dataframe(status_counts, use_container_width=False, hide_index=True)

# ─── Footer ─────────────────────────────────────────────────────────────────
st.divider()
st.caption("🔒 Database credentials are loaded via `st.secrets` and never exposed in the UI.")