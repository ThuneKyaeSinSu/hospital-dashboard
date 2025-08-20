
-- SQLite schema for synthetic hospital ops data

CREATE TABLE IF NOT EXISTS patients (
  patient_id TEXT PRIMARY KEY,
  mrn TEXT,
  age INTEGER,
  gender TEXT,
  primary_condition TEXT
);

CREATE TABLE IF NOT EXISTS units (
  unit_id TEXT PRIMARY KEY,
  unit_name TEXT
);

CREATE TABLE IF NOT EXISTS bed_capacity (
  hospital TEXT,
  unit_id TEXT,
  baseline_staffed_beds INTEGER,
  PRIMARY KEY (hospital, unit_id)
);

CREATE TABLE IF NOT EXISTS staff (
  date TEXT,
  hospital TEXT,
  unit_id TEXT,
  shift TEXT,
  scheduled_staff INTEGER,
  PRIMARY KEY (date, hospital, unit_id, shift)
);

CREATE TABLE IF NOT EXISTS admissions (
  encounter_id TEXT PRIMARY KEY,
  patient_id TEXT,
  hospital TEXT,
  unit_id TEXT,
  triage_level INTEGER,
  admit_ts TEXT,
  wait_minutes REAL,
  discharge_ts TEXT
);
