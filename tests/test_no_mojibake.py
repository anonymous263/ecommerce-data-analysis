import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

TEXT_SUFFIXES = {
    ".md",
    ".py",
    ".yml",
    ".yaml",
    ".sql",
    ".csv",
    ".txt",
    ".env",
    ".example",
    ".gitignore",
}

EXCLUDED_DIR_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "dbt_packages",
    "target",
    "logs",
    "data/raw",
    "data\\raw",
}

MOJIBAKE_PATTERNS = [
    "\u00e2\u20ac\u201d",
    "\u00e2\u2020\u2019",
    "\u00e2\u2030\u00a4",
    "\u00e2\u2030\u00a5",
    "\u00c2\u00a7",
    "\u00e1\u00bb",
    "\u00c6\u00b0",
]

# Mojibake happens when UTF-8 bytes are decoded as cp1252: a lead byte (0xC3-0xC6,
# for the Latin/Vietnamese range) becomes one of these characters, and the
# continuation byte (0x80-0xBF) becomes whatever cp1252 maps it to.
#
# Matching a bare lead character is NOT safe: "\u00c3" is legitimate uppercase
# Vietnamese, as in "\u0110\u00c3 NET" / "\u0110\u00c3 BAO G\u1ed2M". Real mojibake is always the lead
# followed by a continuation character, so we require the pair. Legitimate
# Vietnamese is followed by a space or an ASCII letter, neither of which decodes
# from the 0x80-0xBF range.
MOJIBAKE_LEADS = "\u00c3\u00c4\u00c5\u00c6"
MOJIBAKE_CONTINUATIONS = "".join(
    bytes([b]).decode("cp1252", errors="replace") for b in range(0x80, 0xC0)
)
MOJIBAKE_PAIR_RE = re.compile(
    f"[{re.escape(MOJIBAKE_LEADS)}][{re.escape(MOJIBAKE_CONTINUATIONS)}]"
)


def _is_excluded(path: Path) -> bool:
    relative = str(path.relative_to(PROJECT_ROOT))
    parts = set(path.relative_to(PROJECT_ROOT).parts)

    if parts & EXCLUDED_DIR_PARTS:
        return True

    if relative.startswith("data/raw") or relative.startswith("data\\raw"):
        return True

    return False


def _repo_text_files():
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file():
            continue

        if _is_excluded(path):
            continue

        if path.suffix.lower() in TEXT_SUFFIXES or path.name in {
            ".gitignore",
            ".env.example",
            "requirements.txt",
        }:
            yield path


def test_repo_text_files_do_not_contain_common_mojibake():
    offenders = []

    for path in _repo_text_files():
        text = path.read_text(encoding="utf-8")
        found = [pattern for pattern in MOJIBAKE_PATTERNS if pattern in text]
        found += sorted({match for match in MOJIBAKE_PAIR_RE.findall(text)})
        if found:
            offenders.append(
                f"{path.relative_to(PROJECT_ROOT)} contains mojibake patterns: {found}"
            )

    assert offenders == []


def test_repo_text_files_are_utf8_without_bom():
    offenders = []

    for path in _repo_text_files():
        data = path.read_bytes()

        if data.startswith(b"\xef\xbb\xbf"):
            offenders.append(str(path.relative_to(PROJECT_ROOT)))

        data.decode("utf-8")

    assert offenders == []