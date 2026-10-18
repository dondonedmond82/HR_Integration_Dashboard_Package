"""
HR Integration Dashboard
Adapted from the supplied housing_dashboard(2).py Panel template.

Run:
    pip install panel pandas openpyxl plotly numpy
    panel serve hr_integration_dashboard.py --show

Place Data_Set_Case_Study_Homework.xlsx in the same folder as this script,
or set HR_WORKBOOK to the workbook path in your environment.
"""
import os
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import panel as pn
import plotly.express as px
import plotly.graph_objects as go

warnings.filterwarnings("ignore")
pn.extension("plotly", "tabulator", sizing_mode="stretch_width")

APP_DIR = Path(__file__).resolve().parent
WORKBOOK_CANDIDATES = [
    Path(os.environ["HR_WORKBOOK"]) if os.environ.get("HR_WORKBOOK") else None,
    APP_DIR / "Data_Set_Case_Study_Homework.xlsx",
    APP_DIR / "Data_Set_Case_Study_Homework.xlsx",
    Path.cwd() / "Data_Set_Case_Study_Homework.xlsx",
    Path.cwd() / "Data_Set_Case_Study_Homework.xlsx",
]
WORKBOOK = next((p for p in WORKBOOK_CANDIDATES if p is not None and p.exists()), None)

EXPECTED_COLUMNS = [
    "Employee ID", "Data Effective Date", "Employee Status", "Career Level",
    "Hired Date", "Hired in FY", "Termination Date", "Terminated in FY",
    "Termination Type", "Job Start Date", "Promoted in FY", "Birth Date",
    "Age", "Tenure", "Time in Job", "Rating", "Education",
]
DATE_COLUMNS = ["Data Effective Date", "Hired Date", "Termination Date", "Job Start Date", "Birth Date"]
AS_OF_DATE = pd.Timestamp("2016-12-31")
UNIT_ORDER = ["Unit 1", "Unit 2"]


def _parse_date(series):
    """Parse datetime strings and Excel serial dates without treating ordinary years as serials."""
    raw = series.copy()
    parsed = pd.to_datetime(raw, errors="coerce")
    numeric = pd.to_numeric(raw, errors="coerce")
    mask = numeric.between(20000, 60000)
    if mask.any():
        parsed.loc[mask] = pd.to_datetime(numeric.loc[mask], unit="D", origin="1899-12-30", errors="coerce")
    return parsed


def load_unit(sheet_name):
    if WORKBOOK is None:
        raise FileNotFoundError(
            "HR workbook not found. Put Data_Set_Case_Study_Homework.xlsx beside this script "
            "or set the HR_WORKBOOK environment variable."
        )
    # The supplied workbook contains introductory rows before the employee table.
    raw = pd.read_excel(WORKBOOK, sheet_name=sheet_name, header=None, skiprows=3)
    if raw.empty:
        return pd.DataFrame(columns=EXPECTED_COLUMNS + ["Unit"])
    raw = raw.iloc[:, :len(EXPECTED_COLUMNS)].copy()
    raw.columns = EXPECTED_COLUMNS[:raw.shape[1]]
    for col in EXPECTED_COLUMNS:
        if col not in raw:
            raw[col] = np.nan
    raw = raw[EXPECTED_COLUMNS]
    raw = raw[raw["Employee ID"].notna()].copy()
    raw = raw[raw["Employee ID"].astype(str).str.strip().ne("Employee ID")]
    raw["Employee ID"] = raw["Employee ID"].astype(str).str.strip()

    for col in DATE_COLUMNS:
        raw[col] = _parse_date(raw[col])
    for col in ["Career Level", "Age", "Tenure", "Time in Job"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    for col in ["Employee Status", "Hired in FY", "Terminated in FY", "Termination Type",
                "Promoted in FY", "Rating", "Education"]:
        raw[col] = raw[col].astype("string").str.strip()

    # Resolve duplicate IDs conservatively: retain the row with the most valid dates.
    # Duplicate counts are separately reported as a data-quality issue.
    raw["_valid_dates"] = raw[DATE_COLUMNS].notna().sum(axis=1)
    duplicate_rows = int(raw["Employee ID"].duplicated(keep=False).sum())
    duplicate_ids = int(raw.loc[raw["Employee ID"].duplicated(keep=False), "Employee ID"].nunique())
    clean = (raw.sort_values("_valid_dates", ascending=False)
                 .drop_duplicates("Employee ID", keep="first")
                 .drop(columns="_valid_dates")
                 .copy())
    clean["Unit"] = sheet_name

    clean["Age (calculated)"] = ((AS_OF_DATE - clean["Birth Date"]).dt.days / 365.2425).round(1)
    clean["Tenure (calculated)"] = ((AS_OF_DATE - clean["Hired Date"]).dt.days / 365.2425).round(1)
    clean["Time in Job (calculated)"] = ((AS_OF_DATE - clean["Job Start Date"]).dt.days / 365.2425).round(1)
    clean["Duplicate IDs"] = duplicate_ids
    clean["Duplicate rows"] = duplicate_rows
    return clean


@pn.cache
def load_data():
    frames = [load_unit(s) for s in UNIT_ORDER]
    return pd.concat(frames, ignore_index=True)


try:
    DATA = load_data()
    DATA_ERROR = None
except Exception as exc:
    DATA = pd.DataFrame()
    DATA_ERROR = str(exc)


def _is_yes(series):
    return series.astype("string").str.strip().str.lower().eq("yes")


def get_filtered_data(units, statuses, career_levels, date_scope):
    if DATA.empty:
        return DATA.copy()
    out = DATA.copy()
    if units:
        out = out[out["Unit"].isin(units)]
    if statuses:
        out = out[out["Employee Status"].isin(statuses)]
    if career_levels:
        out = out[out["Career Level"].isin(career_levels)]
    if date_scope == "Active employees":
        out = out[out["Employee Status"].str.lower().eq("active")]
    elif date_scope == "FY2016 exit records":
        out = out[_is_yes(out["Terminated in FY"])]
    return out


def empty_fig(title, message="No records match the selected filters."):
    fig = go.Figure()
    fig.update_layout(
        title=title, template="plotly_white",
        annotations=[dict(text=message, xref="paper", yref="paper", showarrow=False, font=dict(size=14))],
        margin=dict(l=30, r=20, t=55, b=30),
    )
    return fig


def make_kpi(name, value, color="#1f77b4", footer=None):
    indicator = pn.indicators.Number(
        name=name, value=value, format="{value:,.0f}",
        font_size="26px", title_size="12pt", colors=[(0, color)]
    )
    parts = [indicator]
    if footer:
        parts.append(pn.pane.Markdown(f"<small>{footer}</small>", margin=(0, 0, 0, 5)))
    return pn.Card(*parts, title=name, collapsed=False, hide_header=True, styles={"border": "1px solid #e1e6eb", "border-radius": "10px"})


def _active(df):
    return df[df["Employee Status"].astype("string").str.lower().eq("active")]


def _exit_records(df):
    return df[_is_yes(df["Terminated in FY"])]


def build_kpis(units, statuses, career_levels, date_scope):
    f = get_filtered_data(units, statuses, career_levels, date_scope)
    active = _active(f)
    exits = _exit_records(f)
    total = len(f)
    median_age = active["Age (calculated)"].median()
    median_tenure = active["Tenure (calculated)"].median()
    values = [
        make_kpi("Records in view", total, "#1f77b4", "Unique employee IDs after deduplication"),
        make_kpi("Active employees", len(active), "#2ca02c", "Status = Active"),
        make_kpi("FY2016 exit records", len(exits), "#d62728", "Count from Terminated in FY flag"),
        make_kpi("Median age", median_age if pd.notna(median_age) else 0, "#9467bd", "Years; calculated at 31 Dec 2016"),
        make_kpi("Median tenure", median_tenure if pd.notna(median_tenure) else 0, "#ff7f0e", "Years; calculated at 31 Dec 2016"),
    ]
    return pn.GridBox(*values, ncols=5, sizing_mode="stretch_width")


def chart_headcount(units):
    if DATA.empty:
        return empty_fig("Active workforce by unit", DATA_ERROR or "Workbook unavailable")
    d = DATA[DATA["Unit"].isin(units)] if units else DATA.iloc[0:0]
    d = _active(d).groupby("Unit").size().reindex(UNIT_ORDER, fill_value=0).rename("Active employees").reset_index()
    fig = px.bar(d, x="Unit", y="Active employees", text="Active employees",
                 title="Active workforce by unit", template="plotly_white")
    fig.update_traces(textposition="outside")
    fig.update_layout(showlegend=False, margin=dict(l=20, r=20, t=50, b=20))
    return fig


def chart_exit_types(units):
    if DATA.empty:
        return empty_fig("FY2016 exits by type", DATA_ERROR or "Workbook unavailable")
    d = DATA[DATA["Unit"].isin(units)] if units else DATA.iloc[0:0]
    d = _exit_records(d)
    if d.empty:
        return empty_fig("FY2016 exits by type")
    summary = d.groupby(["Unit", "Termination Type"], dropna=False).size().reset_index(name="Exit records")
    summary["Termination Type"] = summary["Termination Type"].fillna("Not specified")
    fig = px.bar(summary, x="Unit", y="Exit records", color="Termination Type", barmode="group",
                 title="Recorded FY2016 exits by type", template="plotly_white")
    fig.update_layout(margin=dict(l=20, r=20, t=50, b=20))
    return fig


def chart_career_mix(units):
    if DATA.empty:
        return empty_fig("Career level mix", DATA_ERROR or "Workbook unavailable")
    d = DATA[DATA["Unit"].isin(units)] if units else DATA.iloc[0:0]
    d = _active(d)
    d = d[d["Career Level"].notna()]
    if d.empty:
        return empty_fig("Active employees by career level")
    counts = d.groupby(["Unit", "Career Level"]).size().reset_index(name="Employees")
    fig = px.bar(counts, x="Career Level", y="Employees", color="Unit", barmode="group",
                 title="Active employees by career level", template="plotly_white")
    fig.update_xaxes(dtick=1)
    return fig


def chart_age_tenure(units):
    if DATA.empty:
        return empty_fig("Age and tenure profile", DATA_ERROR or "Workbook unavailable")
    d = DATA[DATA["Unit"].isin(units)] if units else DATA.iloc[0:0]
    d = _active(d)
    summary = d.groupby("Unit").agg(
        Median_age=("Age (calculated)", "median"),
        Median_tenure=("Tenure (calculated)", "median")
    ).reset_index()
    if summary.empty:
        return empty_fig("Age and tenure profile")
    long = summary.melt(id_vars="Unit", var_name="Measure", value_name="Years")
    fig = px.bar(long, x="Unit", y="Years", color="Measure", barmode="group",
                 title="Active workforce: median age and tenure", template="plotly_white",
                 labels={"Years": "Years"})
    return fig


def descriptive_table(units, statuses, career_levels, date_scope):
    f = get_filtered_data(units, statuses, career_levels, date_scope)
    if f.empty:
        return pn.pane.Markdown("**No records match the selected filters.**")
    num_cols = [c for c in ["Career Level", "Age (calculated)", "Tenure (calculated)", "Time in Job (calculated)"] if c in f]
    if not num_cols:
        return pn.pane.Markdown("No numeric fields available.")
    stats = f[num_cols].describe().T[["count", "mean", "std", "min", "50%", "max"]].reset_index()
    stats = stats.rename(columns={"index": "Indicator", "50%": "Median"})
    return pn.widgets.Tabulator(stats.round(2), pagination="local", page_size=10, height=260, show_index=False)


def unit_comparison(units):
    if DATA.empty:
        return pn.pane.Markdown(f"**Workbook unavailable:** {DATA_ERROR}")
    rows = []
    for unit in UNIT_ORDER:
        if units and unit not in units:
            continue
        d = DATA[DATA["Unit"].eq(unit)]
        active = _active(d)
        exits = _exit_records(d)
        rows.append({
            "Unit": unit,
            "Unique employee records": len(d),
            "Active employees": len(active),
            "FY2016 exit records": len(exits),
            "Voluntary exits": int(exits["Termination Type"].eq("Voluntary Exit").sum()),
            "Involuntary exits": int(exits["Termination Type"].eq("Involuntary Exit").sum()),
            "FY hires": int(_is_yes(d["Hired in FY"]).sum()),
            "FY promotions": int(_is_yes(d["Promoted in FY"]).sum()),
            "Median age (active)": round(active["Age (calculated)"].median(), 1),
            "Median tenure (active)": round(active["Tenure (calculated)"].median(), 1),
            "Duplicate IDs found in raw rows": int(d["Duplicate IDs"].max()) if len(d) else 0,
        })
    return pn.widgets.Tabulator(pd.DataFrame(rows), pagination="local", page_size=10, height=240, show_index=False)


def data_quality_table():
    if DATA.empty:
        return pn.pane.Markdown(f"**Workbook unavailable:** {DATA_ERROR}")
    rows = []
    for unit in UNIT_ORDER:
        raw = pd.read_excel(WORKBOOK, sheet_name=unit, header=None, skiprows=3)
        n_raw = int(raw.iloc[:, 0].notna().sum()) if not raw.empty else 0
        d = DATA[DATA["Unit"].eq(unit)]
        rows.append({
            "Unit": unit,
            "Raw rows with ID": n_raw,
            "Unique IDs retained": len(d),
            "Duplicate IDs identified": int(d["Duplicate IDs"].max()) if len(d) else 0,
            "Missing birth dates": int(d["Birth Date"].isna().sum()),
            "Missing hire dates": int(d["Hired Date"].isna().sum()),
            "Missing job start dates": int(d["Job Start Date"].isna().sum()),
            "Missing career level": int(d["Career Level"].isna().sum()),
            "Missing education": int(d["Education"].isna().sum()),
        })
    return pn.pane.DataFrame(pd.DataFrame(rows), index=False, sizing_mode="stretch_width", height=220)


def ratings_summary(units):
    if DATA.empty:
        return empty_fig("Ratings by unit", DATA_ERROR or "Workbook unavailable")
    d = _active(DATA[DATA["Unit"].isin(units)] if units else DATA.iloc[0:0])
    d = d[d["Rating"].notna()]
    if d.empty:
        return empty_fig("Performance rating distribution")
    summary = d.groupby(["Unit", "Rating"]).size().reset_index(name="Employees")
    fig = px.bar(summary, x="Rating", y="Employees", color="Unit", barmode="group",
                 title="Recorded performance ratings (definitions may differ by unit)",
                 template="plotly_white")
    return fig



def chart_gallery(units):
    """Create a set of complementary descriptive charts for the filtered business units."""
    if DATA.empty:
        msg = DATA_ERROR or "Workbook unavailable"
        return pn.Column(pn.pane.Plotly(empty_fig("Chart gallery", msg)))

    d = DATA[DATA["Unit"].isin(units)] if units else DATA.iloc[0:0]
    if d.empty:
        return pn.Column(pn.pane.Markdown("**Select at least one business unit to display charts.**"))

    active = _active(d).copy()
    exits = _exit_records(d).copy()

    # PIE: status composition by unit
    status_counts = d.groupby(["Unit", "Employee Status"], dropna=False).size().reset_index(name="Employees")
    status_counts["Employee Status"] = status_counts["Employee Status"].fillna("Not specified")
    pie_fig = px.pie(
        status_counts, names="Employee Status", values="Employees", facet_col="Unit",
        title="Employee status composition by unit", template="plotly_white",
        hole=0.35
    )
    pie_fig.update_layout(margin=dict(l=20, r=20, t=65, b=20), legend_title_text="Status")

    # HISTOGRAM 1: age
    age_data = active[active["Age (calculated)"].notna()]
    age_fig = px.histogram(
        age_data, x="Age (calculated)", color="Unit", barmode="overlay", opacity=0.65,
        nbins=20, title="Histogram: age distribution of active employees",
        labels={"Age (calculated)": "Age (years)"}, template="plotly_white"
    )
    age_fig.update_layout(margin=dict(l=20, r=20, t=55, b=25))

    # HISTOGRAM 2: tenure
    tenure_data = active[active["Tenure (calculated)"].notna()]
    tenure_fig = px.histogram(
        tenure_data, x="Tenure (calculated)", color="Unit", barmode="overlay", opacity=0.65,
        nbins=20, title="Histogram: tenure distribution of active employees",
        labels={"Tenure (calculated)": "Tenure (years)"}, template="plotly_white"
    )
    tenure_fig.update_layout(margin=dict(l=20, r=20, t=55, b=25))

    # LINE: active employee counts across career levels (descriptive, not a time series)
    career_line_data = active[active["Career Level"].notna()].groupby(
        ["Career Level", "Unit"]
    ).size().reset_index(name="Employees")
    line_fig = px.line(
        career_line_data, x="Career Level", y="Employees", color="Unit", markers=True,
        title="Line chart: active employees by career level",
        template="plotly_white"
    )
    line_fig.update_xaxes(dtick=1)
    line_fig.update_layout(margin=dict(l=20, r=20, t=55, b=25))

    # BAR: active headcount by unit
    bar_data = active.groupby("Unit").size().reset_index(name="Active employees")
    bar_fig = px.bar(
        bar_data, x="Unit", y="Active employees", text="Active employees",
        title="Bar chart: active headcount by unit", template="plotly_white"
    )
    bar_fig.update_traces(textposition="outside")
    bar_fig.update_layout(margin=dict(l=20, r=20, t=55, b=25))

    # BARH: exits by type and unit
    if exits.empty:
        barh_fig = empty_fig("Horizontal bar: recorded exits by type", "No exit records in the selected units.")
    else:
        exit_summary = exits.groupby(["Unit", "Termination Type"], dropna=False).size().reset_index(name="Exit records")
        exit_summary["Termination Type"] = exit_summary["Termination Type"].fillna("Not specified")
        barh_fig = px.bar(
            exit_summary, x="Exit records", y="Termination Type", color="Unit",
            barmode="group", orientation="h",
            title="Horizontal bar: recorded exits by termination type",
            template="plotly_white"
        )
        barh_fig.update_layout(margin=dict(l=20, r=20, t=55, b=25))

    # SCATTER: age versus tenure for active employees
    scatter_data = active.dropna(subset=["Age (calculated)", "Tenure (calculated)"])
    if scatter_data.empty:
        scatter_fig = empty_fig("Scatter: age vs tenure", "No complete age/tenure records in the selected units.")
    else:
        scatter_fig = px.scatter(
            scatter_data, x="Age (calculated)", y="Tenure (calculated)", color="Unit",
            hover_data=["Employee ID", "Career Level", "Education"],
            opacity=0.65, title="Scatter plot: age versus tenure (active employees)",
            labels={"Age (calculated)": "Age (years)", "Tenure (calculated)": "Tenure (years)"},
            template="plotly_white"
        )
        scatter_fig.update_layout(margin=dict(l=20, r=20, t=55, b=25))

    # HEATMAP: Pearson correlations between numeric workforce measures
    numeric_cols = ["Career Level", "Age (calculated)", "Tenure (calculated)", "Time in Job (calculated)"]
    corr_data = active[numeric_cols].apply(pd.to_numeric, errors="coerce")
    corr = corr_data.corr(numeric_only=True)
    if corr.empty:
        heatmap_fig = empty_fig("Heatmap: numeric measure correlations", "Not enough numeric data to calculate correlations.")
    else:
        heatmap_fig = px.imshow(
            corr, text_auto=".2f", aspect="auto", color_continuous_scale="RdBu",
            zmin=-1, zmax=1, origin="lower",
            title="Heatmap: correlations among age, tenure, time in job and career level",
            template="plotly_white"
        )
        heatmap_fig.update_layout(margin=dict(l=20, r=20, t=65, b=25))

    note = pn.pane.Markdown(
        "**Reading the charts:** The line chart uses career level on the x-axis; it is not a time series. "
        "The heatmap shows correlations, not causal relationships. Employee status and exit counts are "
        "descriptive of the historical workbook as of 31 Dec 2016."
    )
    figures = [
        ("Pie chart", pie_fig),
        ("Histogram — age", age_fig),
        ("Histogram — tenure", tenure_fig),
        ("Line chart", line_fig),
        ("Bar chart", bar_fig),
        ("Horizontal bar chart", barh_fig),
        ("Scatter plot", scatter_fig),
        ("Heatmap", heatmap_fig),
    ]
    cards = [
        pn.Card(pn.pane.Plotly(fig, height=360, sizing_mode="stretch_width"),
                title=title, collapsed=False, sizing_mode="stretch_width")
        for title, fig in figures
    ]
    return pn.Column(note, pn.GridBox(*cards, ncols=2, sizing_mode="stretch_width"))

# Controls adapted from the supplied template's sidebar controller pattern.
unit_select = pn.widgets.MultiChoice(name="Business units", options=UNIT_ORDER, value=UNIT_ORDER)
status_options = sorted(DATA["Employee Status"].dropna().astype(str).unique().tolist()) if not DATA.empty else ["Active"]
status_select = pn.widgets.MultiChoice(name="Employee status", options=status_options, value=status_options)
career_options = sorted(DATA["Career Level"].dropna().unique().tolist()) if not DATA.empty else []
career_select = pn.widgets.MultiChoice(name="Career levels", options=career_options, value=career_options)
scope_select = pn.widgets.RadioButtonGroup(
    name="Population view",
    options=["All unique records", "Active employees", "FY2016 exit records"],
    value="All unique records",
    button_type="primary",
)
search_input = pn.widgets.TextInput(name="Employee ID search", placeholder="Optional: enter an employee ID")

@pn.depends(unit_select.param.value, status_select.param.value, career_select.param.value, scope_select.param.value)
def kpi_panel(units, statuses, careers, scope):
    return build_kpis(units, statuses, careers, scope)


@pn.depends(unit_select.param.value)
def gallery_panel(units):
    return chart_gallery(units)

@pn.depends(unit_select.param.value)
def workforce_charts(units):
    return pn.Row(
        pn.pane.Plotly(chart_headcount(units), height=350, sizing_mode="stretch_width"),
        pn.pane.Plotly(chart_career_mix(units), height=350, sizing_mode="stretch_width"),
    )

@pn.depends(unit_select.param.value)
def movement_charts(units):
    return pn.Row(
        pn.pane.Plotly(chart_exit_types(units), height=370, sizing_mode="stretch_width"),
        pn.pane.Plotly(chart_age_tenure(units), height=370, sizing_mode="stretch_width"),
    )

@pn.depends(unit_select.param.value)
def rating_chart(units):
    return pn.pane.Plotly(ratings_summary(units), height=380, sizing_mode="stretch_width")

@pn.depends(unit_select.param.value)
def comparison_table(units):
    return unit_comparison(units)

@pn.depends(unit_select.param.value, status_select.param.value, career_select.param.value, scope_select.param.value)
def stats_table(units, statuses, careers, scope):
    return descriptive_table(units, statuses, careers, scope)

@pn.depends(unit_select.param.value, status_select.param.value, career_select.param.value, scope_select.param.value, search_input.param.value)
def employee_table(units, statuses, careers, scope, query):
    f = get_filtered_data(units, statuses, careers, scope)
    if query.strip():
        f = f[f["Employee ID"].astype(str).str.contains(query.strip(), case=False, na=False)]
    cols = ["Employee ID", "Unit", "Employee Status", "Career Level", "Hired Date", "Termination Date",
            "Termination Type", "Age (calculated)", "Tenure (calculated)", "Time in Job (calculated)",
            "Rating", "Education", "Hired in FY", "Terminated in FY", "Promoted in FY"]
    if f.empty:
        return pn.pane.Markdown("**No employees match the current filters.**")
    return pn.widgets.Tabulator(f[cols].sort_values(["Unit", "Employee ID"]), pagination="local",
                                page_size=15, height=420, show_index=False)


sidebar = pn.Column(
    "## ⚙️ Controls",
    unit_select,
    status_select,
    career_select,
    pn.layout.Divider(),
    "### Workforce view",
    scope_select,
    search_input,
    pn.layout.Divider(),
    pn.pane.Markdown(
        "**Data reference date:** 31 Dec 2016  \n"
        "**Note:** This is historical data. Exit counts are not a validated turnover rate."
    ),
    width=320,
)

overview = pn.Column(
    pn.pane.Markdown("## Executive overview\nDirectional HR insights to support integration due diligence. Use the controls to filter the business units and employee population."),
    kpi_panel,
    workforce_charts,
    movement_charts,
    pn.pane.Markdown(
        "### Interpretation guardrails\n"
        "- Higher exit counts are a signal for investigation, not proof of poor retention or integration readiness.\n"
        "- The workbook does not include salary, benefits, job titles, department, location, manager, or FTE fields; savings cannot be estimated reliably from this file alone.\n"
        "- The source uses different performance-rating formats across units; do not compare rating levels until definitions are harmonized."
    ),
)

tabs = pn.Tabs(
    ("🧩 Chart Gallery", pn.Column(
        pn.pane.Markdown(
            """## Interactive chart gallery
            Pie, histogram, line, bar, horizontal bar, scatter and heatmap views for descriptive HR analysis. 
            Use the business-unit selector in the sidebar to change the population."""
        ),
        gallery_panel,
    )),

    ("📊 Executive Overview", overview),
    ("🏢 Unit Comparison", pn.Column(
        pn.pane.Markdown("## Unit-level comparison\nCounts are calculated from unique employee IDs after duplicate resolution."),
        comparison_table,
    )),
    ("📈 Descriptive Statistics", pn.Column(
        pn.pane.Markdown("## Descriptive statistics\nNumeric fields are summarized for the filtered population."),
        stats_table,
    )),
    ("⭐ Performance Ratings", pn.Column(
        pn.pane.Markdown("## Performance rating distribution\n**Caution:** rating scales or labels may differ by unit."),
        rating_chart,
    )),
    ("👥 Employee Explorer", pn.Column(
        pn.pane.Markdown("## Employee-level explorer\nUse the employee ID search and filters to inspect records."),
        employee_table,
    )),
    ("🧹 Data Quality & Assumptions", pn.Column(
        pn.pane.Markdown(
            "## Data quality checks and assumptions\n"
            "- The employee table begins after three introductory rows in each worksheet.\n"
            "- Duplicate employee IDs are reduced to one record, retaining the row with the most valid date fields. Raw duplicate counts are shown below.\n"
            "- Age, tenure, and time in job are recalculated at 31 Dec 2016 from birth, hire, and job-start dates. These are approximate years using 365.2425 days per year.\n"
            "- FY hires, exits, and promotions use the source Yes/No flags. Exit counts are not treated as an annual turnover rate because the denominator and period definitions have not been validated.\n"
            "- No values are imputed for missing career level, education, rating, or dates.\n"
            "- Unit 1 uses text performance labels while Unit 2 uses numeric ratings; the rating comparison is descriptive only until the scales are confirmed.\n"
            "- The source data is historical and should be refreshed before any current integration decision."
        ),
        data_quality_table(),
    )),
)

template = pn.template.FastListTemplate(
    title="HR Integration — Human Capital Analytics",
    sidebar=[sidebar],
    main=[tabs],
    accent_base_color="#1f77b4",
    header_background="#1f77b4",
    main_layout=None,
)

if DATA_ERROR:
    template.main.insert(0, pn.pane.Alert(
        f"HR workbook could not be loaded: {DATA_ERROR}",
        alert_type="danger"
    ))

template.servable()
