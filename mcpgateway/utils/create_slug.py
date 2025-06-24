import re
from unicodedata import normalize

# Helper regex patterns
CONTRACTION_PATTERN = re.compile(r"(\w)['’](\w)")
NON_ALPHANUMERIC_PATTERN = re.compile(r"[\W_]+")

# Special character replacements that normalize() doesn't handle well
SPECIAL_CHAR_MAP = {
    "æ": "ae",
    "ß": "ss",
    "ø": "o",
}


def slugify(text):
    """Make an ASCII slug of text.

    Args:
        text(str): Input text

    Returns:
        str: Slugified text
    """
    # Make lower case and delete apostrophes from contractions
    slug = CONTRACTION_PATTERN.sub(r"\1\2", text.lower())
    # Convert runs of non-alphanumeric characters to single hyphens, strip ends
    slug = NON_ALPHANUMERIC_PATTERN.sub("-", slug).strip("-")
    # Replace special characters from the map
    for special_char, replacement in SPECIAL_CHAR_MAP.items():
        slug = slug.replace(special_char, replacement)
    # Normalize the non-ASCII text to ASCII
    slug = normalize("NFKD", slug).encode("ascii", "ignore").decode()
    return slug
