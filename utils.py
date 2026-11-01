"""
utils.py - helper functions for the Workforce Attrition dashboard.

There is no Streamlit code in this file, so every function can be tested on
its own. Sections:
  1. Constants          5. Filtering
  2. Loading            6. Attrition-rate helpers
  3. Cleaning           7. Hotspots, findings and sentences
  4. Feature bands      8. Chart builders (Plotly)
"""
import os

import numpy as np
import pandas as pd
import plotly.express as px

# ----------------------------------------------------------------------------
# 1. CONSTANTS
# ----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# The first path is the one required by the project; the second is a fallback
# in case the file was saved with underscores instead of spaces.
DATA_CANDIDATES = [
    os.path.join(BASE_DIR, "data", "Palo Alto Networks.csv"),
    os.path.join(BASE_DIR, "data", "Palo_Alto_Networks.csv"),
]

REQUIRED_COLUMNS = ["Attrition"]  # the app cannot work without this one
# Optional columns: if one is missing, only the charts that need it are skipped.
OPTIONAL_COLUMNS = [
    "Age", "Gender", "MaritalStatus", "EducationField", "Department", "JobRole",
    "OverTime", "BusinessTravel", "DistanceFromHome", "JobSatisfaction",
    "WorkLifeBalance", "YearsAtCompany", "TotalWorkingYears",
    "YearsSinceLastPromotion",
]

HOTSPOT_FACTOR = 1.25  # hotspot rule: rate > overall rate * 1.25
MIN_GROUP = 10         # groups smaller than this are too noisy to rank/flag

# Different spellings of the Attrition column that we accept
ATTRITION_MAP = {"1": "Left", "1.0": "Left", "yes": "Left", "true": "Left",
                 "0": "Stayed", "0.0": "Stayed", "no": "Stayed", "false": "Stayed"}

# (new column, source column, bin edges, labels, right-closed?)
BAND_RULES = [
    ("AgeGroup", "Age", [0, 25, 35, 45, 55, np.inf], ["<25", "25-34", "35-44", "45-54", "55+"], False),
    ("TenureBand", "YearsAtCompany", [-1, 2, 5, 10, np.inf], ["0-2", "3-5", "6-10", "10+"], True),
    ("TotalWorkingYearsBand", "TotalWorkingYears", [-1, 5, 10, 20, np.inf], ["0-5", "6-10", "11-20", "20+"], True),
    ("PromotionBand", "YearsSinceLastPromotion", [-1, 1, 3, 7, np.inf], ["0-1", "2-3", "4-7", "8+"], True),
    ("DistanceBucket", "DistanceFromHome", [-1, 5, 10, 20, np.inf], ["0-5", "6-10", "11-20", "21+"], True),
]

HOT = f"Hotspot (>{HOTSPOT_FACTOR}x overall)"
OK = "Within normal range"
SMALL = f"Small group (n<{MIN_GROUP})"
RISK_COLORS = {HOT: "#ff6b6b", OK: "#4da3ff", SMALL: "#8a94a8"}
LEFT_COLORS = {"Stayed": "#4da3ff", "Left": "#ff6b6b"}


# ----------------------------------------------------------------------------
# 2. LOADING
# ----------------------------------------------------------------------------
class DataLoadError(Exception):
    """Raised for any loading/validation problem; the app shows it as a friendly banner."""


def find_data_file():
    """Return the first existing CSV path, or None."""
    for path in DATA_CANDIDATES:
        if os.path.isfile(path):
            return path
    return None


def inspect_dataset(df):
    """Collect the facts shown in the 'dataset preview' box (shape, dtypes, nulls, duplicates)."""
    attrition_values = []
    if "Attrition" in df.columns:
        attrition_values = sorted(df["Attrition"].dropna().unique().tolist(), key=str)
    return {
        "shape": df.shape,
        "schema": pd.DataFrame({"dtype": df.dtypes.astype(str), "null_count": df.isnull().sum()}),
        "duplicates": int(df.duplicated().sum()),
        "attrition_values": attrition_values,
    }


def load_and_prepare():
    """Load the CSV, validate it, clean it, add feature columns. Returns (dataframe, info)."""
    path = find_data_file()
    if path is None:
        raise DataLoadError("Data file not found. Please place your CSV at "
                            "'data/Palo Alto Networks.csv' (inside the project folder, next to app.py).")
    try:
        raw = pd.read_csv(path)
    except (OSError, ValueError):  # missing permission, empty file, broken CSV, bad encoding
        raise DataLoadError("The CSV file exists but could not be read. Please check that it is a valid CSV.")
    raw.columns = raw.columns.str.strip()  # remove accidental spaces in headers

    missing = [c for c in REQUIRED_COLUMNS if c not in raw.columns]
    if missing:
        raise DataLoadError(f"Required column(s) missing from the CSV: {', '.join(missing)}.")

    info = inspect_dataset(raw)
    info["missing_optional"] = [c for c in OPTIONAL_COLUMNS if c not in raw.columns]
    df = add_features(clean_data(raw))
    info["rows_after_cleaning"] = len(df)
    return df, info


# ----------------------------------------------------------------------------
# 3. CLEANING
# ----------------------------------------------------------------------------
def clean_data(df):
    """Drop duplicates, add Stayed/Left labels, fill nulls.

    Null rules (also in README):
      - rows with an unknown Attrition value are dropped (they cannot be counted),
      - numeric columns -> filled with the median,
      - text columns    -> filled with the most common value.
    """
    df = df.drop_duplicates().copy()

    # Derived columns; the original 0/1 "Attrition" column is kept untouched.
    text = df["Attrition"].astype(str).str.strip().str.lower()
    df["AttritionStatus"] = text.map(ATTRITION_MAP)
    df = df.dropna(subset=["AttritionStatus"]).copy()
    if df.empty:
        raise DataLoadError("The Attrition column has no usable values (expected 0/1 or Yes/No).")
    df["LeftFlag"] = (df["AttritionStatus"] == "Left").astype(int)  # 1 = left, used for rate maths
    df["AttritionStatus"] = pd.Categorical(df["AttritionStatus"], categories=["Stayed", "Left"], ordered=True)

    for col in df.columns:
        if col in ("AttritionStatus", "LeftFlag") or not df[col].isnull().any():
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            df[col] = df[col].fillna(df[col].median())
        else:
            mode = df[col].mode()
            df[col] = df[col].fillna(mode.iloc[0] if len(mode) else "Unknown")
    return df.reset_index(drop=True)


# ----------------------------------------------------------------------------
# 4. FEATURE BANDS
# ----------------------------------------------------------------------------
def add_features(df):
    """Create band columns from BAND_RULES (only when the source column exists)."""
    df = df.copy()
    for new_col, source, bins, labels, right in BAND_RULES:
        if source in df.columns:
            df[new_col] = pd.cut(df[source], bins=bins, labels=labels, right=right)
    return df


# ----------------------------------------------------------------------------
# 5. FILTERING
# ----------------------------------------------------------------------------
# Sidebar widget key -> dataframe column
FILTER_COLUMNS = {"f_dept": "Department", "f_role": "JobRole", "f_age": "AgeGroup", "f_travel": "BusinessTravel"}


def filter_defaults(df):
    """Default value of every filter that can be built from this dataset.
    For multiselects the default (= all options) is also the option list."""
    d = {}
    for key, col in FILTER_COLUMNS.items():
        if col in df.columns:
            if col == "AgeGroup":  # keep natural order (<25, 25-34, ...)
                d[key] = [str(a) for a in df[col].cat.categories if (df[col] == a).any()]
            else:
                d[key] = sorted(df[col].dropna().unique().tolist())
    if "YearsAtCompany" in df.columns:
        d["f_tenure"] = (int(df["YearsAtCompany"].min()), int(df["YearsAtCompany"].max()))
    if "OverTime" in df.columns:
        d["f_overtime"] = "All"
    return d


def apply_filters(df, sel):
    """Return only the rows that match every selected filter (sel = widget values)."""
    mask = pd.Series(True, index=df.index)
    for key, col in FILTER_COLUMNS.items():
        if key in sel and col in df.columns:
            mask &= df[col].isin(sel[key])
    if "f_tenure" in sel and "YearsAtCompany" in df.columns:
        low, high = sel["f_tenure"]
        mask &= df["YearsAtCompany"].between(low, high)
    if sel.get("f_overtime") in ("Yes", "No") and "OverTime" in df.columns:
        mask &= df["OverTime"] == sel["f_overtime"]
    return df[mask]


# ----------------------------------------------------------------------------
# 6. ATTRITION-RATE HELPERS
# ----------------------------------------------------------------------------
def kpi_values(df):
    """Numbers for the four KPI cards."""
    total = len(df)
    left = int(df["LeftFlag"].sum())
    return {"total": total, "left": left, "retained": total - left,
            "rate": left / total * 100 if total else 0.0}


def overall_rate(df):
    """Attrition % of the dataframe (0 when empty)."""
    return float(df["LeftFlag"].mean() * 100) if len(df) else 0.0


def clean_label(series):
    """Turn values into display text, e.g. 'Travel_Rarely' -> 'Travel Rarely'."""
    return series.astype(str).str.replace("_", " ", regex=False)


def attrition_table(df, col):
    """One row per category of `col`: Headcount, Left (count) and AttritionRate (%)."""
    g = df.groupby(col, observed=True)["LeftFlag"].agg(Headcount="size", Left="sum").reset_index()
    g["AttritionRate"] = g["Left"] / g["Headcount"] * 100
    g["Label"] = clean_label(g[col])
    return g


def status_counts(df, col):
    """Counts of Stayed / Left per category, plus each status as % of its category."""
    c = df.groupby([col, "AttritionStatus"], observed=True).size().reset_index(name="Count")
    c["Share"] = c["Count"] / c.groupby(col, observed=True)["Count"].transform("sum") * 100
    c["Label"] = clean_label(c[col])
    return c


def add_risk_status(t, overall):
    """Label each row Hotspot / Within normal range / Small group using the 1.25x rule."""
    t = t.copy()
    conditions = [t["Headcount"] < MIN_GROUP, t["AttritionRate"] > overall * HOTSPOT_FACTOR]
    t["Status"] = np.select(conditions, [SMALL, HOT], default=OK)
    return t


def summary_table(df, col, name):
    """Small tidy table for st.dataframe."""
    t = attrition_table(df, col)[["Label", "Headcount", "Left", "AttritionRate"]]
    t = t.rename(columns={"Label": name, "Left": "Employees Left", "AttritionRate": "Attrition %"})
    t["Attrition %"] = t["Attrition %"].round(1)
    return t


# ----------------------------------------------------------------------------
# 7. HOTSPOTS, FINDINGS AND SENTENCES
# ----------------------------------------------------------------------------
def hotspot_table(df, col):
    """Groups of `col` (size >= MIN_GROUP) ranked by attrition rate, highest first."""
    overall = overall_rate(df)
    t = add_risk_status(attrition_table(df, col), overall)
    t = t[t["Headcount"] >= MIN_GROUP].copy()
    t["VsOverall"] = t["AttritionRate"] / overall if overall > 0 else np.nan
    return t.sort_values("AttritionRate", ascending=False).reset_index(drop=True)


def group_sentence(row, overall):
    """One sentence + numbers for a group (a row of hotspot_table)."""
    text = (f"{row['Label']}: {row['AttritionRate']:.1f}% attrition "
            f"({int(row['Left'])} of {int(row['Headcount'])} employees)")
    if pd.notna(row["VsOverall"]):
        text += f", {row['VsOverall']:.2f}x the overall rate of {overall:.1f}%"
    return text + "."


def overtime_gap(df):
    """Attrition % with vs without overtime, or None if either group is too small."""
    if "OverTime" not in df.columns:
        return None
    yes, no = df[df["OverTime"] == "Yes"], df[df["OverTime"] == "No"]
    if len(yes) < MIN_GROUP or len(no) < MIN_GROUP:
        return None
    a, b = overall_rate(yes), overall_rate(no)
    return {"yes": a, "no": b, "gap": a - b}


def travel_gap(df):
    """Highest vs lowest attrition among business-travel categories (groups >= MIN_GROUP)."""
    if "BusinessTravel" not in df.columns:
        return None
    t = attrition_table(df, "BusinessTravel")
    t = t[t["Headcount"] >= MIN_GROUP]
    if len(t) < 2:
        return None
    hi, lo = t.loc[t["AttritionRate"].idxmax()], t.loc[t["AttritionRate"].idxmin()]
    return {"hi_label": hi["Label"], "hi_rate": hi["AttritionRate"], "lo_label": lo["Label"],
            "lo_rate": lo["AttritionRate"], "gap": hi["AttritionRate"] - lo["AttritionRate"]}


def compute_findings(df):
    """Compute every number used by observations, hotspots, insights and recommendations."""
    f = {"overall": overall_rate(df), "n": len(df), "left": int(df["LeftFlag"].sum())}
    for key, col in [("dept", "Department"), ("role", "JobRole"), ("age", "AgeGroup"), ("tenure", "TenureBand")]:
        top = hotspot_table(df, col) if col in df.columns else pd.DataFrame()
        f[key] = top.iloc[0].to_dict() if len(top) else None  # highest-attrition group
    f["overtime"] = overtime_gap(df)
    f["travel"] = travel_gap(df)
    return f


def build_sentences(f):
    """Turn findings into sentences. A sentence is only created if its numbers exist."""
    s = {"overall": f"Overall attrition in the current selection is {f['overall']:.1f}% "
                    f"({f['left']} of {f['n']} employees left)."}
    templates = {
        "dept": "{L} has the highest attrition among departments at {r:.1f}% ({l} of {n} employees).",
        "role": "{L} has the highest attrition among job roles at {r:.1f}% ({l} of {n} employees).",
        "age": "The {L} age group has the highest attrition at {r:.1f}% ({l} of {n} employees).",
        "tenure": "The {L} years-at-company band has the highest attrition at {r:.1f}% ({l} of {n} employees).",
    }
    for key, tpl in templates.items():
        g = f.get(key)
        if g:
            s[key] = tpl.format(L=g["Label"], r=g["AttritionRate"], l=int(g["Left"]), n=int(g["Headcount"]))
    o = f.get("overtime")
    if o:
        s["overtime"] = (f"Employees working overtime left at {o['yes']:.1f}% versus {o['no']:.1f}% for those "
                         f"who did not, a difference of {o['gap']:+.1f} percentage points.")
    t = f.get("travel")
    if t:
        s["travel"] = (f"{t['hi_label']} employees left at {t['hi_rate']:.1f}% versus {t['lo_rate']:.1f}% for "
                       f"{t['lo_label']} employees, a gap of {t['gap']:.1f} percentage points.")
    return s


def make_recommendations(f):
    """Up to 5 HR suggestions; each one quotes a computed number (nothing invented)."""
    recs = []
    o, t = f.get("overtime"), f.get("travel")
    if o and o["gap"] > 0:
        recs.append(f"Review how overtime is assigned: employees with overtime left at {o['yes']:.1f}% "
                    f"versus {o['no']:.1f}% without it.")
    if f.get("dept"):
        d = f["dept"]
        recs.append(f"Hold retention check-ins in {d['Label']}, where attrition is {d['AttritionRate']:.1f}% "
                    f"against {f['overall']:.1f}% overall.")
    if f.get("role"):
        r = f["role"]
        recs.append(f"Look at workload and growth paths for {r['Label']} ({int(r['Left'])} of "
                    f"{int(r['Headcount'])} employees left).")
    if f.get("tenure"):
        recs.append(f"Add mentoring or check-ins for the {f['tenure']['Label']} years-at-company band "
                    f"({f['tenure']['AttritionRate']:.1f}% attrition).")
    if f.get("age"):
        recs.append(f"Run stay-interviews with the {f['age']['Label']} age group "
                    f"({f['age']['AttritionRate']:.1f}% attrition) to learn what they need.")
    if t and t["gap"] > 0:
        recs.append(f"Check travel load: {t['hi_label']} employees left at {t['hi_rate']:.1f}% "
                    f"versus {t['lo_rate']:.1f}% for {t['lo_label']}.")
    return recs[:5]


# ----------------------------------------------------------------------------
# 8. CHART BUILDERS (Plotly)
# ----------------------------------------------------------------------------
def donut_chart(df):
    """Attrition vs retention donut."""
    counts = df["AttritionStatus"].value_counts()
    data = pd.DataFrame({"Status": ["Stayed", "Left"],
                         "Count": [int(counts.get("Stayed", 0)), int(counts.get("Left", 0))]})
    fig = px.pie(data, names="Status", values="Count", hole=0.55, color="Status",
                 color_discrete_map=LEFT_COLORS, title="Attrition vs Retention")
    fig.update_traces(textinfo="percent+value")
    return fig


def rate_bar(df, col, title, horizontal=False, sort_by_rate=False):
    """Attrition-rate bar chart. Bars are coloured by risk status and a dashed
    line marks the overall rate. Set horizontal=True for long labels."""
    overall = overall_rate(df)
    t = add_risk_status(attrition_table(df, col), overall)
    t["AttritionRate"] = t["AttritionRate"].round(1)
    if sort_by_rate:
        # horizontal charts draw the first row at the bottom, so sort ascending to get the highest on top
        t = t.sort_values("AttritionRate", ascending=horizontal)
    top = float(t["AttritionRate"].max()) if len(t) else 0.0
    limit = max(top, overall, 1) * 1.25  # head-room for the value labels
    options = dict(color="Status", color_discrete_map=RISK_COLORS, text="AttritionRate",
                   hover_data=["Headcount", "Left"], title=title,
                   category_orders={"Label": t["Label"].tolist(), "Status": [HOT, OK, SMALL]})
    note = f"Overall {overall:.1f}%"
    if horizontal:
        fig = px.bar(t, x="AttritionRate", y="Label", orientation="h", **options)
        fig.add_vline(x=overall, line_dash="dash", annotation_text=note)
        fig.update_xaxes(title="Attrition rate (%)", range=[0, limit])
        fig.update_yaxes(title="", type="category")
    else:
        fig = px.bar(t, x="Label", y="AttritionRate", **options)
        fig.add_hline(y=overall, line_dash="dash", annotation_text=note)
        fig.update_yaxes(title="Attrition rate (%)", range=[0, limit])
        fig.update_xaxes(title="", type="category")
    fig.update_traces(texttemplate="%{text:.1f}%", textposition="outside", cliponaxis=False)
    fig.update_layout(legend_title_text="", legend=dict(orientation="h", y=-0.25))
    return fig


def grouped_count_chart(df, col, title):
    """Grouped bars: number of Stayed vs Left employees in each category."""
    c = status_counts(df, col)
    order = attrition_table(df, col)["Label"].tolist()
    fig = px.bar(c, x="Label", y="Count", color="AttritionStatus", barmode="group", text="Count",
                 color_discrete_map=LEFT_COLORS, title=title,
                 category_orders={"Label": order, "AttritionStatus": ["Stayed", "Left"]})
    fig.update_xaxes(title="", type="category")
    fig.update_yaxes(title="Employees")
    fig.update_layout(legend_title_text="")
    return fig


def stacked_share_chart(df, col, title):
    """100%-stacked bars: share of Stayed vs Left inside each category."""
    c = status_counts(df, col)
    order = attrition_table(df, col)["Label"].tolist()
    fig = px.bar(c, x="Label", y="Share", color="AttritionStatus", barmode="stack", text="Share",
                 color_discrete_map=LEFT_COLORS, title=title,
                 category_orders={"Label": order, "AttritionStatus": ["Stayed", "Left"]})
    fig.update_traces(texttemplate="%{text:.1f}%")
    fig.update_xaxes(title="", type="category")
    fig.update_yaxes(title="% of group", range=[0, 100])
    fig.update_layout(legend_title_text="")
    return fig
