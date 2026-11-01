# Workforce Attrition Patterns and Risk Hotspot Analysis – Palo Alto Networks

A second-year college data-analytics project built with **Python, Pandas, NumPy, Plotly and Streamlit** only.
It is a **descriptive** analysis: it shows *patterns* in the data and never claims that one factor *causes* attrition.

## 1. Objective
Find which parts of the workforce have higher attrition and flag "risk hotspots":
departments, job roles, age groups, overtime, business travel, tenure/experience, job satisfaction and work-life balance.

## 2. Project structure
```
workforce_attrition/
    app.py              # Streamlit page: sidebar, 7 tabs, KPI cards
    utils.py            # loading, cleaning, filters, hotspot logic, Plotly charts
    requirements.txt
    README.md
    .streamlit/config.toml   # dark navy theme
    data/Palo Alto Networks.csv
```

## 3. Methodology
1. **Load** `data/Palo Alto Networks.csv`. A friendly red banner is shown if the file is missing or unreadable.
2. **Validate**: only `Attrition` is required. If any other column is missing, only the charts that need it are skipped.
3. **Clean**
   - Exact duplicate rows are dropped.
   - `Attrition` (0/1) is kept; a derived `AttritionStatus` ("Stayed"/"Left") and a numeric `LeftFlag` are added.
   - Nulls: rows with unknown `Attrition` are dropped; numeric nulls are filled with the **median**; text nulls with the **most common value**. (The supplied file has no nulls and no duplicates, so nothing was changed.)
4. **Feature bands** (written in `BAND_RULES` in `utils.py`)

| Column | Bands |
|---|---|
| AgeGroup | <25, 25-34, 35-44, 45-54, 55+ |
| TenureBand (YearsAtCompany) | 0-2, 3-5, 6-10, 10+ (10+ = more than 10) |
| TotalWorkingYearsBand | 0-5, 6-10, 11-20, 20+ (more than 20) |
| PromotionBand (YearsSinceLastPromotion) | 0-1, 2-3, 4-7, 8+ |
| DistanceBucket (DistanceFromHome) | 0-5, 6-10, 11-20, 21+ |

5. **Attrition rate** = employees who left ÷ employees in the group × 100.
6. **Hotspot rule**: a category is flagged when its attrition rate is **greater than 1.25 × the overall attrition rate**. Groups with **fewer than 10 employees are not ranked or flagged** (one or two leavers would make a tiny group look extreme). Both numbers are constants at the top of `utils.py`.
7. **Filters** (department, job role, age group, tenure slider, overtime, business travel) are applied to the dataframe first; every KPI, chart, table, hotspot and insight is then recomputed from the filtered data. If no rows match, the app shows "No data matches filters".
8. **Insights and recommendations** are built from computed numbers only; each sentence contains the number it is based on.

Charts used: vertical/horizontal bar, donut, grouped bar, 100%-stacked bar. No map is used. `MonthlyIncome` and the other unused columns are not analysed.

## 4. How to install
Python 3.9+ is recommended.
```
cd workforce_attrition
pip install -r requirements.txt
```

## 5. How to run
```
streamlit run app.py
```
The app opens at http://localhost:8501. The CSV must be at `data/Palo Alto Networks.csv`.

## 6. Limitations
- **Association, not causation.** Overtime, travel, age, etc. may be linked to attrition without causing it; other factors are not controlled for.
- Small groups give unstable percentages (see the minimum-size rule above).
- The file's columns match the public IBM HR Attrition dataset layout; results describe **this file only** and should not be presented as official company statistics.
- Satisfaction and work-life-balance scores are shown as 1-4 as stored in the file; the file has no data dictionary (higher = better is the usual coding of this dataset type).
- It is a single snapshot, so trends over time cannot be measured. No date fields are used.
- No predictive model is built (out of scope).

## 7. Conclusion
On the full, unfiltered file (1,470 employees, 237 left = 16.1% attrition), the highest rates appear in the Sales department (20.6%), the Sales Representative role (39.8%), employees under 25 (39.2%) and employees with 0-2 years at the company (29.8%). Employees with overtime left at 30.5% versus 10.4% without overtime. These are descriptive associations; the dashboard's Hotspots and Insights tabs recompute all of them for any filter selection.
