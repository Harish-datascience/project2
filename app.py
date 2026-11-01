"""
app.py - Streamlit dashboard: Workforce Attrition Patterns and Risk Hotspot Analysis.
Run with:  streamlit run app.py
All calculations live in utils.py; this file only draws the page.
"""
import streamlit as st

import utils

DISCLAIMER = ("⚠️ Descriptive analysis only: these patterns are associations in this dataset "
              "and do not prove that any factor causes attrition.")


# ---------------------------------------------------------------- small helpers
@st.cache_data(show_spinner=False)
def load_cached():
    """Load + clean once; Streamlit reuses the result on every rerun.
    (If loading fails, the error is raised and nothing is cached.)"""
    return utils.load_and_prepare()


def disclaimer():
    st.caption(DISCLAIMER)


def show(fig, key):
    """Draw a Plotly chart. Every chart gets a unique key so Streamlit never confuses two charts."""
    st.plotly_chart(fig, key=key)


def reset_filters(defaults):
    """Button callback: put every filter back to its default value."""
    for key, value in defaults.items():
        st.session_state[key] = list(value) if isinstance(value, list) else value


# ---------------------------------------------------------------- sidebar
def build_sidebar(df):
    """Draw the filter widgets and return the filtered dataframe."""
    defaults = utils.filter_defaults(df)
    for key, value in defaults.items():  # first run only: start with "everything selected"
        st.session_state.setdefault(key, list(value) if isinstance(value, list) else value)

    st.sidebar.header("🔎 Filters")
    if "f_dept" in defaults:
        st.sidebar.multiselect("Department", defaults["f_dept"], key="f_dept")
    if "f_role" in defaults:
        st.sidebar.multiselect("Job Role", defaults["f_role"], key="f_role")
    if "f_age" in defaults:
        st.sidebar.multiselect("Age group", defaults["f_age"], key="f_age")
    if "f_tenure" in defaults and defaults["f_tenure"][0] < defaults["f_tenure"][1]:
        low, high = defaults["f_tenure"]
        st.sidebar.slider("Tenure (years at company)", low, high, key="f_tenure")
    if "f_overtime" in defaults:
        st.sidebar.radio("Overtime", ["All", "Yes", "No"], key="f_overtime", horizontal=True)
    if "f_travel" in defaults:
        st.sidebar.multiselect("Business Travel", defaults["f_travel"], key="f_travel",
                               format_func=lambda x: x.replace("_", " "))
    st.sidebar.button("↺ Reset filters", on_click=reset_filters, args=(defaults,))

    selection = {key: st.session_state[key] for key in defaults}
    filtered = utils.apply_filters(df, selection)
    st.sidebar.caption(f"Showing {len(filtered):,} of {len(df):,} employees")
    st.sidebar.download_button("⬇️ Download filtered CSV", filtered.to_csv(index=False).encode("utf-8"),
                               file_name="filtered_attrition_data.csv", mime="text/csv",
                               disabled=filtered.empty)
    return filtered


def show_data_overview(df, info):
    """Preview + validation box (shape, head, dtypes, nulls, duplicates)."""
    with st.expander("📄 Dataset preview and validation"):
        rows, cols = info["shape"]
        st.write(f"**Raw file:** {rows:,} rows × {cols} columns  |  **After cleaning:** "
                 f"{df.shape[0]:,} rows × {df.shape[1]} columns (includes derived columns)")
        st.write(f"**Duplicate rows found (dropped):** {info['duplicates']}  |  "
                 f"**Attrition values:** {info['attrition_values']}")
        if info["missing_optional"]:
            st.warning("Columns not found (their charts are skipped): " + ", ".join(info["missing_optional"]))
        st.dataframe(df.head(10))
        st.write("**Column types and null counts (raw file)**")
        st.dataframe(info["schema"])


# ---------------------------------------------------------------- reusable blocks
def render_kpis(df):
    k = utils.kpi_values(df)
    cards = [("Total Employees", f"{k['total']:,}"), ("Employees Left", f"{k['left']:,}"),
             ("Employees Retained", f"{k['retained']:,}"), ("Attrition %", f"{k['rate']:.1f}%")]
    for column, (label, value) in zip(st.columns(4), cards):
        with column:
            with st.container(border=True):
                st.metric(label, value)


def render_dimension(df, col, title, right, prefix):
    """Two charts for one column: attrition-rate bars (left) and counts or shares (right)."""
    if col not in df.columns:
        st.info(f"Skipped '{title}': the data needed for it is not in the dataset.")
        return
    st.subheader(title)
    left_box, right_box = st.columns(2)
    with left_box:
        show(utils.rate_bar(df, col, f"Attrition rate by {title}"), f"{prefix}_{col}_rate")
    with right_box:
        if right == "grouped":
            show(utils.grouped_count_chart(df, col, "Stayed vs Left (employees)"), f"{prefix}_{col}_grouped")
        else:
            show(utils.stacked_share_chart(df, col, "Stayed vs Left (% of group)"), f"{prefix}_{col}_stacked")


def show_top_groups(df, col, n, heading):
    """List the n highest-attrition groups of `col`, one sentence each."""
    st.markdown(f"**{heading}**")
    if col not in df.columns:
        st.info("Skipped: the needed column is not in the dataset.")
        return
    top = utils.hotspot_table(df, col).head(n)
    if top.empty:
        st.info(f"Not enough employees in the selection (groups need at least {utils.MIN_GROUP}).")
        return
    overall = utils.overall_rate(df)
    for _, row in top.iterrows():
        icon = "🔴" if row["Status"] == utils.HOT else "⚪"
        st.markdown(f"- {icon} {utils.group_sentence(row, overall)}")


def bullet_list(lines):
    for line in lines:
        st.markdown(f"- {line}")


# ---------------------------------------------------------------- the tabs (modules)
def tab_overview(df):
    disclaimer()
    render_kpis(df)
    left_box, right_box = st.columns(2)
    with left_box:
        show(utils.donut_chart(df), "overview_donut")
    with right_box:
        if "Department" in df.columns:
            show(utils.rate_bar(df, "Department", "Attrition rate by department"), "overview_dept")
        else:
            st.info("Department chart skipped: 'Department' column not found.")
    st.subheader("Key observations")
    sentences = utils.build_sentences(utils.compute_findings(df))
    bullet_list([sentences[k] for k in ("overall", "dept", "role", "overtime", "age") if k in sentences])


def tab_dept_role(df):
    disclaimer()
    if "Department" in df.columns:
        st.subheader("Department headcount and attrition rate")
        left_box, right_box = st.columns(2)
        with left_box:
            show(utils.grouped_count_chart(df, "Department", "Headcount: Stayed vs Left"), "dept_grouped")
        with right_box:
            show(utils.rate_bar(df, "Department", "Attrition rate by department"), "dept_rate")
        show_top_groups(df, "Department", 2, "Top-2 departments by attrition rate")
        st.dataframe(utils.summary_table(df, "Department", "Department"), hide_index=True)
    else:
        st.info("Department section skipped: 'Department' column not found.")
    if "JobRole" in df.columns:
        st.subheader("Job role attrition rate")
        show(utils.rate_bar(df, "JobRole", "Attrition rate by job role", horizontal=True, sort_by_rate=True),
             "role_rate")
        show_top_groups(df, "JobRole", 2, "Top-2 job roles by attrition rate")
    else:
        st.info("Job role section skipped: 'JobRole' column not found.")


def tab_demographics(df):
    disclaimer()
    for col, title in [("AgeGroup", "Age group"), ("Gender", "Gender"),
                       ("MaritalStatus", "Marital status"), ("EducationField", "Education field")]:
        render_dimension(df, col, title, "grouped", "demo")


def tab_tenure(df):
    disclaimer()
    st.caption("Bands: '10+' means more than 10 years; '20+' means more than 20 years; '8+' means 8 or more years.")
    for col, title in [("TenureBand", "Years at company"), ("TotalWorkingYearsBand", "Total working years"),
                       ("PromotionBand", "Years since last promotion")]:
        render_dimension(df, col, title, "stacked", "tenure")


def tab_workload(df):
    disclaimer()
    for col, title in [("OverTime", "Overtime"), ("BusinessTravel", "Business travel"),
                       ("DistanceBucket", "Distance from home"),
                       ("JobSatisfaction", "Job satisfaction (score 1-4)"),
                       ("WorkLifeBalance", "Work-life balance (score 1-4)")]:
        render_dimension(df, col, title, "stacked", "work")


def tab_hotspots(df):
    st.warning(DISCLAIMER)
    overall = utils.overall_rate(df)
    st.markdown(f"**Rule:** a category is flagged 🔴 when its attrition rate is above "
                f"{utils.HOTSPOT_FACTOR}x the overall rate ({overall:.1f}% → threshold "
                f"{overall * utils.HOTSPOT_FACTOR:.1f}%). Groups with fewer than {utils.MIN_GROUP} "
                f"employees are not ranked because small numbers are unreliable. ⚪ = not above threshold.")
    show_top_groups(df, "Department", 3, "Top 3 departments")
    show_top_groups(df, "JobRole", 3, "Top 3 job roles")
    show_top_groups(df, "TenureBand", 1, "Highest-risk tenure band (years at company)")
    sentences = utils.build_sentences(utils.compute_findings(df))
    st.markdown("**Overtime gap**")
    st.markdown(f"- {sentences.get('overtime', 'Not enough data for an overtime comparison.')}")
    st.markdown("**Business-travel gap**")
    st.markdown(f"- {sentences.get('travel', 'Not enough data for a travel comparison.')}")


def tab_insights(df):
    st.warning(DISCLAIMER)
    findings = utils.compute_findings(df)
    sentences = utils.build_sentences(findings)
    st.subheader("Key insights")
    bullet_list([sentences[k] for k in ("dept", "role", "overtime", "tenure", "age") if k in sentences])
    st.subheader("HR recommendations")
    recs = utils.make_recommendations(findings)
    if recs:
        bullet_list(recs)
    else:
        st.info("Not enough data in the current selection to make recommendations.")
    st.caption("Recommendations are starting points for further investigation, not proven fixes.")


# ---------------------------------------------------------------- main
def main():
    st.set_page_config(page_title="Workforce Attrition Analysis", page_icon="📊", layout="wide")
    st.title("📊 Workforce Attrition Patterns and Risk Hotspot Analysis")
    st.caption("Palo Alto Networks workforce dataset · descriptive analysis")

    try:
        df, info = load_cached()
    except utils.DataLoadError as error:  # friendly banner instead of a traceback
        st.error(f"⚠️ {error}")
        st.stop()

    show_data_overview(df, info)
    filtered = build_sidebar(df)
    if filtered.empty:
        st.warning("No data matches filters. Change the filters or press 'Reset filters' in the sidebar.")
        st.stop()

    tabs = st.tabs(["Overview", "Department & Role", "Demographics", "Tenure & Career",
                    "Workload & Satisfaction", "Risk Hotspots", "Insights"])
    for tab, draw in zip(tabs, [tab_overview, tab_dept_role, tab_demographics, tab_tenure,
                                tab_workload, tab_hotspots, tab_insights]):
        with tab:
            draw(filtered)


main()
