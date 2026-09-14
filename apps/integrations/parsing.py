import re

ISSUE_REF_RE = re.compile(r"#(\d+)\b")


def extract_issue_ids(*texts):
    """Bare '#<id>' references only (GitHub-native style, e.g. 'fixes #42') —
    no 'fixes'/'closes' keyword required, matching the confirmed product decision."""
    ids = set()
    for text in texts:
        if text:
            ids.update(int(match) for match in ISSUE_REF_RE.findall(text))
    return ids
