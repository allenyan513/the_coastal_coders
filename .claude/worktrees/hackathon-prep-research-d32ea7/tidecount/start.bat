@echo off
cd /d "%~dp0"
pushd web
call pnpm install --frozen-lockfile || goto :fail
call pnpm build || goto :fail
popd
pushd server
uv sync || goto :fail
uv run python -m tidecount.setup || goto :fail
start "" http://localhost:8000
uv run uvicorn tidecount.api:app --port 8000
goto :eof
:fail
echo Setup failed. See the message above.
pause
