"""
Encodes token.pickle as a base64 string so it can be stored as a Railway env var.

Usage (after running generate_token.py):
    cd hw-proposal-generator
    source venv/bin/activate
    python scripts/encode_token.py

Copy the printed string, then in Railway:
    Variables → Add variable → GOOGLE_TOKEN_PICKLE_B64 = <paste here>
"""

import base64
from pathlib import Path

TOKEN_FILE = Path("token.pickle")

if not TOKEN_FILE.exists():
    print("ERROR: token.pickle not found.")
    print("Run  python scripts/generate_token.py  first to authorise and generate it.")
    exit(1)

b64 = base64.b64encode(TOKEN_FILE.read_bytes()).decode("utf-8")

print("=" * 60)
print("GOOGLE_TOKEN_PICKLE_B64 value (copy everything below the line):")
print("=" * 60)
print(b64)
print("=" * 60)
print("\nIn Railway: Variables → Add → GOOGLE_TOKEN_PICKLE_B64 = <paste above>")
