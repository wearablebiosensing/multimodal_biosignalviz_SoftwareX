"""Download the open PhysioNet databases used to benchmark BioViz Studio.

    python download_physionet.py            # both databases
    python download_physionet.py nstdb      # MIT-BIH Noise Stress Test Database only

Records are saved under ./physionet/<database>/ in WFDB format (.hea/.dat/.atr).
Point the app's "Evaluation Experiment" mode (Local Path) at that folder, or zip a
single record's .hea/.dat/.atr files and upload it in the Analysis Dashboard.
"""
import sys
from pathlib import Path

import wfdb

DATABASES = {
    "nstdb": "MIT-BIH Noise Stress Test Database (360 Hz, 30-min two-lead ECG)",
    "ltdb": "MIT-BIH Long-Term ECG Database (seven long-term two-lead ECG recordings)",
}


def main(selected):
    out_root = Path(__file__).resolve().parent / "physionet"
    for db in selected:
        if db not in DATABASES:
            sys.exit(f"Unknown database '{db}'. Choose from: {', '.join(DATABASES)}")
        target = out_root / db
        target.mkdir(parents=True, exist_ok=True)
        print(f"Downloading {DATABASES[db]} -> {target}")
        wfdb.dl_database(db, dl_dir=str(target))
    print("Done.")


if __name__ == "__main__":
    main(sys.argv[1:] or list(DATABASES))
