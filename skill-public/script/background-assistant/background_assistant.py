#!/usr/bin/env python3
"""Optional skill wrapper around the shared conversation command."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from xgent_conversation import main

if __name__ == '__main__':
    result = main(source_skill='background-assistant.md')
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(result)
