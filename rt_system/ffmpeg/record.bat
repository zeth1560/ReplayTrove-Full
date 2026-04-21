@echo off
setlocal EnableExtensions EnableDelayedExpansion

REM ---------------------------------------------------------------------------
REM ReplayTrove long-form recording launcher (Windows batch)
REM - Loads settings from ..\config\recording.env
REM - Uses FFmpeg DirectShow capture with Intel QSV encoding
REM - Writes output outside rt_system for git cleanliness
REM ---------------------------------------------------------------------------

set "SCRIPT_DIR=%~dp0"
set "CONFIG_FILE=%SCRIPT_DIR%..\config\recording.env"
set "FFMPEG_EXE=C:\ffmpeg\bin\ffmpeg.exe"

if not exist "%FFMPEG_EXE%" (
    echo [ERROR] FFmpeg not found at "%FFMPEG_EXE%"
    echo         Update FFMPEG_EXE in this script if your install path differs.
    exit /b 1
)

if not exist "%CONFIG_FILE%" (
    echo [ERROR] Config file not found: "%CONFIG_FILE%"
    exit /b 1
)

REM Basic .env parser for KEY=VALUE lines.
REM Tradeoff: intentionally simple and reliable for batch; avoid advanced quoting/escaping.
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
set "OUTFILE=%OUTPUT_DIR%\replaytrove_longform_%TS%.%OUTPUT_EXTENSION%"

set "DS_INPUT=video=%CAPTURE_DEVICE_NAME%"
if not "%AUDIO_DEVICE_NAME%"=="" set "DS_INPUT=%DS_INPUT%:audio=%AUDIO_DEVICE_NAME%"

echo [INFO] Starting FFmpeg long-form recording...
echo [INFO] Device: %CAPTURE_DEVICE_NAME%
echo [INFO] Output: %OUTFILE%

"%FFMPEG_EXE%" -hide_banner -y ^
-f dshow ^
-framerate %FRAME_RATE% ^
-rtbufsize %RTBUFSIZE% ^
-video_size %VIDEO_SIZE% ^
-i "%DS_INPUT%" ^
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
    echo [ERROR] FFmpeg exited with code %EXIT_CODE%
) else (
    echo [INFO] Recording ended successfully.
)

exit /b %EXIT_CODE%
