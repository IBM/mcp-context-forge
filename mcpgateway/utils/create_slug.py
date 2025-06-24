import re
from unicodedata import normalize


def slugify(text):
    """Make an ASCII slug of text."""
    # Make lower case and delete apostrophes from contractions
    slug = re.sub(r"(\w)['’](\w)", r"\1\2", text.lower())
    # Convert runs of non-alphanumeric characters to single hyphens, strip ends
    slug = re.sub(r'[\W_]+', '-', slug).strip('-')
    # Replace a few special characters that normalize doesn't handle
    specials = {'æ': 'ae', 'ß': 'ss', 'ø': 'o'}
    for s, r in specials.items():
        slug = slug.replace(s, r)
    # Normalize the non-ASCII text to ASCII
    slug = normalize('NFKD', slug).encode('ascii', 'ignore').decode()
    return slug
