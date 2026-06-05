"""GT evaluation harness — comments.md based (Phase 7, req 3).

This is the ONLY module in the package permitted to read
`standard inspection GT data/`. The package __init__.py installs a sys.audit
hook that aborts open() of that directory from any module whose __name__ does
not contain "eval_harness". Keep ALL GT reads (every per-case comments.md)
inside this file — the parser runs here so the audit-hook frame check passes.

No OCR libraries are imported here (C1). GT parsing is pure-Python markdown
regex parsing of each case's comments.md (the reviewer's actual annotation
clean-up of the original PDF mark-ups).

Public API
----------
    list_cases(work_dir)                           -> [case_id, ...]
    gt_comments_for(case_id, work_dir)             -> Path (case comments.md)
    parse_comments(case_id, work_dir)              -> [issue, ...]
    load_predictions(case_id, cache_root)          -> [prediction, ...]
    match_case(gt_issues, predictions)             -> per-case match dict
    evaluate(case_ids, work_dir, cache_root,
             stamp="latest")                       -> aggregate dict

A GT "issue" is a page×topic cluster:
    {issue_id, pages: set[int], topic_tokens: set[str], text: str}

Metrics (content + page centred — comments.md carries no category/severity
enum):
    recall    = hits / GT-issue total      (every reviewer issue covered)
    precision = matched_predictions / prediction total
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# --------------------------------------------------------------------------- #
# GT location (kept here so no other module names the GT directory — C4)
# --------------------------------------------------------------------------- #

_GT_DIRNAME = "standard inspection GT data"
_COMMENTS_FILENAME = "comments.md"


def gt_comments_for(case_id: str, work_dir: Path) -> Path:
    """Return the canonical comments.md path for a case under the work dir.

    The literal GT directory name lives ONLY in this module (C4); callers ask
    eval_harness for the path instead of constructing it themselves. The read
    must happen from inside eval_harness so the audit hook permits it.
    """
    return Path(work_dir) / _GT_DIRNAME / str(case_id) / _COMMENTS_FILENAME


def list_cases(work_dir: Path) -> list[str]:
    """Discover case ids = sub-folders of the GT data dir that hold comments.md.

    Folder names may be plain ('4') or compound ('30 & 31', '47 & 48'); they are
    returned verbatim so they line up with the on-disk cache folder names.
    """
    gt_dir = Path(work_dir) / _GT_DIRNAME
    if not gt_dir.exists():
        return []
    cases = [
        p.name
        for p in gt_dir.iterdir()
        if p.is_dir() and (p / _COMMENTS_FILENAME).exists()
    ]
    return sorted(cases, key=_case_sort_key)


def _case_sort_key(name: str):
    """Sort '4', '7', '10', ..., '30 & 31', '47 & 48' deterministically."""
    head = name.split("&")[0].strip()
    try:
        return (int(head), name)
    except ValueError:
        return (10**9, name)


# --------------------------------------------------------------------------- #
# comments.md parsing
# --------------------------------------------------------------------------- #

# Section headers we care about / must stop at.
_SECTION2_RE = re.compile(r"^##\s+2\.")            # '## 2. 기타 PDF' -> stop main certs
_SECTION3_RE = re.compile(r"^##\s+3\.")            # '## 3. 이메일 회신' -> stop
_MARKING_RE = re.compile(r"^\*\*마킹/하이라이트")  # text-less markings -> ignore block
_TEXTBLOCK_HDR_RE = re.compile(r"^\*\*텍스트 코멘트")

# A comment line:
#   - **p.3** [FreeText] `mingu.jang` — 텍스트 상자: <inline>
#   - **p.3** [FreeText] `mingu.jang`: <inline>
#   - **p.3** [FreeText] `mingu.jang` — 설명선
# Capture page and whatever trails the author backtick on the same line.
_COMMENT_RE = re.compile(
    r"^-\s+\*\*p\.?\s*(?P<page>\d+)\*\*"          # **p.N**
    r"(?:\s*\[[^\]]*\])?"                          # optional [Type]
    r"(?:\s*`[^`]*`)?"                             # optional `author`
    r"\s*(?P<rest>.*)$"                            # trailing text (may be empty)
)
_FENCE_RE = re.compile(r"^\s*```")

# Label prefixes that introduce content after the author (NOT content by
# themselves). When the label stands alone the real text follows in a fence.
_LABELS = ("텍스트 상자", "설명선", "메모", "memo")

# Pure-noise phrases (reviewer housekeeping, not a substantive finding).
_NOISE_EXACT = {
    "삭제 요청", "삭제요청", "삭제", "typo", "텍스트 상자", "설명선",
    "메모", "memo", "참고", "please explain", "check the value",
    "확인", "확인요청", "확인 요청", "확인 바람", "해당 자재", "해당자재",
    "현재", "참조", "재발행", "재발행 요청",
}

# Vague-request phrasing that carries no finding by itself ("X 확인 요청").
_VAGUE_REQUEST_RE = re.compile(
    r"(please\s+explain|check\s+the\s+value|확인\s*(요청|바랍|요망|바람)|"
    r"참조\s*(바랍|요망|바람)|검토\s*(부탁|바랍|요청)|재발행\s*요청|부탁\s*드립)",
    re.IGNORECASE,
)
# Keywords that mark a genuine non-conformity (kept even if phrasing is short).
_FINDING_KW_RE = re.compile(
    r"(불일치|누락|미\s*표시|미수행|미기재|미입력|미표기|초과|미달|미만|오류|오기|"
    r"상이|불만족|불만|부적합|없음|결여|확인\s*불가|불가|중복|미언급|틀림|"
    r"missing|exceed|below|above|non-?conform|fail|overlap|duplicate|"
    r"required|require(?:ment)?|not\s+mentioned|less\s+than|wrong|incorrect|"
    r"out\s+of\s+(?:range|spec))",
    re.IGNORECASE,
)


def _strip_lead(rest: str) -> str:
    """Strip a leading em-dash / colon / label prefix from a comment tail.

    '— 텍스트 상자: foo' -> 'foo'; '— 설명선' -> ''; ': Typo' -> 'Typo';
    '— ??? please explain' -> '??? please explain'.
    """
    s = rest.strip()
    # leading em-dash or hyphen separator
    s = re.sub(r"^[—\-–]+\s*", "", s).strip()
    # a label optionally followed by ':' and inline content
    for lab in _LABELS:
        if s.lower().startswith(lab.lower()):
            tail = s[len(lab):].lstrip()
            if tail.startswith(":") or tail.startswith("："):
                return tail[1:].strip()
            # bare label -> no inline content on this line
            return ""
    # leading colon form ('`author`: text')
    s = re.sub(r"^[:：]\s*", "", s).strip()
    return s


def _is_noise(text: str) -> bool:
    """True if the comment text carries no substantive review content.

    Drops reviewer housekeeping ('삭제 요청'), content-free margin scribbles
    ('??? please explain', 'check the value'), and bare vague requests
    ('확인 요청') — none of which name an actionable finding. A note that
    carries a finding keyword (불일치/누락/미표시…) or a domain token is kept.
    """
    t = text.strip()
    if not t:
        return True
    low = t.lower().strip("?？.,。 ")
    if low in _NOISE_EXACT:
        return True
    # Author-name-only / e-mail-only residue.
    if re.fullmatch(r"[A-Za-z]+\.[A-Za-z]+", t):
        return True
    # Explicit finding keyword or a domain token -> substantive, keep.
    if _FINDING_KW_RE.search(t) or _key_tokens(t):
        return False
    # Strip vague-request phrasing; if nothing substantive remains, it is noise.
    core = _VAGUE_REQUEST_RE.sub(" ", t)
    core = re.sub(r"[?？.,。\-–—:：\s]+", "", core)
    if len(core) < 6:
        return True
    return False


def _dedup_key(text: str) -> str:
    """Normalised key for collapsing identical repeated comments."""
    return re.sub(r"[^0-9a-z가-힣]", "", text.lower())


def _parse_raw_comments(text: str) -> list[tuple[int, str]]:
    """Extract (page, comment_text) tuples from a comments.md body.

    Only the '## 1. 성적서별 ...' region is consulted; '## 2.' (기타 PDF) and
    '## 3.' (이메일) are reference-only and skipped. The '마킹/하이라이트
    (텍스트 없음)' blocks (text-less markings) are skipped. Noise phrases
    (삭제 요청, bare labels, author names) are filtered.
    """
    lines = text.splitlines()
    out: list[tuple[int, str]] = []
    in_marking = False          # inside a text-less markings block
    stopped = False             # past section 2/3
    i = 0
    n = len(lines)

    while i < n:
        line = lines[i]

        if _SECTION2_RE.match(line) or _SECTION3_RE.match(line):
            stopped = True
        if stopped:
            i += 1
            continue

        if _MARKING_RE.match(line):
            in_marking = True
            i += 1
            continue
        if _TEXTBLOCK_HDR_RE.match(line):
            in_marking = False
            i += 1
            continue
        # A new cert section header re-enables comment capture.
        if line.startswith("### "):
            in_marking = False
            i += 1
            continue

        if in_marking:
            i += 1
            continue

        m = _COMMENT_RE.match(line)
        if not m:
            i += 1
            continue

        page = int(m.group("page"))
        inline = _strip_lead(m.group("rest"))

        # Collect a following fenced block, if present, as the comment body.
        fenced: list[str] = []
        j = i + 1
        # skip blank lines between the comment line and an opening fence
        while j < n and lines[j].strip() == "" and not _FENCE_RE.match(lines[j]):
            # a blank line ends a loose comment; but allow an immediately
            # following fence (common pattern), so peek ahead once.
            nxt = j + 1
            if nxt < n and _FENCE_RE.match(lines[nxt]):
                j = nxt
                break
            break
        if j < n and _FENCE_RE.match(lines[j]):
            j += 1
            while j < n and not _FENCE_RE.match(lines[j]):
                fenced.append(lines[j])
                j += 1
            if j < n and _FENCE_RE.match(lines[j]):
                j += 1  # consume closing fence
            i = j
        else:
            i = i + 1

        body = inline
        if fenced:
            fenced_text = " ".join(s.strip() for s in fenced if s.strip())
            body = (inline + " " + fenced_text).strip() if inline else fenced_text

        body = body.strip()
        if not _is_noise(body):
            out.append((page, body))

    return out


# E-mail reply section ('## 3. 이메일 회신 내역'): for many cases the reviewer
# raised the non-conformity by e-mail rather than as a PDF annotation, so the
# real GT lives here. Extract the substantive body of each e-mail (one concern
# per e-mail); drop headers/greetings/signatures and bodies with no domain
# token (generic "성적서 확인 요청" mails carry no finding).
_EMAIL_META_RE = re.compile(
    r"^\s*(?:\*\*)?\s*(?:수신|발신|보낸\s*사람|받는\s*사람|참조|첨부|제목|일시|"
    r"From|To|Cc|Bcc|Sent|Date|Subject|Project|Supplier|Manufacturer)\b",
    re.IGNORECASE,
)
_EMAIL_DROP_SUB = re.compile(r"\[cid:[^\]]*\]|image\d+\.\w+|<[^>]*>|https?://\S+|[\w.\-]+@[\w.\-]+")


def _parse_email_comments(text: str) -> list[tuple[int | None, str]]:
    """Extract (page|None, body) issues from the '## 3. 이메일 회신 내역' section."""
    lines = text.splitlines()
    start = next((idx for idx, ln in enumerate(lines) if _SECTION3_RE.match(ln)), None)
    if start is None:
        return []

    out: list[tuple[int | None, str]] = []
    buf: list[str] = []

    def _flush() -> None:
        if not buf:
            return
        body = " ".join(buf).strip()
        buf.clear()
        if len(body) < 6:
            return
        # One issue per e-mail. Require either a stated non-conformity (finding
        # keyword) or a concrete domain token, so pure cover/greeting mails that
        # carry neither are dropped while real reported findings are kept.
        if not (_FINDING_KW_RE.search(body) or _key_tokens(body)):
            return
        pm = re.search(r"p\.?\s*(\d+)", body, re.IGNORECASE)
        out.append((int(pm.group(1)) if pm else None, body))

    i, n = start + 1, len(lines)
    while i < n:
        ln = lines[i]
        if ln.startswith("### "):          # new e-mail -> flush previous body
            _flush()
            i += 1
            continue
        if _FENCE_RE.match(ln):            # fenced e-mail body
            i += 1
            while i < n and not _FENCE_RE.match(lines[i]):
                raw = lines[i]
                clean = _EMAIL_DROP_SUB.sub("", raw).strip(" *-–—•·\t")
                # Keep substantive lines; drop only header/metadata lines. A
                # purely-greeting e-mail is filtered later by the body-level
                # _key_tokens check, so we don't drop greeting LINES here (the
                # real finding often shares a line with a polite request).
                if clean and not _EMAIL_META_RE.match(raw):
                    buf.append(clean)
                i += 1
            if i < n:
                i += 1                      # consume closing fence
            _flush()                        # one issue per e-mail body
            continue
        i += 1
    _flush()
    return out


# --------------------------------------------------------------------------- #
# Topic clustering (DD1 = page × topic)
# --------------------------------------------------------------------------- #


def parse_comments(case_id: str, work_dir: Path) -> list[dict]:
    """Parse a case's comments.md into clustered review issues.

    Steps:
      1. extract (page, text) comments (markings + noise excluded);
      2. cluster by TOPIC SIGNATURE (shared key tokens via _key_tokens). When
         the same topic recurs across pages — the reviewer repeats one
         requirement on p.3, p.4, p.5, ... — those page-comments collapse into a
         SINGLE issue spanning all the pages.

    Returns a list of issues:
        {issue_id, pages: set[int], topic_tokens: set[str], text: str}
    where ``text`` is a representative (longest) phrasing of the cluster.
    """
    path = gt_comments_for(case_id, work_dir)
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    # GT source: the reviewer's PDF annotations ('## 1') when present; otherwise
    # the non-conformity they raised by e-mail ('## 3'). Using e-mails only as a
    # FALLBACK keeps annotation-rich cases clean (a manufacturer reply e-mail
    # must not pollute a real annotation issue via topic clustering).
    raw = _parse_raw_comments(text)
    if not raw:
        raw = _parse_email_comments(text)

    clusters: list[dict] = []
    for page, body in raw:
        sig = _key_tokens(body)
        dk = _dedup_key(body)
        target: dict | None = None
        for c in clusters:
            # (a) identical repeated comment — the reviewer stamped the SAME
            #     finding on many pages (e.g. 'Item No 불일치' on p.2..16).
            if dk and dk in c["_dks"]:
                target = c
                break
            # (b) shared topic signature.
            if sig and (c["topic_tokens"] & sig):
                target = c
                break
        if target is None:
            clusters.append({
                "pages": {page},
                "topic_tokens": set(sig),
                "_texts": [body],
                "_dks": {dk} if dk else set(),
            })
        else:
            target["pages"].add(page)
            target["topic_tokens"] |= sig
            target["_texts"].append(body)
            if dk:
                target["_dks"].add(dk)

    issues: list[dict] = []
    for k, c in enumerate(clusters, start=1):
        rep = max(c["_texts"], key=len) if c["_texts"] else ""
        issues.append({
            "issue_id": f"G{case_id}-{k}",
            "pages": set(c["pages"]),
            "topic_tokens": set(c["topic_tokens"]),
            "text": rep,
        })
    return issues


# --------------------------------------------------------------------------- #
# Prediction loading (compliance review.json findings)
# --------------------------------------------------------------------------- #


def load_predictions(case_id: str, cache_root: Path) -> list[dict]:
    """Load prediction findings for a case from the compliance review output.

    Priority:
      1. <cache_root>/<case_id>/<case_id>_review.json  (findings[] / materials[])
      2. <cache_root>/<case_id>/<case_id>_findings.json (back-compat)

    Returns [] if neither exists. Each prediction is normalised to at least
    {issue_summary, page_ref, material_grade}; the material_grade falls back to
    the case's materials[] grade when a finding does not carry one.
    """
    base = Path(cache_root) / str(case_id)
    review_path = base / f"{case_id}_review.json"
    findings_path = base / f"{case_id}_findings.json"

    if review_path.exists():
        data = json.loads(review_path.read_text(encoding="utf-8"))
        return _predictions_from_review(data)
    if findings_path.exists():
        data = json.loads(findings_path.read_text(encoding="utf-8"))
        findings = data.get("findings")
        out: list[dict] = []
        if isinstance(findings, list):
            for k, f in enumerate(findings, start=1):
                out.append(_norm_prediction(f, k, None))
        return out
    return []


def _predictions_from_review(data: dict) -> list[dict]:
    """Map a compliance review.json into normalised prediction findings.

    review.json findings carry {no, severity, category, location, content,
    action}; the single (or first) material's grade is used as the default
    material_grade when a finding does not embed one.
    """
    materials = data.get("materials") or []
    default_grade = None
    if materials:
        m0 = materials[0]
        default_grade = m0.get("grade_spec") or m0.get("grade_cert")

    out: list[dict] = []
    for k, f in enumerate(data.get("findings") or [], start=1):
        out.append(_norm_prediction(f, k, default_grade))
    return out


_PRED_PAGE_RE = re.compile(r"(?:p\.?|page|페이지|페)\s*(\d+(?:\s*[-~]\s*\d+)?)", re.IGNORECASE)
_BARE_PAGE_RE = re.compile(r"^\s*\d+(?:\s*[-~]\s*\d+)?\s*$")


def _extract_page(*candidates) -> str:
    """Pull an explicit page token ('p.N' / 'page N' / a bare numeric ref) out
    of a finding's page_ref/location. A verbose textual location ('성적서 N.D.E
    칸 / ... Heat S85072') yields '' so the page gate is skipped rather than
    misreading embedded heat/size digits as page numbers."""
    for c in candidates:
        if not c:
            continue
        s = str(c)
        if _BARE_PAGE_RE.match(s):
            return s.strip()
        m = _PRED_PAGE_RE.search(s)
        if m:
            return "p." + re.sub(r"\s+", "", m.group(1))
    return ""


def _norm_prediction(f: dict, idx: int, default_grade: str | None) -> dict:
    """Normalise a raw finding dict to the prediction shape used by matching."""
    fid = f.get("finding_id") or (f"P{f['no']}" if f.get("no") is not None else f"P#{idx}")
    # issue_summary: prefer an explicit field, else the review 'content'/'category'.
    summary = (
        f.get("issue_summary")
        or f.get("content")
        or f.get("category")
        or ""
    )
    # page_ref: an explicit 'p.N' token only; a verbose textual location yields
    # '' so embedded heat/size digits are not misread as page numbers.
    page_ref = _extract_page(f.get("page_ref"), f.get("location"))
    grade = f.get("material_grade") or default_grade
    return {
        "finding_id": str(fid),
        "issue_summary": summary,
        "page_ref": page_ref,
        "material_grade": grade,
    }


# --------------------------------------------------------------------------- #
# Matching primitives (content + page; reused semantic helpers)
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
_PAGE_RE = re.compile(r"(?:p\.?\s*)?(\d+)(?:\s*[-~]\s*(\d+))?", re.IGNORECASE)
_GRADE_KEY_TOKEN_RE = re.compile(
    r"WP\d+|GR[ABC]|A\d{3}|2H|B7|P\d+|F\d+", re.IGNORECASE
)


def _norm_grade(grade: str | None) -> str:
    if grade is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", grade).upper()


def _grade_tokens(grade: str | None) -> set[str]:
    if grade is None:
        return set()
    norm = _norm_grade(grade)
    if not norm:
        return set()
    toks = {m.group(0).upper() for m in _GRADE_KEY_TOKEN_RE.finditer(norm)}
    m = re.search(r"\d([ABC])$", norm)
    if m:
        toks.add("GR" + m.group(1))
    return toks


def _grade_match(gt_grade: str | None, cert_grade: str | None) -> bool:
    """material_grade match. Either side null -> match (unconstrained)."""
    if gt_grade is None or cert_grade is None:
        return True
    a = _norm_grade(gt_grade)
    b = _norm_grade(cert_grade)
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return bool(_grade_tokens(gt_grade) & _grade_tokens(cert_grade))


def _pages(page_ref) -> set[int]:
    """Parse 'p.5', 'p.5-6', 'p.5~6', 'p.1, p.3', a bare int/str, or a set."""
    if isinstance(page_ref, (set, list, tuple)):
        out: set[int] = set()
        for p in page_ref:
            out |= _pages(p)
        return out
    if not page_ref and page_ref != 0:
        return set()
    page_ref = str(page_ref)
    out = set()
    for m in _PAGE_RE.finditer(page_ref):
        start = int(m.group(1))
        if m.group(2):
            end = int(m.group(2))
            lo, hi = (start, end) if start <= end else (end, start)
            out.update(range(lo, hi + 1))
        else:
            out.add(start)
    return out


def _page_match(gt_ref, cert_ref) -> bool:
    """Page-number overlap, enforced ONLY when both sides cite a page.

    - GT has no page constraint -> skip (True).
    - Prediction carries no parseable page (its 'location' is a textual field
      reference like '성적서 N.D.E 칸') -> do NOT penalize; let content/grade
      gate the match. A correct finding that omits the exact page number must
      not be scored as a miss.
    - Both cite pages -> require a non-empty page-set intersection.
    """
    gt_pages = _pages(gt_ref)
    if not gt_pages:
        return True
    cert_pages = _pages(cert_ref)
    if not cert_pages:
        return True
    return bool(gt_pages & cert_pages)


def _tokens(s: str | None) -> set[str]:
    if not s:
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(s)}


_WS_RE = re.compile(r"\s+")


def _char_trigrams(s: str | None) -> set[str]:
    if not s:
        return set()
    t = _WS_RE.sub("", s.lower())
    if len(t) < 3:
        return {t} if t else set()
    return {t[i:i + 3] for i in range(len(t) - 2)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# --- key tokens for the semantic content_related predicate --------------- #
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_ELEMENT_SYMBOLS = {
    "c", "mn", "si", "p", "s", "cr", "mo", "ni", "v", "nb", "n", "al", "cu",
    "b", "ti", "zr", "w", "pb", "sn", "as", "sb", "bi",
}
_DOMAIN_PHRASES = ("delta ferrite", "n/al", "code case")
_DOMAIN_WORDS = {
    "ferrite", "mt", "pt", "ut", "rt", "nde", "heat", "pb", "cef", "cev",
    "normalizing", "tempering", "hardness", "tensile", "yield",
    "elongation", "impact", "microstructure", "thickness", "quantity",
    "dimension", "material", "heattreatment", "lead", "mtr",
}
_KO_SYNONYMS = {
    "인장": "tensile", "항복": "yield", "경도": "hardness", "충격": "impact",
    "연신": "elongation", "두께": "thickness", "열처리": "heattreatment",
    "미세조직": "microstructure", "페라이트": "ferrite", "수량": "quantity",
    "치수": "dimension", "재질": "material", "노멀라이": "normalizing",
    "템퍼": "tempering",
}


def _key_tokens(s: str | None) -> set[str]:
    """Extract KEY tokens (topic signature) from a comment/finding text.

    Key tokens = decimal/multi-digit numbers, element symbols, and domain
    keywords (incl. multi-word phrases) + Korean->English canonical terms.
    Lowercased; phrases keep their internal space.
    """
    if not s:
        return set()
    low = s.lower()
    keys: set[str] = set()
    for num in _NUM_RE.findall(low):
        if "." in num or len(num) >= 2:
            keys.add(num)
    for t in _TOKEN_RE.findall(low):
        if t in _ELEMENT_SYMBOLS or t in _DOMAIN_WORDS:
            keys.add(t)
    for phrase in _DOMAIN_PHRASES:
        if phrase in low:
            keys.add(phrase)
    for ko, en in _KO_SYNONYMS.items():
        if ko in s:
            keys.add(en)
    return keys


def _content_match(gt_summary: str | None, cert_summary: str | None) -> tuple[bool, float]:
    """content_related: token Jaccard >= 0.2 OR a shared KEY token, with
    GT-coverage and char-trigram fallbacks. Returns (passed, jaccard_score)."""
    gt_t = _tokens(gt_summary)
    cf_t = _tokens(cert_summary)
    score = _jaccard(gt_t, cf_t)
    if score >= 0.2:
        return True, score
    if _key_tokens(gt_summary) & _key_tokens(cert_summary):
        return True, score
    if gt_t and len(gt_t & cf_t) / len(gt_t) >= 0.55:
        return True, score
    gt_g = _char_trigrams(gt_summary)
    cf_g = _char_trigrams(cert_summary)
    if gt_g and len(gt_g & cf_g) / len(gt_g) >= 0.6:
        return True, score
    return False, score


# --------------------------------------------------------------------------- #
# Per-case matching
# --------------------------------------------------------------------------- #


def match_case(gt_issues: list[dict], predictions: list[dict]) -> dict:
    """Match clustered GT issues against prediction findings.

    A GT issue G is a HIT iff SOME prediction P satisfies BOTH:
      1. content_related(G.text, P.issue_summary)  (_content_match: token
         Jaccard >= 0.2 OR a shared KEY/topic token)
      2. page overlap                              (G.pages vs P.page_ref;
         skipped when G has no page constraint)

    comments.md has no category/severity enum, so matching is content + page
    centred. material_grade is a DIAGNOSTIC dimension only (it does not gate),
    matching the reviewer reality that a comment may name no grade.

    Greedy one-to-one assignment: each prediction satisfies at most one GT
    issue. Returns hit/miss ids, precision bookkeeping, and a diagnostic rubric.
    """
    matched_gt_ids: list[str] = []
    unmatched_gt_ids: list[str] = []
    matched_pred_idx: set[int] = set()

    rub = {"grade": 0, "page": 0, "content": 0}
    gt_total = len(gt_issues)

    for gi in gt_issues:
        gi_id = gi.get("issue_id", "<gt>")
        gt_pages = gi.get("pages")
        gt_text = gi.get("text")

        best_idx: int | None = None
        best_score = -1.0
        diag_best = {"grade": 0, "page": 0, "content_ok": 0, "content_score": -1.0}

        for idx, pf in enumerate(predictions):
            pf_grade = pf.get("material_grade")
            pf_page = pf.get("page_ref")
            pf_summary = pf.get("issue_summary")

            content_ok, content_score = _content_match(gt_text, pf_summary)
            page_ok = _page_match(gt_pages, pf_page)

            if content_score > diag_best["content_score"]:
                diag_best = {
                    "grade": 1 if _grade_match(None, pf_grade) else 0,
                    "page": 1 if page_ok else 0,
                    "content_ok": 1 if content_ok else 0,
                    "content_score": content_score,
                }

            if idx in matched_pred_idx:
                continue

            if content_ok and page_ok:
                if content_score > best_score:
                    best_score = content_score
                    best_idx = idx

        rub["grade"] += diag_best["grade"]
        rub["page"] += diag_best["page"]
        rub["content"] += diag_best["content_ok"]

        if best_idx is not None:
            matched_pred_idx.add(best_idx)
            matched_gt_ids.append(gi_id)
        else:
            unmatched_gt_ids.append(gi_id)

    pred_total = len(predictions)
    matched_pred_sorted = sorted(matched_pred_idx)
    extra_pred_ids = [
        predictions[i].get("finding_id", f"<pred#{i}>")
        for i in range(pred_total)
        if i not in matched_pred_idx
    ]

    def _ratio(n: int) -> float:
        return (n / gt_total) if gt_total else 1.0

    rubric = {
        "grade": _ratio(rub["grade"]),
        "page": _ratio(rub["page"]),
        "content": _ratio(rub["content"]),
    }

    return {
        "hits": len(matched_gt_ids),
        "gt_total": gt_total,
        "matched_gt_ids": matched_gt_ids,
        "unmatched_gt_ids": unmatched_gt_ids,
        "cert_total": pred_total,
        "matched_cert_ids": [
            predictions[i].get("finding_id", f"<pred#{i}>") for i in matched_pred_sorted
        ],
        "extra_cert_ids": extra_pred_ids,
        "rubric": rubric,
    }


# --------------------------------------------------------------------------- #
# Aggregate evaluation
# --------------------------------------------------------------------------- #


def evaluate(
    case_ids: list[str],
    work_dir: Path,
    cache_root: Path,
    stamp: str = "latest",
) -> dict:
    """Aggregate GT evaluation across cases (comments.md based).

    Metrics:
      recall    = total_hits / total_gt_issues
      precision = total_matched_pred / total_pred
      case_pass = #cases where every GT issue is hit

    Writes output/eval/eval_report_<stamp>.{md,json}. The stamp is an argument;
    this function never reads wall-clock time. Each case's comments.md is read
    here (inside eval_harness) via parse_comments, satisfying the input guard.
    """
    work_dir = Path(work_dir)
    cache_root = Path(cache_root)

    per_case: list[dict] = []
    gt_index: dict[str, dict[str, dict]] = {}
    total_gt = 0
    total_hits = 0
    total_pred = 0
    total_matched_pred = 0
    case_pass_count = 0

    for case_id in case_ids:
        gt_issues = parse_comments(case_id, work_dir)
        predictions = load_predictions(case_id, cache_root)
        gt_index[case_id] = {gi["issue_id"]: gi for gi in gt_issues}

        m = match_case(gt_issues, predictions)
        full_hit = (m["gt_total"] == 0) or (m["hits"] == m["gt_total"])
        if full_hit:
            case_pass_count += 1

        total_gt += m["gt_total"]
        total_hits += m["hits"]
        total_pred += m["cert_total"]
        total_matched_pred += len(m["matched_cert_ids"])

        per_case.append({
            "case_id": case_id,
            "full_hit": full_hit,
            **m,
        })

    recall = (total_hits / total_gt) if total_gt else 1.0
    precision = (total_matched_pred / total_pred) if total_pred else 1.0
    n_cases = len(case_ids)
    passed = recall == 1.0 and case_pass_count == n_cases

    aggregate = {
        "stamp": stamp,
        "n_cases": n_cases,
        "case_ids": list(case_ids),
        "total_gt": total_gt,
        "total_hits": total_hits,
        "total_cert": total_pred,
        "total_matched_cert": total_matched_pred,
        "recall": recall,
        "precision": precision,
        "case_pass_count": case_pass_count,
        "pass": passed,
        "verdict": "PASS" if passed else "FAIL",
        "per_case": per_case,
    }

    out_dir = work_dir / "output" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"eval_report_{stamp}.json"
    md_path = out_dir / f"eval_report_{stamp}.md"

    json_path.write_text(
        json.dumps(_jsonable(aggregate), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(_render_md(aggregate, gt_index), encoding="utf-8")

    aggregate["report_md"] = str(md_path)
    aggregate["report_json"] = str(json_path)
    return aggregate


def _jsonable(obj):
    """Recursively convert sets to sorted lists for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, set):
        return sorted(obj)
    return obj


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _render_md(agg: dict, gt_index: dict[str, dict[str, dict]]) -> str:
    """Render the markdown eval report (comments.md based)."""
    lines: list[str] = []
    verdict = agg["verdict"]
    lines.append("# GT 평가 리포트 (Standard Inspection, comments.md 기반)")
    lines.append("")
    lines.append(f"- stamp: `{agg['stamp']}`")
    lines.append(f"- 평가 케이스 수: {agg['n_cases']}")
    lines.append("")
    lines.append(f"## 종합: {verdict}")
    lines.append("")

    lines.append("### 핵심 지표")
    lines.append("")
    lines.append("| 지표 | 값 | 목표 | 충족 |")
    lines.append("|---|---|---|---|")
    recall_ok = agg["recall"] == 1.0
    casepass_ok = agg["case_pass_count"] == agg["n_cases"]
    lines.append(
        f"| recall | {agg['total_hits']}/{agg['total_gt']} = {_fmt_pct(agg['recall'])} "
        f"| 100% | {'O' if recall_ok else 'X'} |"
    )
    lines.append(
        f"| case_pass | {agg['case_pass_count']}/{agg['n_cases']} "
        f"| {agg['n_cases']}/{agg['n_cases']} | {'O' if casepass_ok else 'X'} |"
    )
    lines.append(
        f"| precision | {agg['total_matched_cert']}/{agg['total_cert']} = {_fmt_pct(agg['precision'])} "
        f"| (참고) | — |"
    )
    lines.append("")
    lines.append(
        f"**PASS 판정**: recall==1.0 ({'O' if recall_ok else 'X'}) AND "
        f"case_pass==전체 ({'O' if casepass_ok else 'X'}) => **{verdict}**"
    )
    lines.append("")

    # Missing GT issues per case.
    lines.append("## 누락(미매칭) GT 지적사항 (per case)")
    lines.append("")
    any_missing = False
    for pc in agg["per_case"]:
        if pc["unmatched_gt_ids"]:
            any_missing = True
            lines.append(f"### Case {pc['case_id']} — 누락 {len(pc['unmatched_gt_ids'])}건")
            lines.append("")
            idx = gt_index.get(pc["case_id"], {})
            for gid in pc["unmatched_gt_ids"]:
                gi = idx.get(gid, {})
                pages = ", ".join(
                    f"p.{p}" for p in sorted(x for x in gi.get("pages", set()) if x is not None)
                )
                txt = (gi.get("text", "") or "").strip().replace("\n", " ")
                if len(txt) > 120:
                    txt = txt[:117] + "..."
                lines.append(f"- `{gid}` [{pages}] {txt}")
            lines.append("")
    if not any_missing:
        lines.append("- (없음) 모든 GT 지적사항이 매칭됨.")
        lines.append("")

    # Extra predictions per case.
    lines.append("## 초과(매칭 안 된) 예측 지적사항 (per case)")
    lines.append("")
    any_extra = False
    for pc in agg["per_case"]:
        if pc["extra_cert_ids"]:
            any_extra = True
            lines.append(f"### Case {pc['case_id']} — 초과 {len(pc['extra_cert_ids'])}건")
            lines.append("")
            for fid in pc["extra_cert_ids"]:
                lines.append(f"- `{fid}`")
            lines.append("")
    if not any_extra:
        lines.append("- (없음) 모든 예측 지적사항이 GT에 매칭됨.")
        lines.append("")

    # Per-case rubric diagnostic table.
    lines.append("## 진단용 루브릭 (DIAGNOSTIC ONLY)")
    lines.append("")
    lines.append(
        "> 주의: 아래 루브릭(grade/page/content 일치 비율)은 진단 목적의 참고 "
        "지표일 뿐이며, PASS 판정에는 recall==1.0 과 case_pass==전체 만 사용된다."
    )
    lines.append("")
    lines.append("| case | GT | hits | pred | grade | page | content |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for pc in agg["per_case"]:
        r = pc["rubric"]
        lines.append(
            f"| {pc['case_id']} | {pc['gt_total']} | {pc['hits']} | {pc['cert_total']} "
            f"| {_fmt_pct(r['grade'])} | {_fmt_pct(r['page'])} | {_fmt_pct(r['content'])} |"
        )
    lines.append("")

    return "\n".join(lines) + "\n"


__all__ = [
    "list_cases",
    "gt_comments_for",
    "parse_comments",
    "load_predictions",
    "match_case",
    "evaluate",
]
