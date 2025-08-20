# app_streamlit.py
# Streamlit dashboard backed by SQLite with filter-aware queries + TRUE daily census occupancy.
# Place this file in the project root (next to schema.sql and data/).

from pathlib import Path
import sqlite3
import pandas as pd
import numpy as np
import streamlit as st
import plotly.express as px
from datetime import timedelta

# ---------- Paths & Constants ----------
BASE = Path(__file__).parent
DB_PATH = BASE / "hospital.db"
DATA_DIR = BASE / "data"
SCHEMA_PATH = BASE / "schema.sql"

st.set_page_config(page_title="Hospital Ops Dashboard", layout="wide")


# ---------- One-time bootstrap: create DB from CSVs if missing ----------
def ensure_db_exists():
    if DB_PATH.exists():
        return
    if not SCHEMA_PATH.exists():
        st.error("schema.sql not found. Please keep schema.sql next to this file.")
        st.stop()
    if not DATA_DIR.exists():
        st.error("data/ folder not found. Please include CSVs in data/.")
        st.stop()

    con = sqlite3.connect(DB_PATH.as_posix())
    try:
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            con.executescript(f.read())

        for name in ["patients", "units", "bed_capacity", "staff", "admissions"]:
            csv_path = DATA_DIR / f"{name}.csv"
            if not csv_path.exists():
                st.error(f"Missing {csv_path}.")
                st.stop()
            df = pd.read_csv(csv_path)
            df.to_sql(name, con, if_exists="append", index=False)
    finally:
        con.commit()
        con.close()


ensure_db_exists()


# ---------- DB helpers ----------
def get_con():
    return sqlite3.connect(DB_PATH.as_posix(), check_same_thread=False)


@st.cache_data(show_spinner=False)
def get_date_bounds():
    con = get_con()
    try:
        row = pd.read_sql(
            "SELECT MIN(date(admit_ts)) AS dmin, MAX(date(admit_ts)) AS dmax FROM admissions",
            con,
        ).iloc[0]
        dmin = pd.to_datetime(row["dmin"]).date()
        dmax = pd.to_datetime(row["dmax"]).date()
        return dmin, dmax
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def get_distinct_values():
    con = get_con()
    try:
        hospitals = pd.read_sql(
            "SELECT DISTINCT hospital FROM admissions ORDER BY hospital", con
        )["hospital"].tolist()
        units = pd.read_sql(
            "SELECT DISTINCT unit_id FROM admissions ORDER BY unit_id", con
        )["unit_id"].tolist()
        return hospitals, units
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def load_refs():
    con = get_con()
    try:
        units = pd.read_sql("SELECT * FROM units", con)
        beds = pd.read_sql("SELECT * FROM bed_capacity", con)
        staff = pd.read_sql("SELECT * FROM staff", con)
        return units, beds, staff
    finally:
        con.close()


@st.cache_data(show_spinner=False)
def load_admissions(date_from=None, date_to=None, hospital=None, unit=None):
    con = get_con()
    try:
        q = "SELECT * FROM admissions WHERE 1=1"
        params = []

        if date_from is not None:
            q += " AND date(admit_ts) >= date(?)"
            params.append(str(date_from))
        if date_to is not None:
            q += " AND date(admit_ts) <= date(?)"
            params.append(str(date_to))
        if hospital is not None and hospital != "All":
            q += " AND hospital = ?"
            params.append(hospital)
        if unit is not None and unit != "All":
            q += " AND unit_id = ?"
            params.append(unit)

        adm = pd.read_sql(q, con, params=params)
        adm["admit_ts"] = pd.to_datetime(adm["admit_ts"], errors="coerce")
        adm["discharge_ts"] = pd.to_datetime(adm["discharge_ts"], errors="coerce")
        return adm
    finally:
        con.close()


# ---------- TRUE daily census occupancy ----------
def compute_daily_true_occupancy(adm: pd.DataFrame, beds_ref: pd.DataFrame,
                                 date_start, date_end) -> pd.DataFrame:
    """
    Compute TRUE daily occupancy% using concurrent census:
    A patient counts on day D if admit_ts.date() <= D and discharge_ts.date() > D.
    Returns dataframe with columns: hospital, unit_id, date, census, staffed_beds, occ_pct.
    """
    if adm.empty:
        return pd.DataFrame(columns=["hospital","unit_id","date","census","staffed_beds","occ_pct"])

    # Work on dates (drop times for daily census)
    df = adm.copy()
    df["admit_d"] = df["admit_ts"].dt.date
    df["discharge_d"] = df["discharge_ts"].dt.date

    # Build list of dates in selected window
    days = pd.date_range(pd.to_datetime(date_start), pd.to_datetime(date_end), freq="D").date

    # For efficiency with moderate data: compute per (hospital, unit) then per day
    groups = []
    for (h, u), g in df.groupby(["hospital", "unit_id"]):
        # Sort not required but can help readability
        g = g[["admit_d","discharge_d"]]
        # For each day, count intervals where admit_d <= day < discharge_d
        # (discharge day not counted—patient leaves at some time that day)
        census_list = []
        for d in days:
            c = ((g["admit_d"] <= d) & (g["discharge_d"] > d)).sum()
            census_list.append({"hospital": h, "unit_id": u, "date": d, "census": int(c)})
        groups.append(pd.DataFrame(census_list))

    census = pd.concat(groups, ignore_index=True) if groups else pd.DataFrame()

    # Attach staffed beds, compute occ pct
    out = census.merge(beds_ref, on=["hospital","unit_id"], how="left")
    out.rename(columns={"baseline_staffed_beds": "staffed_beds"}, inplace=True)
    out["staffed_beds"] = out["staffed_beds"].fillna(0).astype(int)
    out["occ_pct"] = np.where(out["staffed_beds"] > 0,
                              (out["census"] / out["staffed_beds"]) * 100.0, np.nan)
    return out


# ---------- UI: Filters ----------
st.title("Hospital Resource Utilization Dashboard")

units_ref, beds_ref, staff_ref = load_refs()
date_min, date_max = get_date_bounds()
all_hospitals, all_units = get_distinct_values()

c1, c2, c3 = st.columns(3)
with c1:
    date_range = st.date_input("Date range", value=(date_min, date_max), min_value=date_min, max_value=date_max)
with c2:
    hospital = st.selectbox("Hospital", ["All"] + all_hospitals, index=0)
with c3:
    unit = st.selectbox("Unit", ["All"] + all_units, index=0)

# ---------- Data pull (filter-aware) ----------
adm = load_admissions(date_from=date_range[0], date_to=date_range[1], hospital=hospital, unit=unit)
st.caption(f"Filtered encounters: {len(adm):,}")

if len(adm) == 0:
    st.info("No encounters in the selected filters.")
    st.stop()

# ---------- KPIs ----------
adm = adm.copy()
adm["los_hours"] = (adm["discharge_ts"] - adm["admit_ts"]).dt.total_seconds() / 3600.0
avg_los = float(adm["los_hours"].mean()) if len(adm) else 0.0
admissions_per_day = adm.groupby(adm["admit_ts"].dt.date).size().mean() if len(adm) else 0.0

# Proxy occupancy (quick)
daily_arrivals = (
    adm.assign(date=adm["admit_ts"].dt.date)
    .groupby(["hospital","unit_id","date"])
    .size()
    .reset_index(name="arrivals")
)
occ_proxy = daily_arrivals.merge(beds_ref, on=["hospital","unit_id"], how="left")
occ_proxy["occ_proxy"] = (occ_proxy["arrivals"] / occ_proxy["baseline_staffed_beds"]).clip(upper=1.2)
avg_occ_proxy_pct = float(occ_proxy["occ_proxy"].mean() * 100) if len(occ_proxy) else 0.0

# TRUE daily census occupancy
true_occ = compute_daily_true_occupancy(adm, beds_ref, date_range[0], date_range[1])
avg_true_occ_pct = float(true_occ["occ_pct"].mean()) if len(true_occ) else 0.0

k1, k2, k3, k4 = st.columns(4)
k1.metric("Avg LOS (hrs)", f"{avg_los:.1f}")
k2.metric("Avg Admissions / Day", f"{admissions_per_day:.1f}")
k3.metric("Avg Occupancy (proxy)", f"{avg_occ_proxy_pct:.0f}%")
k4.metric("Avg TRUE Occupancy", f"{avg_true_occ_pct:.0f}%")

if avg_true_occ_pct >= 85:
    st.warning("⚠️ Bottleneck detected: average TRUE occupancy ≥ 85% in the selected period.")

st.divider()

# ---------- Charts ----------
# Admissions over time
ts = adm.groupby(adm["admit_ts"].dt.date).size().reset_index(name="admissions")
fig1 = px.line(ts, x="admit_ts", y="admissions", title="Admissions Over Time")
st.plotly_chart(fig1, use_container_width=True)

# Average LOS by unit
by_unit = adm.groupby("unit_id")["los_hours"].mean().reset_index()
fig2 = px.bar(by_unit, x="unit_id", y="los_hours", title="Average LOS by Unit")
st.plotly_chart(fig2, use_container_width=True)

# ED wait by triage (if ED present)
ed = adm.loc[adm["unit_id"].eq("ED")].dropna(subset=["wait_minutes"]).copy()
if len(ed) > 0:
    by_triage = ed.groupby("triage_level")["wait_minutes"].mean().reset_index()
    fig3 = px.bar(by_triage, x="triage_level", y="wait_minutes", title="ED Average Wait (mins) by Triage Level")
    st.plotly_chart(fig3, use_container_width=True)

# TRUE daily occupancy chart
if not true_occ.empty:
    # Aggregate to a single line (overall) OR show by unit/hospital for detail.
    # Here we plot overall mean TRUE occupancy per day across selected groups:
    true_daily = true_occ.groupby("date")["occ_pct"].mean().reset_index()
    fig4 = px.line(true_daily, x="date", y="occ_pct", title="Daily TRUE Occupancy % (Mean across selected units/hospitals)")
    st.plotly_chart(fig4, use_container_width=True)

    # Optional: uncomment to show a faceted chart by unit or hospital
    # fig4b = px.line(true_occ, x="date", y="occ_pct", color="unit_id", title="Daily TRUE Occupancy % by Unit")
    # st.plotly_chart(fig4b, use_container_width=True)

# ---------- Drill-down + export ----------
st.subheader("Drill-down (filtered encounters)")
cols = ["encounter_id","patient_id","hospital","unit_id","triage_level","admit_ts","discharge_ts","wait_minutes"]
st.dataframe(adm[cols].head(1000))

st.download_button(
    "Download filtered encounters (CSV)",
    data=adm.to_csv(index=False),
    file_name="filtered_encounters.csv",
)

# ---------- Caveats ----------
with st.expander("Data caveats & definitions"):
    st.markdown(
        """
- **TRUE Occupancy** computes daily concurrent census (count of active encounters per day) ÷ staffed beds.
  A patient counts on day *D* if `admit_ts.date() <= D` and `discharge_ts.date() > D`.
- **Proxy Occupancy** uses arrivals ÷ staffed beds for quick signal only.
- **LOS (hours)** = `discharge_ts - admit_ts`.
- **ED wait minutes** reflects triage-to-provider time; for wards, it's transfer lag.
- Data are **synthetic** for demonstration only.
"""
    )
