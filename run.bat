@echo off
setlocal

echo =======================================================
echo Starting SpeechifyPDF
echo =======================================================

set CONDA_ENV=speechifyPDF

echo Starting FastAPI backend on http://127.0.0.1:8000 ...
cd backend && conda activate %CONDA_ENV% && uvicorn app:app --host 127.0.0.1 --port 8000
