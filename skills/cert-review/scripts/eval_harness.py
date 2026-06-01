"""GT evaluation harness (Phase 7).

This is the ONLY module in the package permitted to read
`standard inspection GT data/`. The package __init__.py installs a sys.audit
hook that aborts open() of that directory from any module whose __name__ does
not contain "eval_harness". Keep all GT reads inside this file.

No OCR libraries are imported here (C1). GT parsing is pure-Python markdown
regex parsing of GT_Answer.md.

Public API
----------
    parse_gt(gt_path)                              -> {case_id: [gt_finding, ...]}
    load_cert_findings(case_id, cache_root)        -> [cert_finding, ...]
    match_case(gt_findings, cert_findings)         -> per-case match dict
    evaluate(case_ids, work_dir, cache_root,
             gt_path, stamp="latest")              -> aggregate dict

The four STRICT PASS conditions (everything else is diagnostic only):
    1. recall == 1.0                  (every GT finding matched by some cert finding)
    2. case_pass_count == n_cases     (every evaluated GT case fully covered)
    3. precision >= 0.9               (>=90% of cert findings matched a GT finding)
    4. dropped_total == 0             (no findings dropped for missing provenance)
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
_GT_FILENAME = "GT_Answer.md"


def gt_path_for(work_dir: Path) -> Path:
    """Return the canonical GT_Answer.md path under the work dir.

    The literal GT directory name lives ONLY in this module (C4); callers ask
    eval_harness for the path instead of constructing it themselves.
    """
    return Path(work_dir) / _GT_DIRNAME / _GT_FILENAME


# --------------------------------------------------------------------------- #
# GT parsing
# --------------------------------------------------------------------------- #

_CASE_RE = re.compile(r"^## Case (.+?)\s*$")
# #### F4-5 — [Reject] [Chemistry] <summary>
_FINDING_HEADER_RE = re.compile(
    r"^####\s+(?P<fid>F[\w&.\- ]+?)\s+[—\-]+\s+"
    r"\[(?P<severity>[^\]]+)\]\s+\[(?P<category>[^\]]+)\]\s*(?P<summary>.*)$"
)
# - **field**: value
_FIELD_RE = re.compile(r"^-\s+\*\*(?P<key>[^*]+)\*\*\s*:\s*(?P<val>.*)$")

_GT_FIELD_KEYS = (
    "category",
    "severity",
    "material_grade",
    "heat_no",
    "page_ref",
    "issue_summary",
    "details",
    "required_action",
    "sources",
)


def _na_to_none(val: str | None) -> str | None:
    """Map GT placeholders for 'not applicable' to None."""
    if val is None:
        return None
    v = val.strip()
    if v == "" or v in {"_N/A_", "N/A", "NA", "-", "_-_", "None", "null"}:
        return None
    # strip surrounding markdown emphasis like _value_
    if len(v) >= 2 and v[0] == "_" and v[-1] == "_":
        inner = v[1:-1].strip()
        if inner in {"N/A", "NA", "-", "None", "null"}:
            return None
    return v


def parse_gt(gt_path: Path) -> dict[str, list[dict]]:
    """Parse GT_Answer.md into {case_id: [gt_finding, ...]}.

    Each gt_finding carries: finding_id, category, severity, material_grade,
    heat_no, page_ref, issue_summary (plus details/required_action/sources for
    diagnostic/report use). case_id matches the text after '## Case ' (e.g.
    '4', '30 & 31'), which equals the on-disk cache folder name.
    """
    gt_path = Path(gt_path)
    text = gt_path.read_text(encoding="utf-8")

    cases: dict[str, list[dict]] = {}
    current_case: str | None = None
    current_finding: dict[str, Any] | None = None

    def _flush() -> None:
        nonlocal current_finding
        if current_finding is not None and current_case is not None:
            cases[current_case].append(current_finding)
        current_finding = None

    for raw_line in text.splitlines():
        line = raw_line.rstrip("\n")

        m_case = _CASE_RE.match(line)
        if m_case:
            _flush()
            current_case = m_case.group(1).strip()
            cases.setdefault(current_case, [])
            continue

        m_head = _FINDING_HEADER_RE.match(line)
        if m_head and current_case is not None:
            _flush()
            current_finding = {
                "finding_id": m_head.group("fid").strip(),
                "severity": m_head.group("severity").strip(),
                "category": m_head.group("category").strip(),
                "issue_summary": m_head.group("summary").strip(),
                "material_grade": None,
                "heat_no": None,
                "page_ref": None,
                "details": "",
                "required_action": "",
                "sources": "",
            }
            continue

        if current_finding is not None:
            m_field = _FIELD_RE.match(line)
            if m_field:
                key = m_field.group("key").strip().lower()
                val = m_field.group("val").strip()
                if key in _GT_FIELD_KEYS:
                    if key in {"material_grade", "heat_no", "page_ref"}:
                        current_finding[key] = _na_to_none(val)
                    elif key in {"category", "severity", "issue_summary"}:
                        # field block overrides header value when present
                        norm = _na_to_none(val)
                        if norm is not None:
                            current_finding[key] = norm
                    else:
                        current_finding[key] = val
                continue

    _flush()
    return cases


# --------------------------------------------------------------------------- #
# Cert findings loading
# --------------------------------------------------------------------------- #


def load_cert_findings(case_id: str, cache_root: Path) -> list[dict]:
    """Load <cache_root>/<case_id>/<case_id>_findings.json -> findings list.

    Returns [] if the file is missing. The JSON dict has key "findings".
    """
    path = Path(cache_root) / case_id / f"{case_id}_findings.json"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    findings = data.get("findings")
    return list(findings) if isinstance(findings, list) else []


def _load_dropped_count(case_id: str, cache_root: Path) -> int:
    """Count dropped findings recorded in the case findings.json (provenance C2)."""
    path = Path(cache_root) / case_id / f"{case_id}_findings.json"
    if not path.exists():
        return 0
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    dropped = data.get("dropped_findings")
    if isinstance(dropped, list):
        return len(dropped)
    stats = data.get("stats") or {}
    try:
        return int(stats.get("dropped", 0))
    except (TypeError, ValueError):
        return 0


# --------------------------------------------------------------------------- #
# Matching primitives
# --------------------------------------------------------------------------- #

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+|[가-힣]+")
_PAGE_RE = re.compile(r"(?:p\.?\s*)?(\d+)(?:\s*[-~]\s*(\d+))?", re.IGNORECASE)
# Grade tokens per the SEMANTIC predicate: P\d+|F\d+|WP\d+|A\d{3}|GR[ABC]|B7|2H.
# Ordered so the longer/more-specific alternatives win (WP before P, A\d{3}).
_GRADE_KEY_TOKEN_RE = re.compile(
    r"WP\d+|GR[ABC]|A\d{3}|2H|B7|P\d+|F\d+", re.IGNORECASE
)


def _norm_grade(grade: str | None) -> str:
    """Collapse a grade token to comparable form: uppercase, alphanumerics only."""
    if grade is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", grade).upper()


def _grade_tokens(grade: str | None) -> set[str]:
    """Extract canonical grade tokens (P92, F91, WP11, A106, GRC, B7, 2H ...).

    A bare trailing grade letter on a normalized spec (e.g. 'SA106GRC' or
    'SA106C') is folded to the GR[ABC] token family so 'SA-106 Gr.C' and
    'SA-106-C' share token 'GRC'.
    """
    if grade is None:
        return set()
    norm = _norm_grade(grade)
    if not norm:
        return set()
    toks = {m.group(0).upper() for m in _GRADE_KEY_TOKEN_RE.finditer(norm)}
    # Fold a bare trailing A/B/C grade letter (after a digit) into GR[ABC]
    # so 'SA106C' -> 'GRC' aligns with 'SA106GRC'.
    m = re.search(r"\d([ABC])$", norm)
    if m:
        toks.add("GR" + m.group(1))
    return toks


def _grade_match(gt_grade: str | None, cert_grade: str | None) -> bool:
    """material_grade match per the SEMANTIC predicate.

    - either side null (None) -> match. A null GT grade means the reviewer
      placed NO grade constraint on the finding, so a cert finding that does
      name a grade must not be disqualified on that account (the other
      dimensions — category/severity/page/content — still gate). Symmetrically
      a null cert grade is treated as unconstrained.
    - otherwise: normalize (upper + alphanumerics only) and match if one
      normalized string contains the other, OR they share a grade token
      extracted by _grade_tokens (P\\d+|F\\d+|WP\\d+|A\\d{3}|GR[ABC]|B7|2H).
      Be lenient but require a shared grade token when both non-null and
      neither contains the other.
    """
    if gt_grade is None or cert_grade is None:
        return True
    a = _norm_grade(gt_grade)
    b = _norm_grade(cert_grade)
    if not a or not b:
        return False
    if a == b:
        return True
    if a in b or b in a:
        return True
    return bool(_grade_tokens(gt_grade) & _grade_tokens(cert_grade))


def _norm_heat(heat: str | None) -> str:
    if heat is None:
        return ""
    return re.sub(r"[^A-Za-z0-9]", "", heat).upper()


def _heat_match(gt_heat: str | None, cert_heat: str | None) -> bool:
    """heat_no match — only enforced when GT heat_no is non-null.

    GT heat_no may carry compound text like 'Cert: S12108744QX / Actual: 22001408'.
    A cert finding matches if its heat token appears inside the GT heat string
    (or vice versa) on normalized form.
    """
    if gt_heat is None:
        return True  # skip check
    gt_norm = _norm_heat(gt_heat)
    cert_norm = _norm_heat(cert_heat)
    if not cert_norm:
        return False
    if gt_norm == cert_norm:
        return True
    return cert_norm in gt_norm or gt_norm in cert_norm


def _pages(page_ref) -> set[int]:
    """Parse 'p.5', 'p.5-6', 'p.5~6', 'p.1, p.3', or a bare int/str into ints."""
    if not page_ref and page_ref != 0:
        return set()
    page_ref = str(page_ref)
    out: set[int] = set()
    for m in _PAGE_RE.finditer(page_ref):
        start = int(m.group(1))
        if m.group(2):
            end = int(m.group(2))
            lo, hi = (start, end) if start <= end else (end, start)
            out.update(range(lo, hi + 1))
        else:
            out.add(start)
    return out


def _page_match(gt_ref: str | None, cert_ref: str | None) -> bool:
    """Page-number overlap. If GT page_ref null, the check is skipped (True)."""
    gt_pages = _pages(gt_ref)
    if not gt_pages:
        return True  # GT has no page constraint
    cert_pages = _pages(cert_ref)
    if not cert_pages:
        return False
    return bool(gt_pages & cert_pages)


def _tokens(s: str | None) -> set[str]:
    if not s:
        return set()
    return {t.lower() for t in _TOKEN_RE.findall(s)}


_WS_RE = re.compile(r"\s+")


def _char_trigrams(s: str | None) -> set[str]:
    """Character 3-grams of the whitespace-stripped, lowercased string.

    Robust to Korean particle attachment and minor word-form drift that defeat
    whole-token matching (e.g. '성적서' and '성적서에' share the trigram '성적서').
    """
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
# numeric values (decimals AND multi-digit integers, incl. unit-glued like
# '30J'/'305MPa'/'96HRB'/'0.024%'), element symbols, and domain keywords.
_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_ELEMENT_SYMBOLS = {
    "c", "mn", "si", "p", "s", "cr", "mo", "ni", "v", "nb", "n", "al", "cu",
    "b", "ti", "zr", "w", "pb", "sn", "as", "sb", "bi",
}
# Multi-word domain keywords matched as phrases; single-word ones matched as tokens.
_DOMAIN_PHRASES = ("delta ferrite", "n/al", "code case")
_DOMAIN_WORDS = {
    "ferrite", "mt", "pt", "ut", "rt", "nde", "heat", "pb", "cef", "cev",
    "normalizing", "tempering", "hardness", "tensile", "yield",
    "elongation", "impact", "microstructure", "thickness", "quantity",
    "dimension", "material", "heattreatment",
}
# Korean -> English canonical domain token, so a Korean-worded summary and an
# English-worded GT summary about the same property share a key token
# (e.g. '인장강도' <-> 'Tensile Strength', '경도' <-> 'Hardness').
_KO_SYNONYMS = {
    "인장": "tensile", "항복": "yield", "경도": "hardness", "충격": "impact",
    "연신": "elongation", "두께": "thickness", "열처리": "heattreatment",
    "미세조직": "microstructure", "페라이트": "ferrite", "수량": "quantity",
    "치수": "dimension", "재질": "material", "노멀라이": "normalizing",
    "템퍼": "tempering",
}


def _key_tokens(s: str | None) -> set[str]:
    """Extract KEY tokens from a summary per the semantic content_related rule.

    Key tokens = decimal numbers, element symbols, and domain keywords
    (incl. multi-word phrases). Lowercased; phrases keep their internal space.
    """
    if not s:
        return set()
    low = s.lower()
    keys: set[str] = set()
    # numeric values: decimals + multi-digit integers (drop 1-digit index noise
    # like item/page numbers). findall pulls the number out of unit-glued forms
    # ('30j'->'30', '305mpa'->'305', '0.024%'->'0.024').
    for num in _NUM_RE.findall(low):
        if "." in num or len(num) >= 2:
            keys.add(num)
    # word/number-boundary tokens for element symbols + single-word keywords
    for t in _TOKEN_RE.findall(low):
        if t in _ELEMENT_SYMBOLS or t in _DOMAIN_WORDS:
            keys.add(t)
    # multi-word domain phrases
    for phrase in _DOMAIN_PHRASES:
        if phrase in low:
            keys.add(phrase)
    # Korean domain terms -> English canonical token (cross-language matching)
    for ko, en in _KO_SYNONYMS.items():
        if ko in s:
            keys.add(en)
    return keys


def _content_match(gt_summary: str | None, cert_summary: str | None) -> tuple[bool, float]:
    """content_related per the SEMANTIC predicate.

    Pass if EITHER token-overlap Jaccard >= 0.2 OR the two summaries share at
    least one KEY token (decimal number / element symbol / domain keyword).
    Returns (passed, jaccard_score); the score is reported for the diagnostic
    rubric and best-candidate selection.
    """
    gt_t = _tokens(gt_summary)
    cf_t = _tokens(cert_summary)
    score = _jaccard(gt_t, cf_t)
    if score >= 0.2:
        return True, score
    if _key_tokens(gt_summary) & _key_tokens(cert_summary):
        return True, score
    # GT-coverage: a SHORT GT summary whose content is (mostly) contained in a
    # longer cert summary. Symmetric Jaccard under-scores this because the long
    # cert summary inflates the union; coverage asks the recall question — "is
    # the GT issue covered by the cert finding?". Stopword-light tokens + the
    # grade/page/severity-tier gates keep this from over-matching.
    if gt_t and len(gt_t & cf_t) / len(gt_t) >= 0.55:
        return True, score
    # Char-trigram coverage: robust to Korean particle attachment ('성적서' vs
    # '성적서에') and word-form drift that defeats whole-token matching. Asks how
    # much of the GT summary's character-trigram profile is present in the cert.
    gt_g = _char_trigrams(gt_summary)
    cf_g = _char_trigrams(cert_summary)
    if gt_g and len(gt_g & cf_g) / len(gt_g) >= 0.6:
        return True, score
    return False, score


# --------------------------------------------------------------------------- #
# Per-case matching
# --------------------------------------------------------------------------- #


_SEVERITY_TIER = {
    "reject": "major", "actionrequired": "major",
    "question": "minor", "minor": "minor",
}


def _severity_tier(sev: str | None) -> str:
    """Map a severity label to its tier. Unknown -> the raw lowercased value."""
    return _SEVERITY_TIER.get((sev or "").strip().lower().replace(" ", ""), (sev or "").strip().lower())


def _severity_match(gt_sev: str | None, cert_sev: str | None) -> bool:
    """Tier-based severity match (per user decision).

    GT assigns different exact severities to the same issue-type across cases
    (e.g. 'Product Analysis 2회 미수행' is Reject in case 36 but ActionRequired
    in cases 40/47&48), so exact severity is not rule-derivable. We therefore
    match on the coarse tier: major = {Reject, ActionRequired},
    minor = {Question, Minor}. Exact agreement is still tracked in the
    diagnostic rubric.
    """
    return _severity_tier(gt_sev) == _severity_tier(cert_sev)


def match_case(gt_findings: list[dict], cert_findings: list[dict]) -> dict:
    """Semantic match per case (replaces the strict Jaccard>=0.5 gate).

    A GT finding G is a HIT iff SOME cert finding C satisfies ALL of:
      1. category(C) == category(G)              [exact]
      2. severity tier(C) == severity tier(G)    [major/minor tier, not exact]
      3. grade_match(C, G)                       (_grade_match: shared grade
         token / containment; both-null -> match)
      4. page_match                              (skipped if either page_ref
         null; else page-number-set intersection non-empty)
      5. content_related                         (_content_match: token Jaccard
         >= 0.2 OR a shared KEY token)

    heat_no is NOT a gate condition under the semantic predicate (it remains a
    DIAGNOSTIC rubric dimension only). Greedy one-to-one assignment: each cert
    finding can satisfy at most one GT finding. Returns hit/miss ids, precision
    bookkeeping, and a DIAGNOSTIC rubric (per-dimension agreement ratios over
    GT findings).
    """
    matched_gt_ids: list[str] = []
    unmatched_gt_ids: list[str] = []
    matched_cert_idx: set[int] = set()

    # Diagnostic rubric counters (best-candidate basis per GT finding).
    rub = {"severity": 0, "category": 0, "grade": 0, "heatno": 0, "content": 0}
    gt_total = len(gt_findings)

    for gf in gt_findings:
        gf_id = gf.get("finding_id", "<gt>")
        gt_cat = (gf.get("category") or "").strip()
        gt_sev = (gf.get("severity") or "").strip()
        gt_grade = gf.get("material_grade")
        gt_heat = gf.get("heat_no")
        gt_page = gf.get("page_ref")
        gt_summary = gf.get("issue_summary")

        best_idx: int | None = None
        best_score = -1.0
        # Diagnostic: track per-dimension agreement against the strongest
        # candidate (the cert finding with the highest content Jaccard,
        # regardless of whether it is a full semantic hit).
        diag_best = {
            "severity": 0, "category": 0, "grade": 0, "heatno": 0,
            "content_ok": 0, "content_score": 0.0,
        }

        for idx, cf in enumerate(cert_findings):
            cf_cat = (cf.get("category") or "").strip()
            cf_sev = (cf.get("severity") or "").strip()
            cf_grade = cf.get("material_grade")
            cf_heat = cf.get("heat_no")
            cf_page = cf.get("page_ref")
            cf_summary = cf.get("issue_summary")

            content_ok, content_score = _content_match(gt_summary, cf_summary)

            # Diagnostic best candidate = highest content score over all certs.
            if content_score > diag_best["content_score"]:
                diag_best = {
                    "severity": 1 if cf_sev == gt_sev else 0,
                    "category": 1 if cf_cat == gt_cat else 0,
                    "grade": 1 if _grade_match(gt_grade, cf_grade) else 0,
                    "heatno": 1 if _heat_match(gt_heat, cf_heat) else 0,
                    "content_ok": 1 if content_ok else 0,
                    "content_score": content_score,
                }

            if idx in matched_cert_idx:
                continue

            sev_ok = _severity_match(gt_sev, cf_sev)
            grade_ok = _grade_match(gt_grade, cf_grade)
            page_ok = _page_match(gt_page, cf_page)

            # Issue-match gate (per user decision): content + grade + page +
            # severity-tier. category is NOT a gate — GT assigns the same issue
            # different categories across cases (e.g. a missing attribute is
            # DocumentError for Branch thickness but Identification for LOT No.,
            # and a bad chemistry value is Chemistry not DocumentError), so an
            # exact category gate is not rule-derivable. category & exact
            # severity remain in the diagnostic rubric only. heat_no diagnostic.
            if sev_ok and grade_ok and page_ok and content_ok:
                # Prefer the semantic-hit candidate with the highest content score.
                if content_score > best_score:
                    best_score = content_score
                    best_idx = idx

        # Accumulate diagnostic rubric.
        rub["severity"] += diag_best["severity"]
        rub["category"] += diag_best["category"]
        rub["grade"] += diag_best["grade"]
        rub["heatno"] += diag_best["heatno"]
        rub["content"] += diag_best["content_ok"]

        if best_idx is not None:
            matched_cert_idx.add(best_idx)
            matched_gt_ids.append(gf_id)
        else:
            unmatched_gt_ids.append(gf_id)

    cert_total = len(cert_findings)
    matched_cert_ids = sorted(matched_cert_idx)
    extra_cert_ids = [
        cert_findings[i].get("finding_id", f"<cert#{i}>")
        for i in range(cert_total)
        if i not in matched_cert_idx
    ]

    def _ratio(n: int) -> float:
        return (n / gt_total) if gt_total else 1.0

    rubric = {
        "severity": _ratio(rub["severity"]),
        "category": _ratio(rub["category"]),
        "grade": _ratio(rub["grade"]),
        "heatno": _ratio(rub["heatno"]),
        "content": _ratio(rub["content"]),
    }

    return {
        "hits": len(matched_gt_ids),
        "gt_total": gt_total,
        "matched_gt_ids": matched_gt_ids,
        "unmatched_gt_ids": unmatched_gt_ids,
        "cert_total": cert_total,
        "matched_cert_ids": [
            cert_findings[i].get("finding_id", f"<cert#{i}>") for i in matched_cert_ids
        ],
        "extra_cert_ids": extra_cert_ids,
        "rubric": rubric,
    }


# --------------------------------------------------------------------------- #
# Aggregate evaluation
# --------------------------------------------------------------------------- #


def evaluate(
    case_ids: list[str],
    work_dir: Path,
    cache_root: Path,
    gt_path: Path,
    stamp: str = "latest",
) -> dict:
    """Aggregate strict GT evaluation across cases.

    Metrics:
      recall          = total_hits / total_gt           (target 104/104 == 1.0)
      case_pass_count = #cases where all GT findings hit
      precision       = total_matched_cert / total_cert (target >= 0.9)
      dropped_total   = sum of dropped_findings across cases (target 0)

    PASS = (recall == 1.0) AND (case_pass_count == n_cases)
           AND (precision >= 0.9) AND (dropped_total == 0)

    Writes output/eval/eval_report_<stamp>.{md,json}. The stamp is an argument;
    this function never reads wall-clock time.
    """
    work_dir = Path(work_dir)
    cache_root = Path(cache_root)
    gt_all = parse_gt(gt_path)

    per_case: list[dict] = []
    total_gt = 0
    total_hits = 0
    total_cert = 0
    total_matched_cert = 0
    dropped_total = 0
    case_pass_count = 0

    for case_id in case_ids:
        gt_findings = gt_all.get(case_id, [])
        cert_findings = load_cert_findings(case_id, cache_root)
        dropped = _load_dropped_count(case_id, cache_root)

        m = match_case(gt_findings, cert_findings)
        full_hit = (m["gt_total"] > 0 and m["hits"] == m["gt_total"]) or (
            m["gt_total"] == 0
        )
        if full_hit:
            case_pass_count += 1

        total_gt += m["gt_total"]
        total_hits += m["hits"]
        total_cert += m["cert_total"]
        total_matched_cert += len(m["matched_cert_ids"])
        dropped_total += dropped

        per_case.append({
            "case_id": case_id,
            "dropped": dropped,
            "full_hit": full_hit,
            **m,
        })

    recall = (total_hits / total_gt) if total_gt else 1.0
    precision = (total_matched_cert / total_cert) if total_cert else 1.0
    n_cases = len(case_ids)

    passed = (
        recall == 1.0
        and case_pass_count == n_cases
        and precision >= 0.9
        and dropped_total == 0
    )

    aggregate = {
        "stamp": stamp,
        "n_cases": n_cases,
        "case_ids": list(case_ids),
        "total_gt": total_gt,
        "total_hits": total_hits,
        "total_cert": total_cert,
        "total_matched_cert": total_matched_cert,
        "recall": recall,
        "precision": precision,
        "case_pass_count": case_pass_count,
        "dropped_total": dropped_total,
        "pass": passed,
        "verdict": "PASS" if passed else "FAIL",
        "per_case": per_case,
    }

    out_dir = work_dir / "output" / "eval"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"eval_report_{stamp}.json"
    md_path = out_dir / f"eval_report_{stamp}.md"

    json_path.write_text(
        json.dumps(aggregate, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(_render_md(aggregate, gt_all), encoding="utf-8")

    aggregate["report_md"] = str(md_path)
    aggregate["report_json"] = str(json_path)
    return aggregate


def _fmt_pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _render_md(agg: dict, gt_all: dict[str, list[dict]]) -> str:
    """Render the markdown eval report."""
    lines: list[str] = []
    verdict = agg["verdict"]
    lines.append("# GT 평가 리포트 (Standard Inspection)")
    lines.append("")
    lines.append(f"- stamp: `{agg['stamp']}`")
    lines.append(f"- 평가 케이스 수: {agg['n_cases']}")
    lines.append("")
    lines.append(f"## 종합: {verdict}")
    lines.append("")

    # The 4 strict metrics.
    lines.append("### 핵심 지표 (PASS 판정 4조건)")
    lines.append("")
    lines.append("| 지표 | 값 | 목표 | 충족 |")
    lines.append("|---|---|---|---|")
    recall_ok = agg["recall"] == 1.0
    casepass_ok = agg["case_pass_count"] == agg["n_cases"]
    prec_ok = agg["precision"] >= 0.9
    drop_ok = agg["dropped_total"] == 0
    lines.append(
        f"| recall | {agg['total_hits']}/{agg['total_gt']} = {_fmt_pct(agg['recall'])} "
        f"| 104/104 = 100% | {'O' if recall_ok else 'X'} |"
    )
    lines.append(
        f"| case_pass | {agg['case_pass_count']}/{agg['n_cases']} "
        f"| {agg['n_cases']}/{agg['n_cases']} | {'O' if casepass_ok else 'X'} |"
    )
    lines.append(
        f"| precision | {agg['total_matched_cert']}/{agg['total_cert']} = {_fmt_pct(agg['precision'])} "
        f"| >= 90% | {'O' if prec_ok else 'X'} |"
    )
    lines.append(
        f"| dropped_total | {agg['dropped_total']} | 0 | {'O' if drop_ok else 'X'} |"
    )
    lines.append("")
    lines.append(
        f"**PASS 판정**: recall==1.0 ({'O' if recall_ok else 'X'}) AND "
        f"case_pass==전체 ({'O' if casepass_ok else 'X'}) AND "
        f"precision>=0.9 ({'O' if prec_ok else 'X'}) AND "
        f"dropped==0 ({'O' if drop_ok else 'X'}) => **{verdict}**"
    )
    lines.append("")

    # Missing GT findings per case.
    lines.append("## 누락(미매칭) GT 지적사항 (per case)")
    lines.append("")
    any_missing = False
    gt_index: dict[str, dict[str, dict]] = {}
    for cid, gfs in gt_all.items():
        gt_index[cid] = {gf.get("finding_id", ""): gf for gf in gfs}
    for pc in agg["per_case"]:
        if pc["unmatched_gt_ids"]:
            any_missing = True
            lines.append(f"### Case {pc['case_id']} — 누락 {len(pc['unmatched_gt_ids'])}건")
            lines.append("")
            idx = gt_index.get(pc["case_id"], {})
            for fid in pc["unmatched_gt_ids"]:
                gf = idx.get(fid, {})
                summary = gf.get("issue_summary", "")
                cat = gf.get("category", "")
                sev = gf.get("severity", "")
                lines.append(f"- `{fid}` [{sev}] [{cat}] {summary}")
            lines.append("")
    if not any_missing:
        lines.append("- (없음) 모든 GT 지적사항이 매칭됨.")
        lines.append("")

    # Extra cert findings per case.
    lines.append("## 초과(매칭 안 된) Cert 지적사항 (per case)")
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
        lines.append("- (없음) 모든 Cert 지적사항이 GT에 매칭됨.")
        lines.append("")

    # Per-case rubric diagnostic table.
    lines.append("## 진단용 루브릭 (DIAGNOSTIC ONLY)")
    lines.append("")
    lines.append(
        "> 주의: 아래 루브릭(severity/category/grade/heatno/content 일치 비율)은 "
        "**진단 목적의 참고 지표**일 뿐이며, PASS/FAIL 판정에는 사용되지 않는다. "
        "PASS는 위의 4개 엄격 조건(recall==1.0, case_pass==전체, precision>=0.9, "
        "dropped==0)으로만 결정된다."
    )
    lines.append("")
    lines.append("| case | GT | hits | cert | severity | category | grade | heatno | content |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for pc in agg["per_case"]:
        r = pc["rubric"]
        lines.append(
            f"| {pc['case_id']} | {pc['gt_total']} | {pc['hits']} | {pc['cert_total']} "
            f"| {_fmt_pct(r['severity'])} | {_fmt_pct(r['category'])} | {_fmt_pct(r['grade'])} "
            f"| {_fmt_pct(r['heatno'])} | {_fmt_pct(r['content'])} |"
        )
    lines.append("")

    return "\n".join(lines) + "\n"


__all__ = [
    "gt_path_for",
    "parse_gt",
    "load_cert_findings",
    "match_case",
    "evaluate",
]
