"""Build the compressed EA historic-flood index outside the Streamlit request process."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from historic_flood import _build_index

if __name__ == '__main__':
    rows=_build_index()
    print(f'Wrote {len(rows)} historic flood records.')
