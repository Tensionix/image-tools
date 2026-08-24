@echo off
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion

title Audion Image Tools

set "BASE_DIR=%~dp0"
if "%BASE_DIR:~-1%"=="\" set "BASE_DIR=%BASE_DIR:~0,-1%"
cd /d "%BASE_DIR%"

set "CORE_DIR=%BASE_DIR%\system_core"
set "RUNTIME_DIR=%BASE_DIR%\_runtime"
set "MENU_FILE=%RUNTIME_DIR%\project_menu_ru.txt"
set "RES_FILE=%RUNTIME_DIR%\project_menu_ru_res.txt"

if not exist "%RUNTIME_DIR%" mkdir "%RUNTIME_DIR%" >nul 2>nul

call :RESOLVE_PYTHON
if errorlevel 1 goto NO_PYTHON

call :RESOLVE_FZF
if errorlevel 1 (
  set "MENU_MODE=CMD fallback"
) else (
  set "MENU_MODE=FZF"
)

:MAIN
cls
echo ======================================================================
echo   AUDION IMAGE TOOLS
echo ======================================================================
echo Root:      %BASE_DIR%
echo Python:    %PYTHON_CMD% %PYTHON_ARGS%
echo Menu mode: %MENU_MODE%
echo Focus:     broad conversion + deep JPG/PNG processing + PDF bridge
echo.

if defined FZF_CMD goto FZF_MENU
goto FALLBACK_MENU

:FZF_MENU
> "%MENU_FILE%" echo [01] Быстрый JPG 75                              ^| quick_jpg_75        ^| папка^>JPG quality 75
>>"%MENU_FILE%" echo [02] Быстрый PNG balanced                        ^| quick_png_balanced  ^| папка^>PNG balanced
>>"%MENU_FILE%" echo [03] Нормализация в sRGB, PDF остаётся PDF       ^| quick_norm_jpg      ^| выбор Pillow или color.org
>>"%MENU_FILE%" echo [04] Нормализация в CMYK, PDF остаётся PDF       ^| quick_norm_cmyk     ^| выбор Photoshop5 или FOGRA39
>>"%MENU_FILE%" echo [05] Перевод в оттенки серого (PNG)              ^| quick_gray_png      ^| вывод grayscale в PNG
>>"%MENU_FILE%" echo [06] Подгонка с обрезкой к 2160p (JPG)           ^| quick_2160_jpg      ^| 4K crop to fill frame
>>"%MENU_FILE%" echo [07] Подгонка с обрезкой к 16:9 (JPG)            ^| quick_169_jpg       ^| aspect crop keep impact
>>"%MENU_FILE%" echo [08] TIFF ^> PNG кадры 001-999                    ^| split_tiff          ^| multi-page TIFF split
>>"%MENU_FILE%" echo [09] Contact sheet                               ^| contact_sheet       ^| quick preview grid
>>"%MENU_FILE%" echo [10] Watermark текст                             ^| watermark           ^| batch text overlay
>>"%MENU_FILE%" echo [11] Обрезать однотонную рамку                   ^| trim_border         ^| crop by corner color
>>"%MENU_FILE%" echo [12] Подогнать DPI без ресайза                   ^| dpi_only            ^| update metadata only
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [13] Конвертация в JPG                           ^| convert_jpg         ^| quality 60 75 90 + DPI
>>"%MENU_FILE%" echo [14] Конвертация в PNG                           ^| convert_png         ^| balanced + DPI
>>"%MENU_FILE%" echo [32] PDF ^> JPG / PNG export                      ^| pdf_export          ^| выбрать embedded или render
>>"%MENU_FILE%" echo [33] PDF ^> Embedded images (extract)             ^| pdf_extract         ^| исследовать внутренние растры
>>"%MENU_FILE%" echo [34] Картинки ^> PDF                              ^| images_to_pdf       ^| lossless preferred или JPG High
>>"%MENU_FILE%" echo [16] Подгонка под экран 1080p / 1440p / 2160p    ^| resize_screen       ^| crop=обрезка contain=вписать pad=поля
>>"%MENU_FILE%" echo [17] Подгонка под 16:9 / A4 / A3                 ^| aspect              ^| crop=обрезка contain=вписать pad=поля
>>"%MENU_FILE%" echo [18] Плоттер: подгонка под рулон по стороне      ^| plotter_size        ^| пиксели не трогать, DPI из мм
>>"%MENU_FILE%" echo [19] Плоттер: DPI без ресайза                    ^| plotter_dpi_only    ^| пиксели не трогать, записать DPI
>>"%MENU_FILE%" echo [20] Разрезать...                                ^| split_half          ^| ленты или сетка ^> PNG
>>"%MENU_FILE%" echo [21] Умный кроп белого фона                      ^| smart_crop_white    ^| trim to first meaningful pixels
>>"%MENU_FILE%" echo [22] Уменьшить до 25%% или 50%%                    ^| downscale_percent   ^| lanczos or nearest
>>"%MENU_FILE%" echo [35] Фото-лист по ширине                         ^| photo_sheet_width   ^| строки без зазора из input
>>"%MENU_FILE%" echo [36] Фото-лист для резки                         ^| photo_sheet_cut     ^| полосы по высоте + план резки
>>"%MENU_FILE%" echo [23] Форматы и адаптеры                          ^| formats             ^| core optional best-effort
>>"%MENU_FILE%" echo [24] Информация о проекте                        ^| info                ^| paths runtime purpose
>>"%MENU_FILE%" echo.
>>"%MENU_FILE%" echo [26] Открыть папку INPUT                         ^| open_input          ^| explorer input
>>"%MENU_FILE%" echo [27] Открыть папку OUTPUT                        ^| open_output         ^| explorer output
>>"%MENU_FILE%" echo [25] Проверка окружения                          ^| doctor              ^| validate runtime and imports
>>"%MENU_FILE%" echo [28] Открыть папку CONFIG                        ^| open_config         ^| defaults ICC profiles
>>"%MENU_FILE%" echo [29] Открыть папку LOGS                          ^| open_logs           ^| JSON reports
>>"%MENU_FILE%" echo [30] Tools launcher                              ^| tools               ^| build release service
>>"%MENU_FILE%" echo [31] English project launcher                    ^| launcher_en         ^| switch to english shell
>>"%MENU_FILE%" echo [00] Выход                                       ^| exit                ^| close

"%FZF_CMD%" --prompt="audion@image-tools [PROJECT-RU] > " --pointer=">" --header="Выбери действие. Сверху быстрые пресеты, ниже ручные режимы и сервис." --layout=reverse --border=rounded --info=hidden --margin=1,2  < "%MENU_FILE%" > "%RES_FILE%"

set "CHOICE="
set /p CHOICE=<"%RES_FILE%"
if not defined CHOICE goto MAIN

for /f "tokens=2 delims=|" %%a in ("%CHOICE%") do set "RAW=%%a"
call :TRIM RAW

if /I "%RAW%"=="quick_jpg_75" goto QUICK_JPG_75
if /I "%RAW%"=="quick_png_balanced" goto QUICK_PNG_BALANCED
if /I "%RAW%"=="quick_norm_jpg" goto QUICK_NORM_JPG
if /I "%RAW%"=="quick_norm_cmyk" goto QUICK_NORM_CMYK
if /I "%RAW%"=="quick_gray_png" goto QUICK_GRAY_PNG
if /I "%RAW%"=="quick_2160_jpg" goto QUICK_2160_JPG
if /I "%RAW%"=="quick_169_jpg" goto QUICK_169_JPG
if /I "%RAW%"=="split_tiff" goto SPLIT_TIFF
if /I "%RAW%"=="contact_sheet" goto CONTACT_SHEET
if /I "%RAW%"=="watermark" goto WATERMARK
if /I "%RAW%"=="trim_border" goto TRIM_BORDER
if /I "%RAW%"=="dpi_only" goto DPI_ONLY
if /I "%RAW%"=="convert_jpg" goto CONVERT_JPG
if /I "%RAW%"=="convert_png" goto CONVERT_PNG
if /I "%RAW%"=="resize_screen" goto RESIZE_SCREEN
if /I "%RAW%"=="aspect" goto ASPECT
if /I "%RAW%"=="plotter_size" goto PLOTTER_SIZE
if /I "%RAW%"=="plotter_dpi_only" goto PLOTTER_DPI_ONLY
if /I "%RAW%"=="split_half" goto SPLIT_HALF
if /I "%RAW%"=="smart_crop_white" goto SMART_CROP_WHITE
if /I "%RAW%"=="downscale_percent" goto DOWNSCALE_PERCENT
if /I "%RAW%"=="photo_sheet_width" goto PHOTO_SHEET_WIDTH
if /I "%RAW%"=="photo_sheet_cut" goto PHOTO_SHEET_CUT_LINES
if /I "%RAW%"=="formats" goto FORMATS
if /I "%RAW%"=="info" goto INFO
if /I "%RAW%"=="doctor" goto DOCTOR
if /I "%RAW%"=="open_input" goto OPEN_INPUT
if /I "%RAW%"=="open_output" goto OPEN_OUTPUT
if /I "%RAW%"=="open_config" goto OPEN_CONFIG
if /I "%RAW%"=="open_logs" goto OPEN_LOGS
if /I "%RAW%"=="tools" goto TOOLS
if /I "%RAW%"=="launcher_en" goto LAUNCHER_EN
if /I "%RAW%"=="pdf_export" goto PDF_EXPORT
if /I "%RAW%"=="pdf_rasterize" goto PDF_EXPORT
if /I "%RAW%"=="pdf_extract" goto PDF_EXTRACT
if /I "%RAW%"=="images_to_pdf" goto IMAGES_TO_PDF
if /I "%RAW%"=="exit" exit /b 0
goto MAIN

:FALLBACK_MENU
echo [1] Быстрый JPG 75
echo [2] Быстрый PNG balanced
echo [3] Нормализация в sRGB, PDF остаётся PDF
echo [4] Нормализация в CMYK, PDF остаётся PDF
echo [5] Перевод в оттенки серого (PNG)
echo [6] Подгонка с обрезкой к 2160p (JPG)
echo [7] Подгонка с обрезкой к 16:9 (JPG)
echo [8] TIFF ^> PNG кадры 001-999
echo [9] Contact sheet
echo [A] Watermark текст
echo [B] Обрезать однотонную рамку
echo [C] Подогнать DPI без ресайза
echo [D] Конвертация в JPG
echo [E] Конвертация в PNG
echo [W] PDF ^> JPG / PNG export
echo [X] PDF ^> Embedded images (extract)
echo [Y] Картинки ^> PDF
echo [G] Подгонка под экран 1080p / 1440p / 2160p
echo [H] Подгонка под 16:9 / A4 / A3
echo [I] Плоттер: ресайз под рулон по короткой или длинной стороне
echo [J] Плоттер: DPI без ресайза под рулон
echo [K] Разрезать...
echo [L] Умный кроп белого фона
echo [M] Уменьшить до 25%% или 50%%
echo [Z] Режимы фото-листа
echo [Q] Открыть папку INPUT
echo [R] Открыть папку OUTPUT
echo [N] Форматы и адаптеры
echo [O] Информация о проекте
echo [P] Проверка окружения
echo [S] Открыть папку CONFIG
echo [T] Открыть папку LOGS
echo [U] Tools launcher
echo [V] English project launcher
echo [0] Exit
echo.
choice /C 123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ0 /N /M "Выбор: "
if errorlevel 36 exit /b 0
if errorlevel 35 goto PHOTO_SHEET_MENU
if errorlevel 34 goto IMAGES_TO_PDF
if errorlevel 33 goto PDF_EXTRACT
if errorlevel 32 goto PDF_EXPORT
if errorlevel 31 goto LAUNCHER_RU
if errorlevel 30 goto TOOLS
if errorlevel 29 goto OPEN_LOGS
if errorlevel 28 goto OPEN_CONFIG
if errorlevel 27 goto OPEN_OUTPUT
if errorlevel 26 goto OPEN_INPUT
if errorlevel 25 goto DOCTOR
if errorlevel 24 goto INFO
if errorlevel 23 goto FORMATS
if errorlevel 22 goto DOWNSCALE_PERCENT
if errorlevel 21 goto SMART_CROP_WHITE
if errorlevel 20 goto SPLIT_HALF
if errorlevel 19 goto PLOTTER_DPI_ONLY
if errorlevel 18 goto PLOTTER_SIZE
if errorlevel 17 goto ASPECT
if errorlevel 16 goto RESIZE_SCREEN
if errorlevel 15 goto MAIN
if errorlevel 14 goto CONVERT_PNG
if errorlevel 13 goto CONVERT_JPG
if errorlevel 12 goto DPI_ONLY
if errorlevel 11 goto TRIM_BORDER
if errorlevel 10 goto WATERMARK
if errorlevel 9 goto CONTACT_SHEET
if errorlevel 8 goto SPLIT_TIFF
if errorlevel 7 goto QUICK_169_JPG
if errorlevel 6 goto QUICK_2160_JPG
if errorlevel 5 goto QUICK_GRAY_PNG
if errorlevel 4 goto QUICK_NORM_CMYK
if errorlevel 3 goto QUICK_NORM_JPG
if errorlevel 2 goto QUICK_PNG_BALANCED
if errorlevel 1 goto QUICK_JPG_75
goto MAIN

:INFO
call :RUNPY "%CORE_DIR%\main.py" info
if not defined AUDION_NO_PAUSE pause
goto MAIN


:PDF_RASTERIZE
goto PDF_EXPORT

:PDF_EXPORT
set "PDF_PATH="
set "DST_PATH="
set "PDF_DPI=300"
set "PDF_ASK_DPI="
call :ASK_OUTPUT_FORMAT
call :ASK_PDF_PAGE_MODE
if /I not "%PDF_PAGE_MODE%"=="render" set "PDF_PAGE_MODE=embedded"
if /I "%OUT_FORMAT%"=="jpg" (
  if not defined JPEG_QUALITY call :ASK_JPEG_QUALITY
)
if /I "%PDF_PAGE_MODE%"=="render" (
  if defined PDF_ASK_DPI call :ASK_PDF_DPI
  if not defined PDF_DPI set "PDF_DPI=300"
)
set "PDF_PATH=%BASE_DIR%\input"
set "DST_PATH=%BASE_DIR%\output\pdf_export"
echo.
echo [INPUT]  %PDF_PATH%
echo [OUTPUT] %DST_PATH%
echo [MODE]   %PDF_PAGE_MODE%
if /I "%PDF_PAGE_MODE%"=="render" echo [DPI]    %PDF_DPI%
if /I "%PDF_PAGE_MODE%"=="embedded" (
  if /I "%OUT_FORMAT%"=="jpg" (
    call :RUNPY "%CORE_DIR%\main.py" pdf-export --input "%PDF_PATH%" --output "%DST_PATH%" --to jpg --mode embedded --jpeg-quality %JPEG_QUALITY% --metadata preserve_dpi_color
  ) else (
    call :RUNPY "%CORE_DIR%\main.py" pdf-export --input "%PDF_PATH%" --output "%DST_PATH%" --to png --mode embedded --png-preset balanced --metadata preserve_dpi_color
  )
)
if /I "%PDF_PAGE_MODE%"=="render" (
  if /I "%OUT_FORMAT%"=="jpg" (
    call :RUNPY "%CORE_DIR%\main.py" pdf-export --input "%PDF_PATH%" --output "%DST_PATH%" --to jpg --mode render --dpi %PDF_DPI% --jpeg-quality %JPEG_QUALITY% --metadata preserve_dpi_color
  ) else (
    call :RUNPY "%CORE_DIR%\main.py" pdf-export --input "%PDF_PATH%" --output "%DST_PATH%" --to png --mode render --dpi %PDF_DPI% --png-preset balanced --metadata preserve_dpi_color
  )
)
if not defined AUDION_NO_PAUSE pause
goto MAIN

:PDF_EXTRACT
set "PDF_PATH="
set "DST_PATH="
set "PDF_PATH=%BASE_DIR%\input"
set "DST_PATH=%BASE_DIR%\output\pdf_embedded_extract"
echo.
echo [INPUT]  %PDF_PATH%
echo [OUTPUT] %DST_PATH%
call :RUNPY "%CORE_DIR%\main.py" pdf-extract-embedded --input "%PDF_PATH%" --output "%DST_PATH%"
if not defined AUDION_NO_PAUSE pause
goto MAIN

:IMAGES_TO_PDF
set "SRC_PATH="
set "OUT_FILE="
call :ASK_INPUT_DIR
call :ASK_OUTPUT_PDF_FILE
call :ASK_PDF_EXPORT_MODE
if not defined SRC_PATH goto MAIN
if not defined OUT_FILE goto MAIN
call :RUNPY "%CORE_DIR%\main.py" images-to-pdf --input "%SRC_PATH%" --output "%OUT_FILE%" --mode %PDF_EXPORT_MODE%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:FORMATS
call :RUNPY "%CORE_DIR%\main.py" formats
if not defined AUDION_NO_PAUSE pause
goto MAIN

:QUICK_JPG_75
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\quick_jpg_75
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" convert --input "%SRC_PATH%" --output "%DST_PATH%" --to jpg --jpeg-quality 75
if not defined AUDION_NO_PAUSE pause
goto MAIN

:QUICK_PNG_BALANCED
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\quick_png_balanced
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" convert --input "%SRC_PATH%" --output "%DST_PATH%" --to png --png-preset balanced
if not defined AUDION_NO_PAUSE pause
goto MAIN

:QUICK_NORM_JPG
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\normalized_srgb_jpg
call :ASK_SRGB_PROFILE
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" normalize --input "%SRC_PATH%" --output "%DST_PATH%" --to jpg --target-profile srgb %SRGB_PROFILE_ARGS% --alpha-bg white --metadata preserve_dpi_color
if not defined AUDION_NO_PAUSE pause
goto MAIN

:QUICK_NORM_CMYK
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\normalized_cmyk_tiff
call :ASK_CMYK_PROFILE
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" normalize --input "%SRC_PATH%" --output "%DST_PATH%" --to tiff --target-profile cmyk %CMYK_PROFILE_ARG% --alpha-bg white --metadata preserve_dpi_color
if not defined AUDION_NO_PAUSE pause
goto MAIN

:QUICK_GRAY_PNG
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\gray_png
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" grayscale --input "%SRC_PATH%" --output "%DST_PATH%" --to png
if not defined AUDION_NO_PAUSE pause
goto MAIN

:QUICK_2160_JPG
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\screen_2160p_crop_jpg
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" resize-screen --input "%SRC_PATH%" --output "%DST_PATH%" --to jpg --target 2160p --mode crop --jpeg-quality 90
if not defined AUDION_NO_PAUSE pause
goto MAIN

:QUICK_169_JPG
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\aspect_16x9_crop_jpg
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" aspect --input "%SRC_PATH%" --output "%DST_PATH%" --to jpg --ratio 16:9 --mode crop --jpeg-quality 90
if not defined AUDION_NO_PAUSE pause
goto MAIN

:CONVERT_JPG
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\jpg
call :ASK_JPEG_QUALITY
call :ASK_DPI_OPTION
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" convert --input "%SRC_PATH%" --output "%DST_PATH%" --to jpg --jpeg-quality %JPEG_QUALITY% %DPI_ARG%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:CONVERT_PNG
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\png
call :ASK_DPI_OPTION
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" convert --input "%SRC_PATH%" --output "%DST_PATH%" --to png --png-preset balanced %DPI_ARG%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:NORMALIZE
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\normalized
call :ASK_NORMALIZE_FORMAT
call :ASK_PROFILE
call :ASK_ALPHA_BG
call :ASK_METADATA
call :ASK_DPI_OPTION
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" normalize --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --target-profile %TARGET_PROFILE% %CMYK_PROFILE_ARG% --alpha-bg %ALPHA_BG% --metadata %METADATA_POLICY% %DPI_ARG%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:RESIZE_SCREEN
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\screen_fit
call :ASK_SCREEN_TARGET
call :ASK_RESIZE_MODE
call :ASK_OUTPUT_FORMAT
call :ASK_BG_COLOR
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" resize-screen --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --target %SCREEN_TARGET% --mode %RESIZE_MODE% --background %BG_COLOR%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:ASPECT
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\aspect_fit
call :ASK_RATIO
call :ASK_RESIZE_MODE
call :ASK_OUTPUT_FORMAT
call :ASK_BG_COLOR
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" aspect --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --ratio %RATIO_NAME% --mode %RESIZE_MODE% --background %BG_COLOR%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:DPI_ONLY
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\dpi_updated
call :ASK_OUTPUT_FORMAT
call :ASK_DPI_STRICT
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" normalize --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --target-profile keep --metadata preserve_dpi_color --set-dpi %DPI_VALUE%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:PLOTTER_SIZE
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\plotter_roll_fit
call :ASK_OUTPUT_FORMAT
call :ASK_PLOTTER_SIDE
call :ASK_TARGET_MM
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" plotter-size --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --side %PLOTTER_SIDE% --target-mm %TARGET_MM%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:PLOTTER_DPI_ONLY
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\plotter_dpi_only
call :ASK_OUTPUT_FORMAT
call :ASK_DPI_STRICT
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
if /I "%OUT_FORMAT%"=="jpg" (
  set "ACTIVE_JPEG_QUALITY=90"
  if defined JPEG_QUALITY set "ACTIVE_JPEG_QUALITY=%JPEG_QUALITY%"
  call :RUNPY "%CORE_DIR%\main.py" plotter-dpi-only --input "%SRC_PATH%" --output "%DST_PATH%" --to jpg --jpeg-quality %ACTIVE_JPEG_QUALITY% --dpi %DPI_VALUE% --metadata preserve_dpi_color
) else (
  call :RUNPY "%CORE_DIR%\main.py" plotter-dpi-only --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --dpi %DPI_VALUE% --metadata preserve_dpi_color
)
if not defined AUDION_NO_PAUSE pause
goto MAIN

:SPLIT_HALF
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\split_png
call :ASK_SPLIT_MODE
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
if /I "%SPLIT_MODE%"=="grid" (
  call :ASK_SPLIT_GRID
  call :RUNPY "%CORE_DIR%\main.py" split-half --input "%SRC_PATH%" --output "%DST_PATH%" --mode grid --rows %SPLIT_ROWS% --columns %SPLIT_COLUMNS% --metadata preserve_dpi_color
) else (
  call :ASK_SPLIT_ORIENTATION
  call :ASK_SPLIT_PARTS
  call :RUNPY "%CORE_DIR%\main.py" split-half --input "%SRC_PATH%" --output "%DST_PATH%" --mode strips --orientation %SPLIT_ORIENTATION% --parts %SPLIT_PARTS% --metadata preserve_dpi_color
)
if not defined AUDION_NO_PAUSE pause
goto MAIN

:SMART_CROP_WHITE
set "TOLERANCE="
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\smart_crop_white
call :ASK_OUTPUT_FORMAT
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
echo.
set /p TOLERANCE=Допуск для белого фона [10] : 
if not defined TOLERANCE set "TOLERANCE=10"
call :RUNPY "%CORE_DIR%\main.py" smart-crop-white --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --tolerance %TOLERANCE%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:DOWNSCALE_PERCENT
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\downscale_percent
call :ASK_OUTPUT_FORMAT
call :ASK_PERCENT
call :ASK_ALGORITHM
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
if /I "%OUT_FORMAT%"=="jpg" (
  call :RUNPY "%CORE_DIR%\main.py" downscale-percent --input "%SRC_PATH%" --output "%DST_PATH%" --to jpg --jpeg-quality 75 --percent %SCALE_PERCENT% --algorithm %RESIZE_ALGO%
) else (
  call :RUNPY "%CORE_DIR%\main.py" downscale-percent --input "%SRC_PATH%" --output "%DST_PATH%" --to png --percent %SCALE_PERCENT% --algorithm %RESIZE_ALGO%
)
if not defined AUDION_NO_PAUSE pause
goto MAIN

:SPLIT_TIFF
set "SRC_PATH="
set "DST_PATH="
set "SRC_PATH=%BASE_DIR%\input"
set "DST_PATH=%BASE_DIR%\output\tiff_frames"
echo.
echo [INPUT]  %SRC_PATH%
echo [OUTPUT] %DST_PATH%
call :RUNPY "%CORE_DIR%\main.py" split-tiff --input "%SRC_PATH%" --output "%DST_PATH%"
if not defined AUDION_NO_PAUSE pause
goto MAIN

:CONTACT_SHEET
set "SRC_PATH="
set "OUT_FILE="
set "COLS="
set "THUMB="
set "SRC_PATH=%BASE_DIR%\input"
set "OUT_FILE=%BASE_DIR%\output\contact_sheet.png"
echo.
echo [INPUT]  %SRC_PATH%
echo [OUTPUT] %OUT_FILE%
set /p COLS=Колонки [4] : 
if not defined COLS set "COLS=4"
set /p THUMB=Размер миниатюр WIDTHxHEIGHT [480x270] : 
if not defined THUMB set "THUMB=480x270"
call :RUNPY "%CORE_DIR%\main.py" contact-sheet --input "%SRC_PATH%" --output "%OUT_FILE%" --columns %COLS% --thumb-size %THUMB%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:PHOTO_SHEET_MENU
echo.
echo [1] Простой лист строками без зазора
echo [2] Лист для резки: полосы по высоте
echo [0] Назад
choice /C 120 /N /M "Выбор режима фото-листа: "
if errorlevel 3 goto MAIN
if errorlevel 2 goto PHOTO_SHEET_CUT_LINES
if errorlevel 1 goto PHOTO_SHEET_WIDTH
goto MAIN

:PHOTO_SHEET_WIDTH
echo.
echo Используется конфиг: config\photo_sheet.yaml [paper_saver]
call :RUNPY "%CORE_DIR%\main.py" photo-sheet-width --config "%BASE_DIR%\config\photo_sheet.yaml" --config-mode paper_saver
if not defined AUDION_NO_PAUSE pause
goto MAIN

:PHOTO_SHEET_CUT_LINES
echo.
echo Используется конфиг: config\photo_sheet.yaml [cut_lines]
call :RUNPY "%CORE_DIR%\main.py" photo-sheet-width --config "%BASE_DIR%\config\photo_sheet.yaml" --config-mode cut_lines
if not defined AUDION_NO_PAUSE pause
goto MAIN

:WATERMARK
set "WM_TEXT="
set "WM_POS="
set "WM_OPACITY="
set "WM_SIZE="
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\watermark
call :ASK_OUTPUT_FORMAT
echo.
set /p WM_TEXT=Текст watermark : 
if not defined WM_TEXT goto MAIN
set /p WM_POS=Позиция bottom-right / bottom-left / top-right / top-left [bottom-right] : 
if not defined WM_POS set "WM_POS=bottom-right"
set /p WM_OPACITY=Непрозрачность 1-255 [160] : 
if not defined WM_OPACITY set "WM_OPACITY=160"
set /p WM_SIZE=Размер шрифта [36] : 
if not defined WM_SIZE set "WM_SIZE=36"
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
call :RUNPY "%CORE_DIR%\main.py" watermark --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --text "%WM_TEXT%" --position %WM_POS% --opacity %WM_OPACITY% --font-size %WM_SIZE%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:TRIM_BORDER
set "TOLERANCE="
call :ASK_INPUT_DIR
call :ASK_OUTPUT_DIR output\trimmed
call :ASK_OUTPUT_FORMAT
if not defined SRC_PATH goto MAIN
if not defined DST_PATH goto MAIN
echo.
set /p TOLERANCE=Допуск [10] : 
if not defined TOLERANCE set "TOLERANCE=10"
call :RUNPY "%CORE_DIR%\main.py" trim-border --input "%SRC_PATH%" --output "%DST_PATH%" --to %OUT_FORMAT% --tolerance %TOLERANCE%
if not defined AUDION_NO_PAUSE pause
goto MAIN

:DOCTOR
call :RUNPY "%CORE_DIR%\doctor.py"
if not defined AUDION_NO_PAUSE pause
goto MAIN

:OPEN_INPUT
start "" explorer "%BASE_DIR%\input"
goto MAIN

:OPEN_OUTPUT
start "" explorer "%BASE_DIR%\output"
goto MAIN

:OPEN_CONFIG
start "" explorer "%BASE_DIR%\config"
goto MAIN

:OPEN_LOGS
start "" explorer "%BASE_DIR%\logs"
goto MAIN

:TOOLS
call "%BASE_DIR%\launcher_tools.cmd"
goto MAIN

:LAUNCHER_RU
if exist "%BASE_DIR%\launcher_project_ru.cmd" (
  call "%BASE_DIR%\launcher_project_ru.cmd"
)
goto MAIN

:ASK_INPUT_DIR
set "SRC_PATH="
set "SRC_PATH=%BASE_DIR%\input"
echo.
echo [INPUT]  %SRC_PATH%
goto :eof

:INPUT_HAS_CONTENT
set "INPUT_HAS_CONTENT="
for /r "%BASE_DIR%\input" %%F in (*) do (
  set "INPUT_NAME=%%~nxF"
  if not "!INPUT_NAME:~0,1!"=="." set "INPUT_HAS_CONTENT=1"
)
set "INPUT_NAME="
goto :eof

:ASK_OUTPUT_DIR
set "DST_PATH="
set "DST_PATH=%BASE_DIR%\%~1"
echo [OUTPUT] %DST_PATH%
goto :eof

:ASK_JPEG_QUALITY
set "JPEG_QUALITY="
echo.
echo Качество JPEG:
echo   1 - 60
echo   2 - 75
echo   3 - 90
set /p JPEG_QUALITY=Select [2] : 
if not defined JPEG_QUALITY set "JPEG_QUALITY=75"
if /I "%JPEG_QUALITY%"=="1" set "JPEG_QUALITY=60"
if /I "%JPEG_QUALITY%"=="2" set "JPEG_QUALITY=75"
if /I "%JPEG_QUALITY%"=="3" set "JPEG_QUALITY=90"
goto :eof

:ASK_PNG_PRESET
set "PNG_PRESET="
if defined FZF_CMD (
  > "%MENU_FILE%" echo fast ^| fast
  >>"%MENU_FILE%" echo balanced ^| balanced
  >>"%MENU_FILE%" echo small ^| small
  call :RUN_FZF_MENU "PNG preset > " "Выбери пресет PNG."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "PNG_PRESET=%%a"
  if defined PNG_PRESET call :TRIM PNG_PRESET
  if not defined PNG_PRESET set "PNG_PRESET=balanced"
  goto :eof
)
echo.
echo Пресет PNG:
echo   1 - fast
echo   2 - balanced
echo   3 - small
set /p PNG_PRESET=Select [2] : 
if not defined PNG_PRESET set "PNG_PRESET=balanced"
if /I "%PNG_PRESET%"=="1" set "PNG_PRESET=fast"
if /I "%PNG_PRESET%"=="2" set "PNG_PRESET=balanced"
if /I "%PNG_PRESET%"=="3" set "PNG_PRESET=small"
goto :eof

:ASK_OUTPUT_FORMAT
set "OUT_FORMAT="
set "JPEG_QUALITY="
echo.
echo Формат результата:
echo   1 - JPG
echo   2 - PNG
echo   3 - JPG с качеством 75
set /p OUT_FORMAT=Select [2] : 
if not defined OUT_FORMAT set "OUT_FORMAT=png"
if /I "%OUT_FORMAT%"=="1" set "OUT_FORMAT=jpg"
if /I "%OUT_FORMAT%"=="2" set "OUT_FORMAT=png"
if /I "%OUT_FORMAT%"=="3" (
  set "OUT_FORMAT=jpg"
  set "JPEG_QUALITY=75"
)
goto :eof

:ASK_NORMALIZE_FORMAT
set "OUT_FORMAT="
set "JPEG_QUALITY="
echo.
echo Формат после нормализации:
echo   1 - JPG
echo   2 - PNG
echo   3 - JPG с качеством 75
set /p OUT_FORMAT=Select [1] : 
if not defined OUT_FORMAT set "OUT_FORMAT=jpg"
if /I "%OUT_FORMAT%"=="1" set "OUT_FORMAT=jpg"
if /I "%OUT_FORMAT%"=="2" set "OUT_FORMAT=png"
if /I "%OUT_FORMAT%"=="3" (
  set "OUT_FORMAT=jpg"
  set "JPEG_QUALITY=75"
)
goto :eof

:ASK_SRGB_PROFILE
set "SRGB_PROFILE_ARGS="
set "SRGB_PROFILE_CHOICE="
if defined FZF_CMD (
  > "%MENU_FILE%" echo pillow ^| Create Profile sRGB ^(Pillow^)
  >>"%MENU_FILE%" echo colororg ^| sRGB IEC 61966-2.1 ^(color.org^)
  call :RUN_FZF_MENU "sRGB profile > " "Выбери sRGB профиль."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "SRGB_PROFILE_CHOICE=%%a"
  if defined SRGB_PROFILE_CHOICE call :TRIM SRGB_PROFILE_CHOICE
  if not defined SRGB_PROFILE_CHOICE set "SRGB_PROFILE_CHOICE=colororg"
  if /I "%SRGB_PROFILE_CHOICE%"=="pillow" set "SRGB_PROFILE_ARGS=--srgb-profile-mode pillow"
  if /I "%SRGB_PROFILE_CHOICE%"=="colororg" set "SRGB_PROFILE_ARGS=--srgb-profile-mode colororg --srgb-profile config/icc/sRGB2014.icc"
  goto :eof
)
echo.
echo sRGB профиль:
echo   1 - Create Profile sRGB (Pillow)
echo   2 - sRGB IEC 61966-2.1 (color.org)
set /p SRGB_PROFILE_CHOICE=Select [2] : 
if not defined SRGB_PROFILE_CHOICE set "SRGB_PROFILE_CHOICE=2"
if /I "%SRGB_PROFILE_CHOICE%"=="1" set "SRGB_PROFILE_ARGS=--srgb-profile-mode pillow"
if /I "%SRGB_PROFILE_CHOICE%"=="2" set "SRGB_PROFILE_ARGS=--srgb-profile-mode colororg --srgb-profile config/icc/sRGB2014.icc"
goto :eof

:ASK_CMYK_PROFILE
set "CMYK_PROFILE_ARG="
set "CMYK_PROFILE_CHOICE="
if defined FZF_CMD (
  > "%MENU_FILE%" echo ps5 ^| Photoshop5DefaultCMYK.icc
  >>"%MENU_FILE%" echo fogra39 ^| CoatedFOGRA39.icc
  call :RUN_FZF_MENU "cmyk profile > " "Выбери CMYK профиль."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "CMYK_PROFILE_CHOICE=%%a"
  if defined CMYK_PROFILE_CHOICE call :TRIM CMYK_PROFILE_CHOICE
  if not defined CMYK_PROFILE_CHOICE set "CMYK_PROFILE_CHOICE=ps5"
  if /I "%CMYK_PROFILE_CHOICE%"=="ps5" set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/Photoshop5DefaultCMYK.icc"
  if /I "%CMYK_PROFILE_CHOICE%"=="fogra39" set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/CoatedFOGRA39.icc"
  goto :eof
)
echo.
echo CMYK профиль:
echo   1 - Photoshop5DefaultCMYK.icc
echo   2 - CoatedFOGRA39.icc
set /p CMYK_PROFILE_CHOICE=Select [1] : 
if not defined CMYK_PROFILE_CHOICE set "CMYK_PROFILE_CHOICE=1"
if /I "%CMYK_PROFILE_CHOICE%"=="1" set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/Photoshop5DefaultCMYK.icc"
if /I "%CMYK_PROFILE_CHOICE%"=="2" set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/CoatedFOGRA39.icc"
goto :eof

:ASK_PROFILE
set "TARGET_PROFILE="
set "CMYK_PROFILE_ARG="
if defined FZF_CMD (
  > "%MENU_FILE%" echo keep ^| keep
  >>"%MENU_FILE%" echo srgb ^| srgb
  >>"%MENU_FILE%" echo cmyk_ps5 ^| cmyk Photoshop5DefaultCMYK.icc
  >>"%MENU_FILE%" echo cmyk_fogra39 ^| cmyk CoatedFOGRA39.icc
  call :RUN_FZF_MENU "target profile > " "Выбери целевое цветовое пространство."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "TARGET_PROFILE=%%a"
  if defined TARGET_PROFILE call :TRIM TARGET_PROFILE
  if not defined TARGET_PROFILE set "TARGET_PROFILE=srgb"
  if /I "%TARGET_PROFILE%"=="keep" goto :eof
  if /I "%TARGET_PROFILE%"=="srgb" goto :eof
  if /I "%TARGET_PROFILE%"=="cmyk_ps5" (
    set "TARGET_PROFILE=cmyk"
    set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/Photoshop5DefaultCMYK.icc"
    goto :eof
  )
  if /I "%TARGET_PROFILE%"=="cmyk_fogra39" (
    set "TARGET_PROFILE=cmyk"
    set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/CoatedFOGRA39.icc"
    goto :eof
  )
)
echo.
echo Целевое цветовое пространство:
echo   1 - keep
echo   2 - srgb
echo   3 - cmyk Photoshop5DefaultCMYK.icc
echo   4 - cmyk CoatedFOGRA39.icc
set /p TARGET_PROFILE=Select [2] : 
if not defined TARGET_PROFILE set "TARGET_PROFILE=srgb"
if /I "%TARGET_PROFILE%"=="1" set "TARGET_PROFILE=keep"
if /I "%TARGET_PROFILE%"=="2" set "TARGET_PROFILE=srgb"
if /I "%TARGET_PROFILE%"=="3" (
  set "TARGET_PROFILE=cmyk"
  set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/Photoshop5DefaultCMYK.icc"
)
if /I "%TARGET_PROFILE%"=="4" (
  set "TARGET_PROFILE=cmyk"
  set "CMYK_PROFILE_ARG=--cmyk-profile config/icc/CoatedFOGRA39.icc"
)
goto :eof

:ASK_ALPHA_BG
set "ALPHA_BG="
if defined FZF_CMD (
  > "%MENU_FILE%" echo white ^| white
  >>"%MENU_FILE%" echo black ^| black
  >>"%MENU_FILE%" echo custom ^| свой цвет #RRGGBB
  call :RUN_FZF_MENU "alpha background > " "Выбери подложку alpha."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "ALPHA_BG=%%a"
  if defined ALPHA_BG call :TRIM ALPHA_BG
  if not defined ALPHA_BG set "ALPHA_BG=white"
  if /I "%ALPHA_BG%"=="custom" (
    set "ALPHA_BG="
    set /p ALPHA_BG=Введи цвет #RRGGBB [white] : 
    if not defined ALPHA_BG set "ALPHA_BG=white"
  )
  goto :eof
)
echo.
echo Подложка alpha:
echo   1 - white
echo   2 - black
echo   3 - свой цвет #RRGGBB
set /p ALPHA_BG=Select [1] : 
if not defined ALPHA_BG set "ALPHA_BG=white"
if /I "%ALPHA_BG%"=="1" set "ALPHA_BG=white"
if /I "%ALPHA_BG%"=="2" set "ALPHA_BG=black"
if /I "%ALPHA_BG%"=="3" (
  set "ALPHA_BG="
  set /p ALPHA_BG=Введи цвет #RRGGBB [white] : 
  if not defined ALPHA_BG set "ALPHA_BG=white"
)
goto :eof

:ASK_METADATA
set "METADATA_POLICY="
if defined FZF_CMD (
  > "%MENU_FILE%" echo preserve_all ^| preserve_all
  >>"%MENU_FILE%" echo preserve_dpi_color ^| preserve_dpi_color
  >>"%MENU_FILE%" echo strip_all ^| strip_all
  call :RUN_FZF_MENU "metadata > " "Выбери политику метаданных."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "METADATA_POLICY=%%a"
  if defined METADATA_POLICY call :TRIM METADATA_POLICY
  if not defined METADATA_POLICY set "METADATA_POLICY=preserve_dpi_color"
  goto :eof
)
echo.
echo Метаданные:
echo   1 - preserve_all
echo   2 - preserve_dpi_color
echo   3 - strip_all
set /p METADATA_POLICY=Select [2] : 
if not defined METADATA_POLICY set "METADATA_POLICY=preserve_dpi_color"
if /I "%METADATA_POLICY%"=="1" set "METADATA_POLICY=preserve_all"
if /I "%METADATA_POLICY%"=="2" set "METADATA_POLICY=preserve_dpi_color"
if /I "%METADATA_POLICY%"=="3" set "METADATA_POLICY=strip_all"
goto :eof

:ASK_DPI_OPTION
set "DPI_ARG="
set "DPI_VALUE="
echo.
echo DPI:
echo   1 - не менять
echo   2 - 300
echo   3 - 600
set /p DPI_VALUE=Select [1] : 
if not defined DPI_VALUE goto :eof
if /I "%DPI_VALUE%"=="1" goto :eof
if /I "%DPI_VALUE%"=="2" set "DPI_VALUE=300"
if /I "%DPI_VALUE%"=="3" set "DPI_VALUE=600"
if not defined DPI_VALUE goto :eof
set "DPI_ARG=--set-dpi %DPI_VALUE%"
goto :eof

:ASK_DPI_STRICT
set "DPI_VALUE="
echo.
echo Новый DPI:
echo   1 - 150
echo   2 - 300
echo   3 - свой
set /p DPI_VALUE=Select [2] : 
if not defined DPI_VALUE set "DPI_VALUE=300"
if /I "%DPI_VALUE%"=="1" set "DPI_VALUE=150"
if /I "%DPI_VALUE%"=="2" set "DPI_VALUE=300"
if /I "%DPI_VALUE%"=="3" (
  set "DPI_VALUE="
  set /p DPI_VALUE=Введите DPI [300] : 
  if not defined DPI_VALUE set "DPI_VALUE=300"
)
goto :eof

:ASK_SCREEN_TARGET
set "SCREEN_TARGET="
echo.
echo Цель:
echo   1 - 1080p
echo   2 - 1440p
echo   3 - 2160p
set /p SCREEN_TARGET=Select [3] : 
if not defined SCREEN_TARGET set "SCREEN_TARGET=2160p"
if /I "%SCREEN_TARGET%"=="1" set "SCREEN_TARGET=1080p"
if /I "%SCREEN_TARGET%"=="2" set "SCREEN_TARGET=1440p"
if /I "%SCREEN_TARGET%"=="3" set "SCREEN_TARGET=2160p"
goto :eof

:ASK_RESIZE_MODE
set "RESIZE_MODE="
echo.
echo Режим:
echo   1 - crop        - обрезать под размер
echo   2 - contain     - вписать без полей
echo   3 - pad         - вписать с полями
echo   4 - by-height   - подогнать по высоте
echo   5 - by-width    - подогнать по ширине
set /p RESIZE_MODE=Select [1] : 
if not defined RESIZE_MODE set "RESIZE_MODE=crop"
if /I "%RESIZE_MODE%"=="1" set "RESIZE_MODE=crop"
if /I "%RESIZE_MODE%"=="2" set "RESIZE_MODE=contain"
if /I "%RESIZE_MODE%"=="3" set "RESIZE_MODE=pad"
if /I "%RESIZE_MODE%"=="4" set "RESIZE_MODE=by-height"
if /I "%RESIZE_MODE%"=="5" set "RESIZE_MODE=by-width"
if /I "%RESIZE_MODE%"=="by-hight" set "RESIZE_MODE=by-height"
goto :eof

:ASK_RATIO
set "RATIO_NAME="
if defined FZF_CMD (
  > "%MENU_FILE%" echo 16:9 ^| 16:9
  >>"%MENU_FILE%" echo a4-portrait ^| a4-portrait
  >>"%MENU_FILE%" echo a4-landscape ^| a4-landscape
  >>"%MENU_FILE%" echo a3-portrait ^| a3-portrait
  >>"%MENU_FILE%" echo a3-landscape ^| a3-landscape
  call :RUN_FZF_MENU "ratio > " "Выбери соотношение."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "RATIO_NAME=%%a"
  if defined RATIO_NAME call :TRIM RATIO_NAME
  if not defined RATIO_NAME set "RATIO_NAME=16:9"
  goto :eof
)
echo.
echo Соотношение:
echo   1 - 16:9
echo   2 - a4-portrait
echo   3 - a4-landscape
echo   4 - a3-portrait
echo   5 - a3-landscape
set /p RATIO_NAME=Select [1] : 
if not defined RATIO_NAME set "RATIO_NAME=16:9"
if /I "%RATIO_NAME%"=="1" set "RATIO_NAME=16:9"
if /I "%RATIO_NAME%"=="2" set "RATIO_NAME=a4-portrait"
if /I "%RATIO_NAME%"=="3" set "RATIO_NAME=a4-landscape"
if /I "%RATIO_NAME%"=="4" set "RATIO_NAME=a3-portrait"
if /I "%RATIO_NAME%"=="5" set "RATIO_NAME=a3-landscape"
goto :eof

:ASK_BG_COLOR
set "BG_COLOR="
if defined FZF_CMD (
  > "%MENU_FILE%" echo black ^| black
  >>"%MENU_FILE%" echo white ^| white
  >>"%MENU_FILE%" echo custom ^| свой цвет #RRGGBB
  call :RUN_FZF_MENU "padding color > " "Выбери цвет полей."
  if defined FZF_RESULT for /f "tokens=1 delims=|" %%a in ("%FZF_RESULT%") do set "BG_COLOR=%%a"
  if defined BG_COLOR call :TRIM BG_COLOR
  if not defined BG_COLOR set "BG_COLOR=black"
  if /I "%BG_COLOR%"=="custom" (
    set "BG_COLOR="
    set /p BG_COLOR=Введи цвет #RRGGBB [black] : 
    if not defined BG_COLOR set "BG_COLOR=black"
  )
  goto :eof
)
echo.
echo Цвет полей:
echo   1 - black
echo   2 - white
echo   3 - свой цвет #RRGGBB
set /p BG_COLOR=Select [1] : 
if not defined BG_COLOR set "BG_COLOR=black"
if /I "%BG_COLOR%"=="1" set "BG_COLOR=black"
if /I "%BG_COLOR%"=="2" set "BG_COLOR=white"
if /I "%BG_COLOR%"=="3" (
  set "BG_COLOR="
  set /p BG_COLOR=Введи цвет #RRGGBB [black] : 
  if not defined BG_COLOR set "BG_COLOR=black"
)
goto :eof

:ASK_PLOTTER_SIDE
set "PLOTTER_SIDE="
echo.
echo Подгонять по стороне:
echo   1 - short
echo   2 - long
set /p PLOTTER_SIDE=Select [1] : 
if not defined PLOTTER_SIDE set "PLOTTER_SIDE=short"
if /I "%PLOTTER_SIDE%"=="1" set "PLOTTER_SIDE=short"
if /I "%PLOTTER_SIDE%"=="2" set "PLOTTER_SIDE=long"
goto :eof

:ASK_TARGET_MM
set "TARGET_MM="
echo.
echo Размер стороны в мм:
echo   1 - 600
echo   2 - 900
echo   3 - 1050
set /p TARGET_MM=Введите мм или пресет [900] : 
if not defined TARGET_MM set "TARGET_MM=900"
if /I "%TARGET_MM%"=="1" set "TARGET_MM=600"
if /I "%TARGET_MM%"=="2" set "TARGET_MM=900"
if /I "%TARGET_MM%"=="3" set "TARGET_MM=1050"
goto :eof

:ASK_ALGORITHM
set "RESIZE_ALGO="
echo.
echo Алгоритм:
echo   1 - lanczos
echo   2 - nearest
set /p RESIZE_ALGO=Select [1] : 
if not defined RESIZE_ALGO set "RESIZE_ALGO=lanczos"
if /I "%RESIZE_ALGO%"=="1" set "RESIZE_ALGO=lanczos"
if /I "%RESIZE_ALGO%"=="2" set "RESIZE_ALGO=nearest"
goto :eof

:ASK_SPLIT_MODE
set "SPLIT_MODE="
echo.
echo Режим разрезания:
echo   1 - ленты
echo   2 - сетка
set /p SPLIT_MODE=Select [1] : 
if not defined SPLIT_MODE set "SPLIT_MODE=strips"
if /I "%SPLIT_MODE%"=="1" set "SPLIT_MODE=strips"
if /I "%SPLIT_MODE%"=="2" set "SPLIT_MODE=grid"
goto :eof

:ASK_SPLIT_ORIENTATION
set "SPLIT_ORIENTATION="
echo.
echo Направление лент:
echo   1 - vertical
echo   2 - horizontal
set /p SPLIT_ORIENTATION=Select [1] : 
if not defined SPLIT_ORIENTATION set "SPLIT_ORIENTATION=vertical"
if /I "%SPLIT_ORIENTATION%"=="1" set "SPLIT_ORIENTATION=vertical"
if /I "%SPLIT_ORIENTATION%"=="2" set "SPLIT_ORIENTATION=horizontal"
goto :eof

:ASK_SPLIT_PARTS
set "SPLIT_PARTS="
echo.
set /p SPLIT_PARTS=Частей, 2..10 [2] : 
if not defined SPLIT_PARTS set "SPLIT_PARTS=2"
goto :eof

:ASK_SPLIT_GRID
set "SPLIT_ROWS="
set "SPLIT_COLUMNS="
echo.
set /p SPLIT_ROWS=По вертикали, 2..10 [2] : 
if not defined SPLIT_ROWS set "SPLIT_ROWS=2"
set /p SPLIT_COLUMNS=По горизонтали, 2..10 [2] : 
if not defined SPLIT_COLUMNS set "SPLIT_COLUMNS=2"
goto :eof

:ASK_PERCENT
set "SCALE_PERCENT="
echo.
echo Масштаб:
echo   1 - 25
echo   2 - 50
set /p SCALE_PERCENT=Select [2] : 
if not defined SCALE_PERCENT set "SCALE_PERCENT=50"
if /I "%SCALE_PERCENT%"=="1" set "SCALE_PERCENT=25"
if /I "%SCALE_PERCENT%"=="2" set "SCALE_PERCENT=50"
goto :eof


:ASK_PDF_DPI
set "PDF_DPI="
set "PDF_DPI_INVALID="
echo.
echo PDF DPI:
echo   Введи своё число от 1 до 1200, например 150 200 300 600
:ASK_PDF_DPI_LOOP
set /p PDF_DPI=Select : 
if defined PDF_DPI call :TRIM PDF_DPI
if not defined PDF_DPI (
  echo [INFO] Нужно ввести число DPI.
  goto ASK_PDF_DPI_LOOP
)
echo(%PDF_DPI%| findstr /r "^[0-9][0-9]*$" >nul
if errorlevel 1 (
  echo [INFO] DPI должен быть целым числом от 1 до 1200.
  goto ASK_PDF_DPI_LOOP
)
if %PDF_DPI% LSS 1 (
  echo [INFO] DPI должен быть не меньше 1.
  goto ASK_PDF_DPI_LOOP
)
if %PDF_DPI% GTR 1200 (
  echo [INFO] DPI должен быть не больше 1200.
  goto ASK_PDF_DPI_LOOP
)
goto :eof

:ASK_PDF_PAGE_MODE
set "PDF_PAGE_MODE="
set "PDF_ASK_DPI="
if not defined PDF_DPI set "PDF_DPI=300"
echo.
echo Режим экспорта PDF:
echo   1 - embedded - самый крупный растр на странице
echo   2 - render   - вся страница с текстом и вектором ^(%PDF_DPI% DPI^)
echo   3 - render   - выбрать другой DPI
set /p PDF_PAGE_MODE=Select [2] : 
if not defined PDF_PAGE_MODE set "PDF_PAGE_MODE=2"
if /I "%PDF_PAGE_MODE%"=="1" set "PDF_PAGE_MODE=embedded"
if /I "%PDF_PAGE_MODE%"=="2" set "PDF_PAGE_MODE=render"
if /I "%PDF_PAGE_MODE%"=="3" (
  set "PDF_PAGE_MODE=render"
  set "PDF_ASK_DPI=1"
)
goto :eof

:ASK_OUTPUT_PDF_FILE
set "OUT_FILE="
set "OUT_FILE=%BASE_DIR%\output\images_to_pdf.pdf"
echo [OUTPUT] %OUT_FILE%
goto :eof

:ASK_PDF_EXPORT_MODE
set "PDF_EXPORT_MODE="
echo.
echo Режим PDF:
echo   1 - Lossless
echo   2 - JPG с качеством 75
echo   3 - JPG с качеством 90
set /p PDF_EXPORT_MODE=Select [1] : 
if not defined PDF_EXPORT_MODE set "PDF_EXPORT_MODE=lossless"
if /I "%PDF_EXPORT_MODE%"=="1" set "PDF_EXPORT_MODE=lossless"
if /I "%PDF_EXPORT_MODE%"=="2" set "PDF_EXPORT_MODE=jpg75"
if /I "%PDF_EXPORT_MODE%"=="3" set "PDF_EXPORT_MODE=jpg90"
goto :eof

:NO_PYTHON
cls
echo [ERROR] Python runtime was not resolved.
echo.
echo Supported locations:
echo   runtime\python.exe
echo   runtime\python\python.exe
echo   py -3.12
echo   python
echo.
echo Use builder_main.cmd or install\Build_Portable_Env_Build.cmd
if not defined AUDION_NO_PAUSE pause
exit /b 1

:RUNPY
set "TARGET=%~1"
if not exist "%TARGET%" (
  echo [ERROR] Script not found:
  echo %TARGET%
  goto :eof
)
"%PYTHON_CMD%" %PYTHON_ARGS% %*
goto :eof

:RESOLVE_PYTHON
set "PYTHON_CMD="
set "PYTHON_ARGS="

if exist "%BASE_DIR%\runtime\python.exe" (
  set "PYTHON_CMD=%BASE_DIR%\runtime\python.exe"
  goto PY_OK
)

if exist "%BASE_DIR%\runtime\python\python.exe" (
  set "PYTHON_CMD=%BASE_DIR%\runtime\python\python.exe"
  goto PY_OK
)

py -3.12 -V >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=py"
  set "PYTHON_ARGS=-3.12"
  goto PY_OK
)

where python >nul 2>nul
if not errorlevel 1 (
  set "PYTHON_CMD=python"
  goto PY_OK
)

exit /b 1

:PY_OK
exit /b 0

:RESOLVE_FZF
set "FZF_CMD="
if exist "%CORE_DIR%\fzf.exe" (
  set "FZF_CMD=%CORE_DIR%\fzf.exe"
  exit /b 0
)
where fzf >nul 2>nul
if not errorlevel 1 (
  set "FZF_CMD=fzf"
  exit /b 0
)
exit /b 1

:RUN_FZF_MENU
set "FZF_RESULT="
if not defined FZF_CMD goto :eof
if exist "%RES_FILE%" del "%RES_FILE%" >nul 2>nul
"%FZF_CMD%" --prompt="%~1" --pointer=">" --header="%~2" --layout=reverse --border=rounded --info=hidden --margin=1,2 < "%MENU_FILE%" > "%RES_FILE%"
if exist "%RES_FILE%" set /p FZF_RESULT=<"%RES_FILE%"
goto :eof

:TRIM
for /f "tokens=* delims= " %%z in ("!%~1!") do set "%~1=%%z"
:TRIM_R
if "!%~1:~-1!"==" " set "%~1=!%~1:~0,-1!" & goto TRIM_R
goto :eof
