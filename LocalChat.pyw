"""Windows GUI entry point; double-click to open Local Chat without a console."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import main

main()
