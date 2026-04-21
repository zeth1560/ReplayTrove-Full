@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------------
REM ReplayTrove FFmpeg capture smoke test (10 seconds)
REM - Reuses rt_system/config/recording.env values
REM - Writes a short test file to verify device + encoder pipeline
REM ---------------------------------------------------------------------------

set "SCRIPT_DIR=%~dp0"
set "ROOT_DIR=%SCRIPT_DIR%..\"
set "CONFIG_FILE=%ROOT_DIR%config\recording.env"
set "FFMPEG_EXE=C:\ffmpeg\bin\ffmpeg.exe"

if not exist "%FFMPEG_EXE%" (
    echo [ERROR] FFmpeg not found at "%FFMPEG_EXE%"
    exit /b 1
)

if not exist "%CONFIG_FILE%" (
    echo [ERROR] Config file not found: "%CONFIG_FILE%"
    exit /b 1
)

for /f "usebackq tokens=1* delims==" %%A in ("%CONFIG_FILE%") do (
    set "K=%%A"
    set "V=%%B"
    if defined K (
        if not "!K:~0,1!"=="#" (
            if not "!K!"=="" set "!K!=!V!"
        )
    )
)

if "%CAPTURE_DEVICE_NAME%"=="" (
    echo [ERROR] CAPTURE_DEVICE_NAME is empty in "%CONFIG_FILE%"
    exit /b 1
)

if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=C:\ReplayTrove\long_clips"
if "%FRAME_RATE%"=="" set "FRAME_RATE=60"
if "%RTBUFSIZE%"=="" set "RTBUFSIZE=1024M"
if "%VIDEO_SIZE%"=="" set "VIDEO_SIZE=1920x1080"
if "%VIDEO_CODEC%"=="" set "VIDEO_CODEC=h264_qsv"
if "%PRESET%"=="" set "PRESET=medium"
if "%RATE_CONTROL%"=="" set "RATE_CONTROL=global_quality"
if "%GLOBAL_QUALITY%"=="" set "GLOBAL_QUALITY=23"
if "%GOP%"=="" set "GOP=120"
if "%PIX_FMT%"=="" set "PIX_FMT=nv12"
if "%OUTPUT_EXTENSION%"=="" set "OUTPUT_EXTENSION=mkv"
if "%AUDIO_CODEC%"=="" set "AUDIO_CODEC=aac"
if "%AUDIO_BITRATE%"=="" set "AUDIO_BITRATE=192k"

if not exist "%OUTPUT_DIR%" mkdir "%OUTPUT_DIR%"

for /f %%I in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd_HHmmss"') do set "TS=%%I"
set "OUTFILE=%OUTPUT_DIR%\replaytrove_test_%TS%.%OUTPUT_EXTENSION%"

set "DS_INPUT=video=%CAPTURE_DEVICE_NAME%"
if not "%AUDIO_DEVICE_NAME%"=="" set "DS_INPUT=%DS_INPUT%:audio=%AUDIO_DEVICE_NAME%"

echo [INFO] Running 10-second FFmpeg capture test...
echo [INFO] Output: %OUTFILE%

"%FFMPEG_EXE%" -hide_banner -y ^
-f dshow ^
-framerate %FRAME_RATE% ^
-rtbufsize %RTBUFSIZE% ^
-video_size %VIDEO_SIZE% ^
-i "%DS_INPUT%" ^
-t 10 ^
-c:v %VIDEO_CODEC% ^
-preset %PRESET% ^
-rc %RATE_CONTROL% ^
-global_quality %GLOBAL_QUALITY% ^
-g %GOP% ^
-pix_fmt %PIX_FMT% ^
-c:a %AUDIO_CODEC% ^
-b:a %AUDIO_BITRATE% ^
%EXTRA_ARGS% ^
"%OUTFILE%"

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo [ERROR] Test capture failed with code %EXIT_CODE%
) else (
    echo [INFO] Test capture succeeded.
)

exit /b %EXIT_CODE%
