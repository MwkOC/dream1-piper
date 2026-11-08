"""One-shot Dream Labs model probe using the installed public client."""

from __future__ import annotations

import argparse
import os


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", action="store_true", help="list accessible Dream models")
    args = parser.parse_args()
    if not args.models:
        parser.error("only --models is enabled until observation capture is connected")
    import dream

    with dream.DreamClient(api_key=os.environ.get("DREAM_API_KEY")) as client:
        for model in client.get_models():
            print(f"{model.id}\tservable={getattr(model, 'servable', None)}")
    return 0


__all__ = ["main"]


if __name__ == "__main__":
    raise SystemExit(main())
