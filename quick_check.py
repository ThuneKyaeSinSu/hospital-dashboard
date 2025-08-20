# quick_check.py
import sqlite3, pandas as pd
con = sqlite3.connect("hospital.db")
for t in ["patients","units","bed_capacity","staff","admissions"]:
    n = pd.read_sql(f"SELECT COUNT(*) as n FROM {t}", con)["n"][0]
    print(t, n)
con.close()
