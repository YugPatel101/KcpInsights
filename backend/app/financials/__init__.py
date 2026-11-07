"""Financial-document processing: table reconstruction, statement extraction, validation.

Pure functions over PDF bytes/pages; no network and no database access. Extracted figures are
never invented: a field that cannot be located and parsed is simply absent, and every figure keeps
the page, label and text it was read from.
"""
