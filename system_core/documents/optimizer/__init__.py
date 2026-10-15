"""The engine of Audion Office Image Optimizer 1.7.3 (E:\\TOOLS\\Audion Office Image Optimizer\\system_core\\app), taken whole.

What it does to a DOCX or a PPTX, as it did there: the pictures shrunk to a limit and recompressed
(ooxml_package.write_hard_batch_document), the document fitted under a size in megabytes
(write_fit_size_document), every picture brought to sRGB or CMYK with or without its ICC profile
(write_profile_normalized_document), the pictures copied out (media_extract). Two things differ from
the program it came from: the root of the project is that of Audion Image Tools (project_config.py),
and a copy keeps the name of its document - it goes into a Target of its own (ooxml_package.py).
"""
