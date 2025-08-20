
import pandas as pd
import sqlite3
from pathlib import Path

data_dir = Path("data")
con = sqlite3.connect("hospital.db")

# Create tables
with open("schema.sql","r") as f:
    con.executescript(f.read())

# Load CSVs
pd.read_csv(data_dir/"patients.csv").to_sql("patients", con, if_exists="append", index=False)
pd.read_csv(data_dir/"units.csv").to_sql("units", con, if_exists="append", index=False)
pd.read_csv(data_dir/"bed_capacity.csv").to_sql("bed_capacity", con, if_exists="append", index=False)
pd.read_csv(data_dir/"staff.csv").to_sql("staff", con, if_exists="append", index=False)
pd.read_csv(data_dir/"admissions.csv").to_sql("admissions", con, if_exists="append", index=False)

con.commit()
con.close()
print("SQLite database created: hospital.db")
