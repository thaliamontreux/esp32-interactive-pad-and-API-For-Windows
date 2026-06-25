@echo off
setlocal

:: Enable ANSI escape
for /f %%a in ('echo prompt $E ^| cmd') do set "ESC=%%a"
:loop
cls

:: ORANGE (yellow) Starting box
echo %ESC%[43m%ESC%[30m   STARTING...   %ESC%[0m246pGc#df5STCjiw
echo.
timeout /t 1 >nul

:: Compile step
echo Compiling...
pio run --target upload --upload-port COM58
pio run --target upload --upload-port COM40


:: Check result
IF %ERRORLEVEL% EQU 0 (
    :: Green SUCCESS box
    echo %ESC%[42m%ESC%[30m   SUCCESSFUL BUILD   %ESC%[0m
    echo.
    timeout /t 1 >nul

    :: Launch PuTTY
    putty.exe -serial COM40 -sercfg 115200,8,n,1,N
    goto loop
    
) ELSE (
    :: Red blinking ERROR box
    echo %ESC%[5m%ESC%[41m%ESC%[30m      ERROR      %ESC%[0m
    echo.

    :: Warning triangle
    echo    %ESC%[31m   /\   
    echo      /  \  
    echo     / !! \ 
    echo    /      \ 
    echo   /________\ %ESC%[0m

    echo.
)