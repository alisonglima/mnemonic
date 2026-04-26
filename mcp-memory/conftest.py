import sys
from pathlib import Path

# Allow `from scripts.benchmark import ...` regardless of pytest invocation CWD.
# The scripts/ directory lives next to this conftest.py.
sys.path.insert(0, str(Path(__file__).parent / "scripts"))
