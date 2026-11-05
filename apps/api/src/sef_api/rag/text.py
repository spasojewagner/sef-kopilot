"""Serbian text in two scripts: transliteration, folding for search, and the letters that look
alike in Cyrillic and Latin.

Serbian is written in Cyrillic and in Latin, letter for letter, so a search in either script must
find a passage written in the other. :func:`fold` reduces a text to the Latin letters without
diacritics that a person types on any keyboard ("šifra", "шифра" and "sifra" all become
"sifra"), and searches compare folded texts.

Published texts also mix the scripts inside a word: an official consolidated text spells "Члaн"
with a Latin "a", and a specification writes "BT-Е1" with a Cyrillic "Е". Such letters look the
same and differ to every program. :func:`cyrillic_words` and :func:`latin_identifier` put each
back into its script.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

__all__ = [
    "cyrillic_letters",
    "cyrillic_text",
    "cyrillic_words",
    "fold",
    "latin_identifier",
    "transliterate",
]

# fmt: off
_TO_LATIN: Final = {
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Ђ": "Đ", "Е": "E", "Ж": "Ž", "З": "Z",
    "И": "I", "Ј": "J", "К": "K", "Л": "L", "Љ": "Lj", "М": "M", "Н": "N", "Њ": "Nj", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "Ћ": "Ć", "У": "U", "Ф": "F", "Х": "H", "Ц": "C",
    "Ч": "Č", "Џ": "Dž", "Ш": "Š",
}
# fmt: on
_TRANSLITERATION: Final = str.maketrans(
    _TO_LATIN | {cyrillic.lower(): latin.lower() for cyrillic, latin in _TO_LATIN.items()}
)

#: Latin letters drawn exactly like a Cyrillic one, and that one.
# fmt: off
_LOOKALIKES: Final = {
    "A": "А", "B": "В", "C": "С", "E": "Е", "H": "Н", "J": "Ј", "K": "К", "M": "М", "O": "О",
    "P": "Р", "T": "Т", "X": "Х", "a": "а", "c": "с", "e": "е", "j": "ј", "o": "о", "p": "р",
    "x": "х", "y": "у",
}
# fmt: on
_TO_CYRILLIC: Final = str.maketrans(_LOOKALIKES)
_TO_LATIN_LOOKALIKE: Final = str.maketrans({c: latin for latin, c in _LOOKALIKES.items()})

_WORD: Final = re.compile(r"[^\W\d_]+")
_TOKEN: Final = re.compile(r"\S+")
#: The lower-case Latin letters drawn exactly like a Cyrillic one.
_LOWER_LOOKALIKES: Final = frozenset(latin for latin in _LOOKALIKES if latin.islower())
_CYRILLIC: Final = re.compile(r"[\u0400-\u04ff]")  # the Cyrillic block


def transliterate(text: str) -> str:
    """``text`` with its Serbian Cyrillic letters in Serbian Latin: "Члан 4б" is "Član 4b"."""
    return text.translate(_TRANSLITERATION)


def fold(text: str) -> str:
    """``text`` as searches compare it: in Latin, without diacritics, lower case, its spaces
    collapsed; "đ" becomes "dj", as people type it."""
    latin = transliterate(text).replace("đ", "dj").replace("Đ", "Dj")
    bare = "".join(
        char for char in unicodedata.normalize("NFKD", latin) if not unicodedata.combining(char)
    )
    return " ".join(bare.lower().split())


def _cyrillic_word(match: re.Match[str]) -> str:
    word = match.group()
    latin = {char for char in word if not _CYRILLIC.match(char)}
    if not _CYRILLIC.search(word) or not latin <= _LOOKALIKES.keys():
        return word
    return word.translate(_TO_CYRILLIC)


def cyrillic_words(text: str) -> str:
    """``text`` with the Latin look-alike letters inside Cyrillic words made Cyrillic. A word
    without a Cyrillic letter, or with a Latin letter that has no Cyrillic twin, is left as it
    is, so that "UBL", "PDF" and "cbc:ID" stay Latin."""
    return _WORD.sub(_cyrillic_word, text)


def _cyrillic_token(match: re.Match[str]) -> str:
    token = match.group()
    letters = [char for char in token if char.isalpha()]
    if letters and all(char in _LOWER_LOOKALIKES for char in letters):
        return token.translate(_TO_CYRILLIC)
    return token


def cyrillic_text(text: str) -> str:
    """``text``, known to be Serbian written in Cyrillic, with its words put back into Cyrillic:
    the Latin look-alike letters inside Cyrillic words, as :func:`cyrillic_words` does, and the
    words written only in lower-case look-alike letters, as "је", "а" and "о" are when a text
    spells them "je", "a" and "o". A word with any other Latin letter ("e-mail", "UBL",
    "PDV-RS-OBJ") stays as it is."""
    return _TOKEN.sub(_cyrillic_token, cyrillic_words(text))


def cyrillic_letters(text: str) -> str:
    """``text`` with every Latin letter that has a Cyrillic twin made Cyrillic, for a short
    text known to be Cyrillic, such as the letter of an article's number ("4a" is "4а")."""
    return text.translate(_TO_CYRILLIC)


def latin_identifier(text: str) -> str:
    """An identifier written in Latin letters, such as "BT-E1" or "AE20", with any Cyrillic
    look-alike letter in it made Latin."""
    return text.translate(_TO_LATIN_LOOKALIKE)
