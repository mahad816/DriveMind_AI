"""Version of the text-extraction pipeline, stored on every ``Document``.

Raise ``EXTRACTION_PIPELINE_VERSION`` whenever a change would make the extracted text of a file that is
already indexed come out different (a reader learns tables, headers are removed, a new export format).
Files whose stored version is lower are read again on the next ingest; if the new text is identical
only the version is updated, and if it differs the normal chunk and embedding steps follow.

History:
    1  every reader before the table-aware readers (legacy rows get this value in the migration)
    2  DOCX keeps headings, lists and tables; Google Docs are exported as DOCX
"""

EXTRACTION_PIPELINE_VERSION = 2
