# Changelog

## 3.0.0 — 2026-10-14

The window is new, every operation can be run from a console, and the program now works on PDF pages and on the pictures inside documents.

- Replace the window: a native Windows window (C#, Avalonia) instead of NiceGUI in a pywebview frame. `Start.exe` opens `App\AudionImageTools.exe`; the window carries its own .NET, so nothing is installed. The console menus (`launcher_gui.cmd`, `launcher_project.cmd` and the rest), fzf, the portable PowerShell and the packages of the former window are gone; the environment holds only what the engine needs.
- Run any operation from a console through `image_cli.cmd`, with the same settings as the button: `describe` prints the sections, operations and fields as JSON, `run --operation ID [--source] [--target] [--set NAME=VALUE]` runs one. Exit codes: 0 done, 1 failed, 130 stopped, 2 a wrong call - refused before anything runs. The window writes the line it runs into its journal at every start.
- Lay the window out in nine sections under the header; an operation with settings is a form with its run button at the right of its head, the operations without settings stand in the block `Quick`, the rarely needed fields under `Advanced`, in sight. Four themes, Russian and English, switched without a restart.
- Show a preview for the operations that are hard to set blind - colour, size, turning and cropping, cutting, watermark: before, after, side by side, on one picture of the source, made again as a field changes.
- Show a batch as one live line under the journal - the share done, done and total, the speed, the time left and the file, each in its own colour - instead of a line for every file. A file that went wrong stays in the journal; every line is in the log of the operation. The bar of the run is as wide as the journal.
- PDF pages: turn chosen pages, merge PDFs in the natural order of their names, split by pages, by N pages or by ranges, clear the document properties. Pages are not redrawn; every copy is checked before it is called done; a signed or encrypted PDF is refused.
- The pictures inside documents: check their DPI in DOCX, PPTX and PDF, raise them to a threshold, shrink the pictures of a PDF, put a text watermark across its pages; shrink the pictures of DOCX and PPTX to a limit, fit a document under a size in MB, bring its pictures to sRGB or CMYK, take them out into a folder. A PNG under a size in KB - a coat of arms, a sign, a pictogram - stays PNG, and a transparent PNG keeps its transparency.
- Add `Exact size` (fit, pad, fill, stretch to a size in pixels), a scale up to 1000 %, `By height` and `By width` in `Fit to screen` and `Fit aspect`, and the quick `A4 → A3 · 141%`, `×2`, `×3` that keep the written density.
- Add `No EXIF and GPS`: the metadata taken out of JPEG, PNG and WebP without writing the picture again, its pixels checked.
- Add `Split into frames` for TIFF, GIF, WebP, APNG and MPO with the pauses kept, and `Animation from frames` into GIF, WebP or APNG.
- Add `Correction` (levels, brightness, contrast, saturation, gamma, grey, sepia, a tint of any colour, inverse, white to transparent), `PNG 256 colours`, and the quick `Auto levels` and `PNG 256`.
- Add ICO with every size of Windows, and a background of any colour for transparency.
- Refuse a Target that is the Source, lies inside it or holds it - judged by the folders the paths really lead to - before anything runs: the copies of a run could land on its originals.
- Write every result - a picture, a PDF, a copy of a document - beside its place and put it there whole: a STOP or a failure leaves the copy before it as it was, and a copy whose parts do not read back is not put in place. A signed DOCX, PPTX or PDF is refused by every operation that writes it.
- Mark the operations over documents with the marks of Word, PowerPoint and Acrobat - the formats each of them takes.
- Turn a JPEG by 90, 180 and 270 degrees without loss through jpegtran of libjpeg-turbo, when its sides are whole numbers of its blocks; the journal names a picture that is turned by its pixels.
