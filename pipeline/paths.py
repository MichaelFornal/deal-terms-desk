import os
from pathlib import Path

MAUD_REV = "37d5c3b95d18dcd8404cc5ce3fd5069be062392f"
MAUD_BASE = f"https://huggingface.co/datasets/theatticusproject/maud/resolve/{MAUD_REV}/MAUD_v1"
CSV_NAMES = ("MAUD_train.csv", "MAUD_dev.csv", "MAUD_test.csv")

DATA = Path(os.environ.get("DTD_DATA", "data"))
RAW = DATA / "raw" / "maud"
INDEX = DATA / "index" / "maud.db"
OUT = DATA / "out"
