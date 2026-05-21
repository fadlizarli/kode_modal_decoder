CIPHER_MAP = {
    'A': 1, 'B': 2, 'C': 3, 'D': 4, 'E': 5,
    'F': 6, 'G': 7, 'H': 8, 'I': 9, 'Y': 0,
}

MULTIPLIERS = {'JT': 1_000_000, 'RB': 1_000, 'RT': 100}

_CIPHER_CHARS = set(CIPHER_MAP.keys())
_SUFFIX_WORDS = set(MULTIPLIERS.keys())


def is_abcdefghiy(kode: str) -> bool:
    """Return True if all letter chars in kode belong to ABCDEFGHIY cipher."""
    parts = kode.strip().upper().split()
    if not parts:
        return False
    letters = parts[0]
    return bool(letters) and all(c in _CIPHER_CHARS for c in letters)


def decode(kode: str) -> int | None:
    """
    Decode kode_modal encoded with ABCDEFGHIY cipher.

    Format: '<letters>' or '<letters> <suffix>' where suffix is JT/RB/RT.
    Returns decoded integer cost, or None if kode is invalid/unrecognised.
    """
    parts = kode.strip().upper().split()
    if not parts:
        return None

    letters = parts[0]
    suffix = parts[1] if len(parts) > 1 else ''

    if not letters or not all(c in _CIPHER_CHARS for c in letters):
        return None

    if suffix and suffix not in _SUFFIX_WORDS:
        return None

    multiplier = MULTIPLIERS.get(suffix, 1)
    number = int(''.join(str(CIPHER_MAP[c]) for c in letters))
    return number * multiplier
