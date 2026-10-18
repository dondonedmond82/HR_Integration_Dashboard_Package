HR Integration Dashboard
========================

Files:
- hr_integration_dashboard.py : interactive Panel dashboard
- Data_Set_Case_Study_Homework(1).xlsx : HR case study workbook

Requirements:
    pip install panel pandas openpyxl plotly numpy

Run from the folder containing both files:
    panel serve hr_integration_dashboard.py --show

The app uses the source workbook's Unit 1 and Unit 2 worksheets.
If the workbook is stored elsewhere, set the HR_WORKBOOK environment variable
to its full path before starting the app.

Windows PowerShell example:
    $env:HR_WORKBOOK = "C:\path\to\Data_Set_Case_Study_Homework(1).xlsx"
    panel serve hr_integration_dashboard.py --show

Important interpretation notes:
- Data reference date is 31 December 2016.
- Duplicate employee IDs are deduplicated by retaining the row with the most valid date fields.
- Age, tenure and time-in-job are calculated from dates.
- Exit counts are not a validated turnover rate.
- Salary and role details are absent, so the dashboard cannot quantify integration savings.
