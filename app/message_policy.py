"""Conservative text handling: never erase numbers, punctuation or word boundaries."""
import difflib
import unicodedata


def text_key(text):
    return " ".join(text.strip().split())


def is_chinese_only(text):
    letters = [char for char in text if char.isalpha()]
    return bool(letters) and all(
        unicodedata.name(char, "").startswith(("CJK UNIFIED", "CJK COMPATIBILITY"))
        for char in letters
    )


class OcrFrameTracker:
    """Match exact lines in adjacent OCR frames, including scroll overlap.

    Occurrences are matched one-to-one, so a second identical visible line is
    still a new message. No fuzzy comparison or session-wide text suppression.
    """
    def __init__(self):
        self.previous = []

    def reset(self):
        self.previous = []

    def new_indices(self, texts):
        current = [text_key(text) for text in texts]
        matcher = difflib.SequenceMatcher(None, self.previous, current, autojunk=False)
        matched = set()
        for block in matcher.get_matching_blocks():
            matched.update(range(block.b, block.b + block.size))
        self.previous = current
        return [index for index in range(len(current)) if index not in matched]
