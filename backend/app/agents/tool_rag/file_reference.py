"""Whether a reference the model passed to ``resolve_file`` is shaped like a file name.

``resolve_file`` matches exact file names. A reference such as "invoice INV-0457" or "the Q3 board deck"
therefore always comes back NOT_FOUND, and that says nothing about the user's question: the invoice may
be indexed and answerable. A reference that ends in an extension ("budget_2027.txt") is a claim that a
file of that name exists; when it does not, the user must be told so and no other document may stand in.

Structural test only, no guessing about intent: ``.`` followed by a letter and up to four letters or
digits at the end. A version ("release 1.3.2", ".2") or a sentence ("Q3.") is not an extension.
"""

import re

_EXTENSION = re.compile(r"\.[A-Za-z][A-Za-z0-9]{0,4}$")


def names_a_file(reference: str) -> bool:
    return _EXTENSION.search(reference.strip()) is not None
