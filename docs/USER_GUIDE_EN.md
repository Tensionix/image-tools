# Audion Image Tools - User Guide

**Contents**

- [Purpose](#purpose)
- [Quick Route](#quick-route)
- [The Window](#the-window)
- [Source and Target](#source-and-target)
- [Sections](#sections)
- [Service Buttons of the Header](#service-buttons-of-the-header)
- [Threads and Memory](#threads-and-memory)
- [Main Folders](#main-folders)
- [The Console Command](#the-console-command)
- [Before Release](#before-release)

This is the English companion to `USER_GUIDE_RU.md`.

## Purpose

Audion Image Tools is a portable program for batch work on images, PDF, and the pictures inside DOCX, PPTX and PDF documents: conversion, PDF pages, images to PDF and pictures out of PDF, turning and cropping, size, DPI without touching pixels, colour profiles and correction, metadata, printable sheets, contact sheets, and the resolution and weight of the pictures in documents.

`Start.exe` opens the window. Every button of the window is a run of the console command `image_cli.cmd` with the same settings; the same work can be done from a console (see "The console command").

## Quick Route

1. Open `Start.exe`.
2. Put files into `input\`, or choose a folder (or one file) in the `SOURCE` row.
3. Choose a section in the row under the header, then an operation - a large button on the page of the section.
4. Check `SOURCE`, `TARGET` and the fields of the form; for an operation with a preview, look at what it makes of the first picture.
5. Press the run button at the head of the form. The operations of the `Quick` block run at once, without a form.
6. Follow the journal on the right; take the result from `TARGET`.

Until `SOURCE` and `TARGET` are chosen, an operation reads `input\` and writes into its own subfolder of `output\`.

## The Window

**Header.** On the left - the name and the version, and the badges of what the engine can do on this machine (`HEIC`, `AVIF`, `RAW`, `WORD`, `POWERPOINT`). On the right - `THREADS` (how many pictures are processed at once), the service buttons `FORMATS`, `PROJECT INFO`, `DOCTOR`, the language `RU`/`EN`, the theme (Audion Code Dark, Audion Vault Dark, Audion Dark, Audion Light), `SETTINGS` (colours, fonts and sizes of the window) and `ABOUT`. The language and the theme change without a restart.

**Sections.** The row of large buttons under the header: `CONVERT`, `PDF`, `TRANSFORM`, `CUT`, `SIZE`, `DPI`, `COLOUR`, `PHOTO SHEET`, `SHEETS AND MARKS`. Under the name of a section - a line of what it holds.

**A page.** The operations of a section are the large buttons at the top of its page. An operation with settings opens a form; its run button stands at the right of the head of the form, next to the return of the fields to their defaults. The operations over documents wear a frame of their own and the marks of the formats they take: Word - DOCX, PowerPoint - PPTX, Acrobat - PDF. The `Quick` block at the bottom of the page holds the operations of the section without settings: one press - one run.

**Fields.** A choice of a few is a row of switch buttons; several formats - ticks; numbers - fields with arrows; smooth values (brightness, contrast, saturation) - sliders, their track painted in what the slider does. An own colour is set by a swatch, R, G, B sliders and fields. The rarely needed fields stand under `Advanced`, in sight. Short captions are explained by tooltips.

**Preview.** The operations that are hard to set blind (colour, size, turning and cropping, cutting, watermark) show a preview frame under the form: `Before`, `After` or `Side by side`. It shows what the operation will make of one picture of the source, on a smaller copy; the arrows step through the pictures of the source. The picture is made again a moment after a field stops changing.

**The right column.** At the top - `SOURCE` and `TARGET` (see below). Under them, after a check of documents, the `RESULT` card: the total, the table, the report and its folder. Below - the `JOURNAL` with `LOGS` (the folder of the logs), `REPORT` (the folder of the reports), `CONFIG` (the folder of the settings), copy, clear, and the journal over the whole window. The column is widened by dragging its edge.

**The journal.** The lines of an operation come in their colours: what went - green, what asks for a look - amber, an error - red, service lines - quiet. The start and the end of every run is a bold `=====` line. A batch of many files writes no line for every file: at the bottom of the journal goes one live line - the share done, how many are done and how many there are, the speed, the time left (ETA) and the file, each in its own colour. A file that went wrong stays in the journal as a line with its details. Every line of every file is in the log of the operation in `logs\`.

**The status line.** At the bottom of the window: what the window is doing, the bar of the run under the journal across its whole width, the time of the run and `STOP`. `STOP` asks the operation to stop at its next safe point; a second press a few seconds later ends it at once. Every result - a picture, a PDF, a copy of a document - is written beside its place and takes the place only whole: the file being written when the run stops does not spoil the earlier result of the same name.

## Source and Target

- `SOURCE` is a folder or one file. `TARGET` is the folder of the result. A path can be typed (Enter takes it) or chosen by a button.
- Each row has: choose a folder, for the source - choose one file, earlier paths, pin the path, open in Explorer.
- `RESET` returns both paths to the folders of the program, `input\` and `output\`. The history of paths is cleared, the pinned ones stay, no file is touched.
- `LIST` writes into the journal what lies in the source, with its subfolders.
- `TO SOURCE` makes the result the source of the next operation: the source is cleared (into the Recycle Bin), then the contents of the target move into it.
- `CLEAR` deletes the contents of the source, the target or both - into the Recycle Bin. The folders stay; before deleting, the window asks and names the paths.

The folders inside the source are repeated in the target. `TARGET` may not be `SOURCE`, lie inside it or hold it - through a link to a folder as well: the copies of a run would be among its originals. Such a run is refused before it starts, nothing touched.

## Sections

### CONVERT

`Convert images` turns a folder into one or several formats: `JPG`, `PNG`, `TIFF`, `WebP`, `AVIF`, `HEIF`, `HEIC`, `ICO`. With several formats the result is laid out into a subfolder per format. For JPG and the compact formats - quality `60%`, `75%`, `90%` and an exact field `1..100` (`83` by default). For `JPG`, `PNG` and `TIFF` a DPI can be written without touching pixels. `Background under transparency` - `White`, `Black` or `Custom`: it fills what is transparent where the format keeps no transparency. `Metadata`: `DPI + color`, `Preserve all`, `Strip all`. `ICO` writes every size of an icon Windows asks for into one file.

Quick operations:

- `JPG 75% quality`, `PNG`, `Grayscale PNG`.
- `2160p JPG 90% quality` - to UHD `3840x2160` with a centre crop. When the source is smaller than UHD and is enlarged, a gentle `Unsharp Mask` follows Lanczos.
- `16:9 JPG 90% quality` - a crop to 16:9.

`Animation from frames` puts the pictures of a folder into one GIF, WebP or APNG in the order of their names (2 before 10). The pauses come from `frames.json` when `Split into frames` left one, or from a frame rate.

### PDF

- `Images to PDF` - a PDF of images: `All images into one PDF` or `Separate PDFs by folder`, `PNG lossless` or JPG 75/90 %. `Do not change DPI` keeps the size of the pages by the DPI of the sources; an own DPI changes the physical size of the pages, not the pixels.
- `PDF export` - pages through their embedded rasters or rendered at a DPI (up to 1200).
- `Extract embedded` - the embedded raster objects in their own format or in chosen formats, into one folder or into folders named after the PDF; a TIFF can be written beside a PNG.
- `Turn pages` - turns the named pages (`1-3, 7`). The page is not redrawn: text stays text, pictures keep every pixel.
- `Merge PDF` - every PDF of the source into one file, in the order of their names; pages move as they are.
- `Split PDF` - one page each, N pages each, or by ranges; the files are named `name_001.pdf`, `name_002.pdf`.
- `Check DPI` - the table of the pictures of every PDF: pixels, size on the page, resolution, and the total "how many below the threshold". The PDF is not changed. The table is in the `RESULT` card and in the report (CSV and Markdown).
- `Raise to DPI` - a copy of the PDF with its pictures at the threshold or above; the pages, the text and the place of every picture stay.
- `Lighter pictures` - a copy of the PDF with lighter pictures: what is above the target resolution gets fewer pixels and is written as JPEG.
- `Watermark` - a line of text across every page along its diagonal, half transparent; it is written as text over the page.
- `Extract from DOCX and PPTX` - the pictures of documents as they are stored, into a folder named after the document.
- Quick `No PDF properties` - a copy without author, title, producer, dates and XMP.

Every copy of a PDF is checked (pages, text, the place of the pictures) before it is called done. A PDF with a signature or encryption is not changed and is named. A copy of a document is written beside its place and takes the place only whole: a `STOP` in the middle of the writing leaves the copy before it as it was.

### TRANSFORM

- `Turn by angle` - any angle with fractions of a degree; the canvas grows, stays, or the corners of the fill are cut.
- `Trim border` - removes a solid border by the colour of the corners.
- `Smart crop white` - crops a white background to the meaningful pixels.
- `Margins` - margins around a picture in millimetres of a chosen colour; millimetres are counted by the density of the picture, or by the DPI of the form when it has none.

`Safety margin, mm = 0` cuts exactly along the found contour; a larger value keeps the source background around the result by the DPI of the picture (300 without one). A PDF can be built right after a crop: `Embedded PNG` lossless or `Embedded JPG 75%` for a compact PDF.

Quick operations: `90° clockwise`, `90° counter-clockwise`, `Turn 180°`, `Mirror left-right`, `Mirror top-bottom`. A JPEG is turned without loss (jpegtran) when its sides are whole numbers of its JPEG blocks; otherwise it is written again at quality 95, and the journal names it.

### CUT

- `Split...` - strips or a grid of rectangles, up to 100 parts: `name_01.png`, `name_02.png` and so on.
- `Split into frames` - a picture of several frames (a multi-page TIFF, an animated GIF, WebP or APNG, MPO) into lossless PNG frames, in a folder of its name; an animation leaves `frames.json` with its pauses.

### SIZE

- `File size` - smaller or larger by a percent (up to 400 %), or the largest percent that fits a target file size in MB.
- `Fit to screen` - 1080p, 1440p or 2160p: `Crop` fills the frame and cuts the rest, `Contain` keeps the whole picture, `Pad` adds a background up to the target size, `By height` and `By width` bring one side to the target and keep the proportions.
- `Fit aspect` - 16:9, A4 or A3 in the same modes.
- `Exact size` - an exact width and height in pixels: fit, fit with margins (white, black, transparent or of an own colour), fill with a crop, or stretch.
- `Shrink in documents` - the pictures of DOCX and PPTX to a limit (`1920 × 1080`, `2560 × 1440`, `3840 × 2160` or own) and recompressed. In HARD a PNG becomes a JPEG unless it is lighter than `Keep PNG under, KB`, would come out heavier as a JPEG, or is transparent: coats of arms, signs and pictograms stay PNG. SAFE touches JPEGs only. A signed DOCX or PPTX is not changed: its signature would break.
- `Document to a file size` - every DOCX and PPTX under a size in megabytes; the limit is lowered step by step, and a document that does not fit is named.

Quick operations: `A4 → A3 · 141%`, `×2`, `×3` - enlarged with the written density kept, so the print comes out as many times larger too.

Algorithms:

- `Lanczos` - the best for photos and soft scans; on PNG maps it can make halos and heavier files.
- `Bicubic` - a soft compromise for photos and JPG.
- `Box` - a dry average for maps, plans and screenshots: fewer halos, lighter PNG.
- `Nearest` - makes no new colours and often the lightest PNG, but diagonals and thin text turn into steps.

In `Fit`, `Target MB` is a limit for every file; a normal result is about `0.8-1.0` of the target. The percent of the scale is chosen, not the JPG quality.

### DPI

- `Fit to roll` - the DPI for a physical side in millimetres; pixels stay.
- `DPI only for roll` - a DPI written without touching pixels.
- `Check DPI` - for DOCX, PPTX and PDF: a line for every placed picture - pixels, the size of the placement, the resolution and the number the picture states of itself - and the total "how many below the threshold". The documents are not changed; the table is in the `RESULT` card and in the report.
- `Raise to DPI` - a copy of the document with its pictures at the threshold or above. Only the pictures change: the text, the pages, the place and size of the placements stay. Word and PowerPoint are told not to compress the pictures back.

### COLOUR

- `Normalize profile` - keep the profile, or bring the result to `sRGB` (`sRGB 2014` of color.org or Pillow's built-in) or `CMYK` (`Photoshop5DefaultCMYK.icc` or `CoatedFOGRA39.icc`); output formats, quality and metadata.
- `Correction` - auto levels (per channel or with the tone), brightness, contrast, saturation, gamma, tone (`Black and white`, `Sepia`, a `Tint` of an own colour), inverse, white to transparent. Transparency is kept; a JPEG whose white became transparent is written as PNG.
- `PNG 256 colours` - a PNG of at most the chosen number of colours: drawings, plans, maps and screenshots become many times lighter with no visible difference.
- `Profile in documents` - the pictures of DOCX and PPTX in sRGB or CMYK, with an ICC profile inside the picture or without.

Quick operations:

- `No EXIF and GPS` - a copy of every JPEG, PNG and WebP without EXIF (GPS, camera, date, thumbnail), XMP, IPTC and comments. The picture is not written again: the copy gives the same pixels, and that is checked; the profile, the density and the orientation of the photo stay.
- `Auto levels` - levels stretched per channel: the dullness of a scan and a colour cast go.
- `PNG 256` - a PNG of 256 colours without dithering.

### PHOTO SHEET

- `Paper saver` - a dense layout in rows without gaps.
- `Cut-lines` - grouped by similar height, with a `cut_plan.txt`.

Common settings: sheet width in mm, final DPI, reading subfolders, background, format and quality. Source pixels are not resampled: the width and the DPI describe the final sheet. When the chosen DPI is too low for the source pixels at that width, the DPI of the sheet is raised, and the report names it.

### SHEETS AND MARKS

- `Tile sheet` - one picture across A5, A4, A3 or a roll of a given width. Sizes `As is`, `By width`, `By height`, `Document 40x30`, `Document 60x40`; frame, margins and gap in millimetres.
- `Watermark` - a horizontal caption in a corner or a diagonal protective line.
- `Contact sheet` - a grid of thumbnails of a folder: a caption with the name, a `px | cm | DPI` line and the weight in KB. A thumbnail shows the whole picture; without a DPI, centimetres are counted at 300 dpi, and the caption says so.

Watermark:

- `Corner` - a tidy technical caption: a date, an author, a draft status; `Corner font size` works here only.
- `Diagonal protective` - text across the whole picture; `Diagonal coverage, %` sets the length of the caption against the diagonal (60 % suits short words like `COPY`).
- `Opacity` - `0..255`; `64` by default, about 25 % opaque. For red or black text start at `64-96`, for light text on a dark ground - at `96-128`.
- `Color` - `Red`, `Black`, `White`, `Yellow`, `Gray`, `Blue` or `Custom RGB` (R, G, B from 0 to 255).

## Service Buttons of the Header

- `FORMATS` - which formats and adapters this machine has.
- `PROJECT INFO` - the paths of the program and its environment.
- `DOCTOR` - a check of Python and the packages of the engine.

They use neither `SOURCE` nor `TARGET`.

## Threads and Memory

`THREADS` in the header is how many independent pictures are processed at once. It helps on batches, but large maps, TIFF and PDF rendering and PNG output take much more memory than the file on disk: every thread may open one more heavy picture.

- `16 GB RAM` - `1-2` threads.
- `32 GB RAM` - usually `4`.
- `64 GB RAM` - `8-12` after checking the peak memory.
- `128 GB+ RAM` - `16+` can be tried while watching the memory.

## Main Folders

- `App\` - the window and the PowerShell the program carries.
- `input\` - default sources.
- `output\` - default results.
- `logs\` - the log of every operation.
- `report\` - the reports of checks.
- `workspace\` - temporary working area.
- `config\` - the operations, the layout of the window, defaults, ICC profiles.
- `docs\` - documentation.
- `system_core\` - the engine and the console command.
- `runtime\`, `wheelhouse\`, `install\download\` - the portable environment and build files.

## The Console Command

Every operation of the window runs from a console too, with the same fields:

```bat
image_cli.cmd describe
image_cli.cmd run --operation downscale_percent --set scale_mode=custom --set custom_percent=75
image_cli.cmd run --operation convert_images --source D:\Photos --target D:\Out --set to=jpg,png
```

`describe` prints every section, operation and field as JSON. Exit codes: `0` done, `1` failed, `130` stopped, `2` a wrong call - and then nothing is run. At every start the journal of the window writes the line that repeats the same operation from a console.

The engine can be called directly as well:

```bat
runtime\python.exe system_core\main.py plotter-size --input input --output output\plotter_roll_fit --to png --side short --target-mm 900
runtime\python.exe system_core\main.py plotter-dpi-only --input input --output output\plotter_dpi_only --to png --dpi 300
runtime\python.exe system_core\main.py smart-crop-white --input input --output output\smart_crop_white --to png --tolerance 10 --safety-margin-mm 0
runtime\python.exe system_core\main.py images-to-pdf --input input --output output\images.pdf --bundle folders --mode lossless
```

## Before Release

Run the interactive cleanup:

```bat
cleanup_project.cmd
```

It asks `Y/N/Q`. `Y` clears working results, the portable environment, wheelhouse, downloaded archives, caches and temporary files. The window `App\`, the source scripts, folders, documentation, licenses and settings stay.
