$env:PYTHONPATH = "$PSScriptRoot\..\src"
python -m uvicorn displaypad_server.main:app --reload --host 0.0.0.0 --port 7443
