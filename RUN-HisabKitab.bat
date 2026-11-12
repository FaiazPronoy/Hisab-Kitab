@echo off
setlocal
title Hisab Kitab
cd /d "%~dp0"

echo ==========================================
echo   HISAB KITAB
echo ==========================================
echo.

where docker >nul 2>&1
if errorlevel 1 (
  if exist "%ProgramFiles%\Docker\Docker\resources\bin\docker.exe" set "PATH=%ProgramFiles%\Docker\Docker\resources\bin;%PATH%"
)
where docker >nul 2>&1
if errorlevel 1 (
  echo [X] Docker was not found.
  echo     Install Docker Desktop from docker.com, start it once,
  echo     then run this file again.
  echo.
  pause
  exit /b 1
)

echo [1/5] Checking that Docker is running ...
docker info >nul 2>&1
if errorlevel 1 (
  echo       starting Docker Desktop, this can take a minute ...
  if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
  for /l %%i in (1,1,60) do (
    docker info >nul 2>&1 && goto docker_ok
    timeout /t 3 /nobreak >nul
  )
  echo.
  echo [X] Docker did not start. Open Docker Desktop by hand, wait until
  echo     it says "Engine running", then run this file again.
  pause
  exit /b 1
)
:docker_ok

rem with less than about 3.5 GB for Docker, one worker process instead of two keeps it from running out of memory
for /f %%m in ('powershell -NoProfile -Command "[int]((docker info --format '{{.MemTotal}}')/1MB)"') do set "MEMMB=%%m"
if defined MEMMB if %MEMMB% LSS 3500 (
  set "WORKER_CONCURRENCY=1"
  echo       Docker has %MEMMB% MB of memory, so the worker runs one task at a time.
)

if not exist ".env" (
  echo       Writing a local .env from .env.example ...
  copy /y ".env.example" ".env" >nul
)

rem another app on the same ports makes the web or the API fail to start
for %%p in (3000 8000) do (
  netstat -ano | findstr /r /c:":%%p .*LISTENING" >nul && (
    docker ps --filter "publish=%%p" --format "{{.Names}}" | findstr /b /c:"docintel-" >nul || (
      echo.
      echo [X] Port %%p is already in use by another program or container.
      echo     Stop it first: "docker ps" shows what runs, "docker stop" with its name stops it.
      pause
      exit /b 1
    )
  )
)

echo [2/5] Building and starting the containers ...
echo       The first run downloads and builds images, about 10 minutes.
rem one image at a time is slower but fits in less memory
docker compose build api && docker compose build web && docker compose up -d
if errorlevel 1 (
  echo.
  echo [X] The containers did not start. See the error above.
  pause
  exit /b 1
)

echo [3/5] Waiting for the API ...
for /l %%i in (1,1,60) do (
  curl -s -o nul http://localhost:8000/api/v1/health && goto api_ok
  timeout /t 3 /nobreak >nul
)
echo [X] The API did not answer. Run "docker compose logs api" to see why.
pause
exit /b 1
:api_ok

echo [4/5] Loading the demo invoices and reviewers ...
rem inside the running api container, so no extra container needs memory
docker compose exec -T api python -m scripts.seed_demo
if errorlevel 1 echo       the demo data did not load; the app still runs.

echo [5/5] Waiting for the web app ...
for /l %%i in (1,1,40) do (
  curl -s -o nul http://localhost:3000/login && goto web_ok
  timeout /t 3 /nobreak >nul
)
echo [X] The web app did not answer. Run "docker compose logs web" to see why.
pause
exit /b 1
:web_ok
echo       Ready.
echo.
echo   Open  http://localhost:3000/
echo.
echo   Clerk      nadia   /  demo-clerk
echo   Approver   farhan  /  demo-approver
echo.
echo   API docs   http://localhost:8000/docs   (X-API-Key: local-dev-key)
echo   Stop it    docker compose down
echo.

start "" http://localhost:3000/
pause
