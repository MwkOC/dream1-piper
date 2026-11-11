"""Compatibility wrapper for the canonical experimental Dream/Piper probe.

Use ``cd experiments && dream-piper-models ...`` for new workflows. This
wrapper remains so existing scripts do not silently use the retired local-IK
implementation.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))

from piper.dream_probe import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
