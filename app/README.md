# Stable application

This is the non-ROS FastAPI boundary for the project. It validates transport
contracts only; it does not import Dream Labs, ROS 2, CAN, or cameras.

```bash
cd app
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn dream1_piper_app.main:app --reload
```

