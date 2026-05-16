"""Make ml-service/ the import root for tests so they can resolve the
scripts/ helpers directly via importlib without modifying sys.path
manually in every test file."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
