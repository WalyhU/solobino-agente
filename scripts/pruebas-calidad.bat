@echo off
REM Ejecuta en Windows las pruebas de calidad de Solobino (unitarias, cobertura y Selenium).
REM Uso: doble clic, o desde PowerShell:  scripts\pruebas-calidad.bat
setlocal
cd /d "%~dp0.."
if not exist reports mkdir reports
set LOG=reports\pruebas-windows.log
echo Pruebas de calidad Solobino - %DATE% %TIME% > %LOG%

where python3.13 >nul 2>&1 && (set PY=python3.13) || (set PY=python)
%PY% --version >> %LOG% 2>&1

if not exist .venv\Scripts\python.exe (
  echo [1/4] Creando entorno virtual...
  %PY% -m venv .venv >> %LOG% 2>&1
)
call .venv\Scripts\activate.bat

echo [2/4] Instalando dependencias (sin librerias CUDA)...
findstr /v /i "nvidia" voice-backend\requirements.txt > reports\req-sin-cuda.txt
python -m pip install -q --upgrade pip >> %LOG% 2>&1
python -m pip install -q -r reports\req-sin-cuda.txt pytest pytest-cov selenium >> %LOG% 2>&1

echo [3/4] Pruebas unitarias + cobertura...
echo ===== UNITARIAS ===== >> %LOG%
python -m pytest tests --ignore=tests\selenium --ignore=tests\integration -q --junitxml=reports\unit-tests.xml --cov --cov-report=xml:coverage.xml --cov-report=term >> %LOG% 2>&1
set UNIT=%ERRORLEVEL%

echo [4/4] Pruebas de interfaz con Selenium (Chrome)...
echo ===== SELENIUM ===== >> %LOG%
python -m pytest tests\selenium -v --junitxml=reports\selenium.xml >> %LOG% 2>&1
set UI=%ERRORLEVEL%

echo ===== RESUMEN: unitarias=%UNIT% selenium=%UI% (0 = OK) ===== >> %LOG%
echo.
echo Resultado: unitarias=%UNIT%  selenium=%UI%  (0 = OK). Detalle en %LOG%
endlocal
