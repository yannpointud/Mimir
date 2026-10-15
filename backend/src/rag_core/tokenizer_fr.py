"""Light French tokenizer for the BM25 lexical index.

Design decision: lowercase + accent folding (é -> e) +
split on non-alphanumerics, with NO stemming and NO stopword removal. The goal
is to preserve exact terms, identifiers and acronyms (e.g. "JIRA-4521",
"API") which the dense embedding path tends to miss -- that is precisely what
gives the hybrid retrieval its edge on exact-match queries.

The very same tokenizer MUST be applied on both sides (indexing AND querying):
if the two sides tokenized differently the tokens would never match. This module
is stdlib-only (re, unicodedata) and has no external dependency.
"""

import re
import unicodedata

# Split on runs of ASCII alphanumerics (applied AFTER accent folding + lowercasing).
# This deliberately drops punctuation and splits identifiers like "API-42" into
# ["api", "42"] and "COVID-19" into ["covid", "19"] without any stemming.
_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _fold_accents(text: str) -> str:
    """Fold French accents to their base letters (é -> e, à -> a, ç -> c, ...).

    Uses NFKD decomposition then drops the combining diacritical marks
    (Unicode category 'Mn'). This is what makes "Café", "cafe" and "CAFÉ"
    collapse to the same token so an accented query matches an unaccented
    document (and vice versa).

    Example: "Café" -> "Cafe", "COVID-19" -> "COVID-19"
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _split_alnum(text: str) -> list[str]:
    """Lowercase then split on non-alphanumerics.

    Preserves identifiers/acronyms without stemming or stopword filtering
    (deliberate): "Le ticket JIRA-4521 concerne l'API REST" ->
    ['le', 'ticket', 'jira', '4521', 'concerne', 'l', 'api', 'rest'].
    """
    return _TOKEN_PATTERN.findall(text.lower())


def light_french_tokenizer(texts: list[str]) -> list[list[str]]:
    """Tokenize a list of texts into a list of token lists.

    Applied identically at index time and query time (same transformation on
    both sides). Accent-folds first, then lowercases and splits on
    non-alphanumerics. No stemming, no stopwords.
    """
    return [_split_alnum(_fold_accents(t)) for t in texts]
