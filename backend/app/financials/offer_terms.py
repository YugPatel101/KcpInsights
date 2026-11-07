"""Offer terms printed in an offer document (DRHP, RHP or prospectus).

SEBI's ICDR Regulations prescribe where these appear: the cover page (face value, promoters, book-built or fixed-price
issue, listing exchanges, the company's website and e-mail), the capital structure chapter (the shareholding pattern in
the format of LODR Regulation 31) and the objects of the issue. Only those fixed places are read. Every value carries its
page and the text as printed; anything not found, or found but failing its check, is returned as None — nothing is
inferred, and a promoter holding is accepted only when the promoter and public rows of the same table add up.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Any

from app.financials.disclosures import Disclosure
from app.financials.statement_parser import UNIT_TO_CRORE, detect_unit

EXTRACTOR_VERSION = "1.3"

_WS = re.compile(r"\s+")
_RS = r"(?:₹|`|Rs\.?|Re\.?|INR)\s?"  # "`" is how PDFs set in the Rupee Foradian font encode ₹


def _flat(text: str) -> str:
    return _WS.sub(" ", text.replace(" ", " "))


def _fz(word: str) -> str:
    """Pattern for a word that PDF text extraction may split ('Promote r', 'Promot ers')."""
    return r"\s?".join(re.escape(c) for c in word)


# ---------------------------------------------------------------------------- cover page
_FV = re.compile(r"face value (?:of (?:each |our |the )?(?:equity shares? )?(?:is )?)?" + _RS + r"(\d{1,4}(?:\.\d{1,2})?)\s?(?:/-)?\s?(?:each|per)", re.I)


def face_value(texts: list[str]) -> Disclosure | None:
    """Face value per equity share: the value stated most often in the first pages (cover, definitions, offer summary)."""
    votes: Counter[float] = Counter()
    first: dict[float, tuple[int, str]] = {}
    for i, t in enumerate(texts[:30]):
        flat = _flat(t)
        for m in _FV.finditer(flat):
            v = float(m.group(1))
            if 0 < v <= 1000:
                votes[v] += 1
                first.setdefault(v, (i + 1, flat[max(0, m.start() - 40): m.end() + 20]))
    if not votes:
        return None
    (v, n), *rest = votes.most_common(2)
    if rest and rest[0][1] * 3 > n:
        return None  # two different face values stated comparably often: ambiguous
    page, text = first[v]
    return Disclosure("face_value", v, page, text, f"stated {n} time(s) in the opening pages")


def issue_method(texts: list[str]) -> Disclosure | None:
    for i, t in enumerate(texts[:3]):
        flat = _flat(t)
        m = re.search(r"(?:100\s?% )?book[- ]?buil(?:t|ding) (?:issue|offer)|fixed[- ]price (?:issue|offer)", flat, re.I)
        if m:
            value = "fixed_price" if m.group(0).lower().startswith("fixed") else "book_built"
            return Disclosure("issue_method", value, i + 1, m.group(0))
    return None


def listing_exchanges(texts: list[str]) -> Disclosure | None:
    """Exchanges the shares are 'proposed to be listed on', as stated on the cover page."""
    for i, t in enumerate(texts[:6]):
        flat = _flat(t)
        m = re.search(r"proposed to be listed on (.{0,300})", flat, re.I)
        if not m:
            continue
        seg = re.split(r"designated stock exchange|in-principle|in principle|\. [A-Z]", m.group(1), maxsplit=1)[0]
        low = seg.lower()
        found: list[str] = []
        if re.search(r"emerge|sme platform of (?:the )?(?:national stock exchange|nse)|nse sme", low):
            found.append("NSE Emerge")
        if re.search(r"bse sme|sme platform of (?:the )?(?:bse|bombay)", low):
            found.append("BSE SME")
        if not found:
            if re.search(r"national stock exchange|\bnse\b", low):
                found.append("NSE")
            if re.search(r"\bbse\b|bombay stock exchange", low):
                found.append("BSE")
        if found:
            return Disclosure("listing_exchanges", ", ".join(found), i + 1, m.group(0)[:240])
    return None


_NAME_STOP = re.compile(r"\s(?:DETAILS OF|THE OFFER|THE ISSUE|TYPE OF|OFFER FOR SALE|FRESH ISSUE|ISSUE TO PUBLIC|DETAILS)\b")


def _split_names(seg: str) -> list[str]:
    seg = re.sub(r"\((?:i|ii|iii|iv|v|vi|vii|viii|ix|x|\d{1,2})\)|\b(?:i|ii|iii|iv|v|vi|vii|viii|ix|x)\)", ",", seg)
    parts = [p.strip(" .;:-") for p in re.split(r",|;|\band\b|\bAND\b|&(?=\s+[A-Z][a-z]+\s)", seg)]
    names = []
    for p in parts:
        p = re.sub(r"^(?:mr|mrs|ms|dr|shri|smt)\.?\s+", "", p, flags=re.I).strip()
        if 3 <= len(p) <= 80 and re.match(r"[A-Za-z]", p) and not re.search(r"\d|promoter|company|section|page", p, re.I):
            names.append(p.title() if p.isupper() else p)
    return names


def promoters(texts: list[str]) -> Disclosure | None:
    """Promoter names from the cover page ('OUR PROMOTERS: ...'), else from 'The Promoters of our Company are ...'."""
    for i, t in enumerate(texts[:3]):
        flat = _flat(t)
        m = re.search(r"(?:OUR (?:INDIVIDUAL |CORPORATE )?PROMOTERS?|(?:THE )?PROMOTERS? OF (?:OUR|THE) COMPANY(?: ARE)?)\s?:?\s?([A-Z].{2,500})", flat)
        if m:
            seg = _NAME_STOP.split(m.group(1), maxsplit=1)[0]
            names = _split_names(seg)
            if 1 <= len(names) <= 15:
                return Disclosure("promoters", names, i + 1, m.group(0)[:300], "cover page")
    for i, t in enumerate(texts[:260]):
        flat = _flat(t)
        if re.search(r"does not have (?:an )?identifiable promoters?|no identifiable promoters?", flat, re.I):
            return Disclosure("promoters", [], i + 1, "the company has no identifiable promoter", "no identifiable promoter")
        m = re.search(r"(?:the )?promoters of our company are\s?:?\s?(.{3,400}?)\.(?:\s|$)", flat, re.I)
        if m:
            names = _split_names(m.group(1))
            if 1 <= len(names) <= 15:
                return Disclosure("promoters", names, i + 1, m.group(0)[:300], "'Our Promoters' section")
    return None


_SKIP_HOSTS = ("sebi.gov.in", "nseindia.com", "bseindia.com", "kfintech.com", "linkintime.co.in", "in.mpms.mufg.com", "bigshareonline.com",
               "skylinerta.com", "cameoindia.com", "purvashare.com", "maashitla.com")


def contact(texts: list[str]) -> dict[str, Disclosure]:
    """The company's website and e-mail: the first ones printed on the cover page (intermediaries' follow later)."""
    out: dict[str, Disclosure] = {}
    for i, t in enumerate(texts[:2]):
        flat = _flat(t)
        if "website" not in out:
            # "Website: www.x.com", else the first www. address on the cover (the issuer's contacts come before the intermediaries')
            for pat in (r"Website\s?:\s?((?:https?://)?(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+){1,3})",
                        r"(?<![\w@.])((?:https?://)?www\.[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+){1,3})",
                        r"(?<![\w@.])(https?://[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+){1,3})"):
                for m in re.finditer(pat, flat, re.I):
                    host = re.sub(r"^https?://", "", m.group(1).lower()).rstrip(".")  # kept as printed (with or without www.)
                    if not any(host.endswith(s) for s in _SKIP_HOSTS):
                        out["website"] = Disclosure("website", host, i + 1, flat[max(0, m.start() - 30): m.end()])
                        break
                if "website" in out:
                    break
        if "email" not in out:
            em = re.search(r"E-?mail(?: id)?\s?:?\s?([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", flat, re.I)
            if em and not any(em.group(1).lower().endswith(s) for s in _SKIP_HOSTS):
                out["email"] = Disclosure("email", em.group(1).lower(), i + 1, em.group(0))
    return out


# ---------------------------------------------------------------------------- proposed offer (cover page)
_OFFER_CELL = re.compile(r"(?:up to\s+)?(\d{1,3}(?:,\d{2,3})+|\d{4,}|\[[●•]\])\s+equity shares\b.{0,120}?aggregating\s+(?:up\s+)?to\s+"
                         + _RS + r"\s?(\d[\d,]*(?:\.\d+)?|\[[●•]\])\s?(million|lakhs?|crores?)?|\bnot applicable\b|\bnil\b", re.I)


def proposed_offer(texts: list[str]) -> Disclosure | None:
    """The offer as the cover page states it: fresh issue, offer for sale and total, each in shares and/or rupees.

    SEBI's cover format prints three cells in this order. A figure not yet determined ('[●]') stays None. When shares
    (or rupees) are printed for all three cells they must add up; otherwise the reading is refused.
    """
    for i, t in enumerate(texts[:2]):
        flat = _flat(t)
        m = re.search(r"DETAILS OF (?:THE )?(?:OFFER|ISSUE)(.{0,1600}?)(?:The (?:Offer|Issue) is being made|$)", flat, re.I)
        if not m:
            continue
        cells = list(_OFFER_CELL.finditer(m.group(1)))
        if len(cells) < 3:
            continue
        parsed: list[tuple[float | None, float | None]] = []
        for c in cells[:3]:
            if c.group(1) is None:  # "Not applicable" / "Nil"
                parsed.append((0.0, 0.0))
                continue
            shares = None if c.group(1).startswith("[") else float(c.group(1).replace(",", ""))
            amount = None
            if not c.group(2).startswith("[") and c.group(3):
                factor = UNIT_TO_CRORE.get(detect_unit("₹ in " + c.group(3)) or "")
                amount = round(float(c.group(2).replace(",", "")) * factor, 4) if factor else None
            parsed.append((shares, amount))
        (fs, fa), (os_, oa), (ts, ta) = parsed
        for part1, part2, whole in ((fs, os_, ts), (fa, oa, ta)):
            if part1 is not None and part2 is not None and whole is not None and abs(part1 + part2 - whole) > max(1.0, 0.001 * whole):
                return None  # the printed parts do not add up: not read
        value = {"fresh_shares": fs, "fresh_cr": fa, "ofs_shares": os_, "ofs_cr": oa, "total_shares": ts, "total_cr": ta}
        if all(v is None for v in value.values()):
            continue
        return Disclosure("proposed_offer", value, i + 1, m.group(0)[:400], "offer size as stated on the cover page")
    return None


# ---------------------------------------------------------------------------- intermediaries (draft documents)
# registrars to an issue (a short, stable list); names on NSE records are added by the caller
REGISTRARS = ("KFin Technologies Limited", "MUFG Intime India Private Limited", "Link Intime India Private Limited",
              "Bigshare Services Private Limited", "Cameo Corporate Services Limited", "Skyline Financial Services Private Limited",
              "Purva Sharegistry (India) Private Limited", "Maashitla Securities Private Limited", "Mudra RTA Ventures Private Limited",
              "MAS Services Limited", "Integrated Registry Management Services Private Limited")
# words that cannot identify a lead manager on their own ("Capital Markets" is part of many names)
_GENERIC_WORDS = {"capital", "markets", "market", "securities", "financial", "finance", "services", "advisors", "advisers", "advisory",
                  "investment", "investments", "management", "wealth", "broking", "brokers", "company", "corporate", "consultants", "&", "and"}
_SUFFIX = re.compile(r"\b(?:private|pvt|limited|ltd|llp|india|\(india\))\b\.?", re.I)


def name_core(name: str) -> str:
    """A company name reduced for matching: lower case, no legal suffixes or punctuation ('KFin Technologies Limited' -> 'kfin technologies')."""
    s = re.sub(r"\(formerly[^)]*\)", " ", name, flags=re.I)
    s = _SUFFIX.sub(" ", s.lower())
    return " ".join(re.sub(r"[^a-z0-9& ]+", " ", s).split())


def cover_intermediaries(texts: list[str], registrars: list[str], managers: list[str]) -> dict[str, Disclosure]:
    """Registrar and book-running lead managers named on the cover page, by matching names already known.

    Draft documents set these in narrow cover tables that interleave when read, so names are not parsed from the layout:
    each known name (at least two significant words) is looked for on the cover instead. A manager never seen before
    is therefore not listed — the basis says so.
    """
    cover = " " + " ".join(name_core(_flat(t)) for t in texts[:2]) + " "
    out: dict[str, Disclosure] = {}
    reg_cores: dict[str, str] = {}
    for n in registrars:
        if len(name_core(n).split()) >= 2:
            reg_cores.setdefault(name_core(n), n)
    found_reg = [(cover.find(f" {c} "), n) for c, n in reg_cores.items() if f" {c} " in cover]
    if found_reg:
        name = min(found_reg)[1]
        out["registrar"] = Disclosure("registrar", re.sub(r"\s*\(formerly[^)]*\)", "", name).strip(), 1, name, "named on the cover page")
    seen: dict[str, tuple[int, str]] = {}
    for n in managers:
        c = name_core(n)
        if len(c.split()) >= 2 and set(c.split()) - _GENERIC_WORDS and c not in reg_cores and f" {c} " in cover:
            seen.setdefault(c, (cover.find(f" {c} "), n.strip()))
    seen = {c: v for c, v in seen.items() if not any(c != o and f" {c} " in f" {o} " for o in seen)}  # inside a longer name found
    if seen:
        names = [n for _, n in sorted(seen.values())]
        out["lead_managers"] = Disclosure("lead_managers", ", ".join(names), 1, "; ".join(names)[:300],
                                          "named on the cover page; matched against lead managers on NSE records (one not seen before would be missing)")
    return out


# ---------------------------------------------------------------------------- share capital
_POST = re.compile(r"(?:outstanding|paid[- ]up)[a-z ,]{0,40}?after the (?:issue|offer)[^\[●•]{0,150}?\b(\d{1,3}(?:,\d{2,3})+)\s?"
                   r"(?:fully paid[- ]up )?equity shares", re.I)


def post_issue_shares(texts: list[str]) -> Disclosure | None:
    """Equity shares after the issue when the document prints the number (fixed share counts, mostly SME); '[●]' is skipped."""
    for i, t in enumerate(texts[:260]):
        flat = _flat(t)
        m = _POST.search(flat)
        if m:
            n = int(m.group(1).replace(",", ""))
            if n >= 100_000:
                return Disclosure("post_issue_shares", n, i + 1, flat[max(0, m.start() - 40): m.end() + 40], "equity shares after the issue, as printed")
    return None


# ---------------------------------------------------------------------------- shareholding pattern
_PROMOTER = _fz("Promoter")
# the promoter row of the shareholding pattern, up to the public row ("(A)"/"A" and "(B)"/"B" markers; words may be split)
_A_ROW = re.compile(r"(?:\(A\)|\bA\b)?\s?" + _PROMOTER + r"\s?s?\s?(?:and|&)\s?" + _PROMOTER + r"\s?" + _fz("Group")
                    + r"(.{0,500}?)(?:\(B\)|\bB\b)\s?" + _fz("Public"), re.I)
_NEXT_ROW = re.compile(r"\(C\)|\bC\b|©|\bTotal\b")
_A1A2 = re.compile(r"\bA1\s?" + _PROMOTER + r"s?\b(.{0,200}?)\bA2\s?" + _PROMOTER + r"\s?" + _fz("Group") + r"(.{0,200}?)\bB\s?" + _fz("Public")
                   + r"(.{0,200}?)(?:\bC\b|Total|$)", re.I)
_PCT = re.compile(r"(?<![\d,.])(\d{1,3}(?:\.\d{1,4})?)\s?%|(?<![\d,.])(\d{1,3}\.\d{1,4})(?![\d,])")


def _first_pct(seg: str) -> float | None:
    # narrow table columns split a percentage's last digit onto the next text fragment: "70.7 9" is 70.79, "83.6 2%" is 83.62
    seg = re.sub(r"(?<![\d,.])(\d{1,3}\.\d) (\d)(?=\s?%|\s|$)(?![\d,.])", r"\1\2", seg)
    m = _PCT.search(seg)
    if not m:
        return None
    v = float(m.group(1) or m.group(2))
    return v if 0 <= v <= 100 else None


def _no_figures(seg: str) -> bool:
    return not re.search(r"\d", seg)


def promoter_holding_pre(texts: list[str]) -> Disclosure | None:
    """Promoter and promoter-group share of total equity before the issue, from the shareholding-pattern table.

    Accepted only when the promoter and public rows of the same table add up to 100% (±0.6 pt), or to at least 90% when
    a non-promoter non-public row (employee trusts) holds the rest, or when the promoters hold everything and the public
    row is empty.
    """
    best: tuple[int, Disclosure] | None = None
    no_promoter = any(re.search(r"(?:does not have|no) (?:an )?identifiable promoters?", _flat(t), re.I) for t in texts[:300])
    for i, t in enumerate(texts[:300]):
        flat = _flat(t)
        cands: list[tuple[float | None, float | None, str, int, int]] = []
        for m in _A_ROW.finditer(flat):
            pub = flat[m.end(): m.end() + 300]
            nxt = _NEXT_ROW.search(pub)
            pub = pub[: nxt.start()] if nxt else pub
            a, b = _first_pct(m.group(1)), _first_pct(pub)
            if a is None and re.fullmatch(r"[\s\-–—]*", m.group(1)) and no_promoter:
                a = 0.0  # a blank promoter row, and the document states there is no identifiable promoter
                cands.append((a, None, m.group(0), m.start(), m.end()))
                continue
            if a is None and re.search(r"(?<![\d,.])100(?![\d,.])", m.group(1)) and _no_figures(pub):
                a = 100.0  # '100' printed without decimals or %, nothing held by the public
            cands.append((a, b, m.group(0) + pub, m.start(), m.end() + len(pub)))
        for m in _A1A2.finditer(flat):
            a1, a2, b = _first_pct(m.group(1)), _first_pct(m.group(2)), _first_pct(m.group(3))
            if a1 is not None:
                cands.append((round(a1 + (a2 or 0.0), 4), b, m.group(0), m.start(), m.end()))
        for a, b, _text, s, e in cands:
            if a is None:
                continue
            if b is None:
                ok, rank = a >= 99.9 or (a == 0.0 and no_promoter), 2
            else:
                total = a + b
                ok, rank = (abs(total - 100) <= 0.6, 3) if abs(total - 100) <= 0.6 else (90 <= total <= 100.6, 1)
            if not ok:
                continue
            basis = ("shareholding pattern: the promoter row is blank and the company has no identifiable promoter" if a == 0.0 and b is None else
                     f"shareholding pattern before the issue: promoter and promoter group {a:g}%" + (f", public {b:g}%" if b is not None else ", public nil"))
            d = Disclosure("promoter_holding_pre_pct", a, i + 1, flat[max(0, s - 60): min(len(flat), e)][:400], basis)
            if best is None or rank > best[0]:
                best = (rank, d)
        if best and best[0] == 3:
            break
    return best[1] if best else None


# ---------------------------------------------------------------------------- objects of the issue
_INTRO = re.compile(
    r"(?:(?:net (?:fresh )?(?:issue |offer )?proceeds|(?:fresh )?(?:issue|offer) proceeds|proceeds (?:from|of) the (?:fresh )?(?:issue|offer))"
    r"[^.]{0,80}?(?:are|is|will be) proposed to be (?:utili[sz]ed|used|deployed|applied)"
    r"|(?:we|our company) (?:proposes?|intends?) to (?:utili[sz]e|use|deploy|apply) the net proceeds)[^:]{0,200}?(?::|below|follows)", re.I)
_ITEM = re.compile(r"(?:^|\s)(?:\((?:[ivx]{1,4}|[a-h]|\d{1,2})\)|(?:[ivx]{1,4}|[a-h]|\d{1,2})[.)]|[\u2022\u25cf\u25aa\uf0b7\uf0a7•●▪])\s+")
_AMT = r"(?:\d{1,3}(?:,\d{2,3})*\.\d{1,2}|\d{1,3}(?:,\d{2,3})+|\[●\]|\[•\]|\[\s?\])"  # '[ ]' where the ● glyph was lost
# header cells of the utilisation table, removed before reading its rows
_HEADER = re.compile(
    r"^(?:\s|:|\(\d\)|\*|#|\^|"
    # longer cells first: alternation is tried in order
    r"Estimated (?:amount|deployment|utili[sz]ation)(?: to be deployed| of Net Proceeds)?(?: in| during)? (?:FY|Fiscal|Financial Year)"
    r"\s?\d{4}(?:\s?-\s?\d{2,4})?|Deployment (?:in|during) (?:FY|Fiscal)\s?\d{4}(?:\s?-\s?\d{2,4})?|"
    r"(?:Amount )?(?:which will be |to be |proposed to be )?(?:financed|funded|deployed|utili[sz]ed)(?: from| out of)?(?: the)? Net Proceeds|"
    r"(?:aggregate )?(?:proposed|estimated) (?:deployment|utili[sz]ation)(?: (?:from|of) (?:the )?net proceeds)?(?: in (?:fiscal|fy)\s?\d{4}(?:\s?-\s?\d{2,4})?)?|"
    r"\((?:amounts? in |in )?(?:₹|`|Rs\.?|inr)[^)]{0,30}\)|Sr\.?\s?No\.?|S\.\s?No\.?|Particulars|Total estimated (?:cost|amount)|"
    r"Amount(?:\s?\(\d\))?|Estimated (?:amount|cost)\*?|"
    r"(?:% of|Percentage of) (?:the )?(?:Gross|Net)(?: (?:offer|issue|fresh issue))? Proceeds(?:\s?\(\d\))?\*?|Amount already deployed|Balance)+", re.I)
_END = re.compile(r"(?:total|net proceeds|gross proceeds)\b", re.I)
_PROSE = re.compile(r"proposed to be|following table|set forth|summari[sz]ed in|as approved by|resolution dated|to be finali[sz]ed", re.I)
_SUBTOTAL = re.compile(r"^(?:\d{1,4}\s+)?sub[- ]?\s?total\b", re.I)  # a subtotal row (a page number may precede it)


# column-header phrases of utilisation tables that can be read into the first row's text
_HEAD_WORDS = re.compile(
    r"particulars|estimated (?:amount|cost|utili[sz]ation|deployment)(?: of net proceeds)?|total estimated cost|"
    r"amount(?: (?:to be|which will be|proposed to be|expected to be))? (?:funded|financed|deployed|utili[sz]ed)(?: (?:from|out of))?(?: the)? "
    r"net (?:issue |offer |fresh issue )?proceeds(?:\s?\(\d\))?|(?:amount )?(?:deployed|incurred) (?:till|up ?to) [a-z]+ \d{1,2}, \d{4}(?:\s?\(\d\))?|"
    r"(?:fiscal|fy)\s?20\d\d(?:\s?-\s?\d{2,4})?|\b(?:sr|s)\.?\s?no\.?|\((?:in |amount in |amounts in )?(?:₹|rs\.?|inr)?[^)]{0,25}(?:lakhs?|million|crores?)\)|"
    r"^\d{1,4}\b", re.I)


def _strip_head_words(s: str) -> str:
    """Drop column-header text read into a purpose: keep what follows the last header phrase, if anything."""
    last = None
    for m in _HEAD_WORDS.finditer(s):
        last = m
    if last is None:
        return s
    enum = re.search(r"(?:^|\s)(?:\d{1,2}[.)]|\([a-z0-9]{1,2}\)|[a-h][.)])\s+(?=[A-Z])", s)
    if enum and _HEAD_WORDS.search(s[: enum.start()]):
        return s[enum.end():]  # header text, then the first enumerated object
    rest = re.sub(r"^(?:\(\d\)|[\s:;,.()*%\-])+", "", s[last.end():])
    rest = re.sub(r"^(?:\d{1,2}[.)]|\([a-z0-9]{1,2}\)|[a-h][.)])\s+", "", rest).strip()
    if len(rest) >= 8 and re.match(r"[A-Z(]", rest):
        return rest
    residue = re.sub(r"[\W\d_]+", " ", _HEAD_WORDS.sub(" ", s)).strip()
    return "" if len(residue) < 12 else s  # nothing but header text: not an object


def _clean_purpose(s: str) -> str:
    s = re.sub(r"\b(?:sr|s)\.\s?no\.?", " ", s, flags=re.I)  # "Sr. No." column header (its period is not a sentence end)
    s = re.sub(r"^[\[\]●•\s%\-]+", "", s)  # residue of a "[●]" cell or a "%" header split across rows
    s = _strip_head_words(s)
    s = re.split(r"\(collectively|(?<=[a-z)”\"])\.\s", s, maxsplit=1, flags=re.I)[0]
    s = re.sub(r"(?:\(\d\)|\*+|#|\^)+\s*$", "", s.strip()).strip(" ;,.:")
    s = re.sub(r"^\d{1,2}\.?\s+", "", s)
    s = re.sub(r"\s*(?:;|,)?\s*(?:and|or)$", "", s).strip(" ;,.")
    s = re.sub(r"(?:\(\d\)|\*+|#|\^)+$", "", s).strip()
    return s[:1].upper() + s[1:]


def _rows(tail: str) -> list[tuple[str, str | None]]:
    """(purpose, first amount cell or None) for each object, in order, up to general corporate purposes.

    A numbered list ('1. ...', '(i) ...') is split at its markers; an unnumbered utilisation table is read row by row
    (text, then amount cells) up to its total row.
    """
    body = " " + _HEADER.sub("", tail)
    marks = list(_ITEM.finditer(body))
    rows: list[tuple[str, str | None]] = []
    if len(marks) >= 2 and marks[0].start() <= 3:
        for k, mk in enumerate(marks):
            seg = body[mk.end(): marks[k + 1].start() if k + 1 < len(marks) else len(body)]
            am = re.search(_AMT, seg)
            purpose = _clean_purpose(seg[: am.start()] if am else seg)
            if _SUBTOTAL.match(purpose) or not purpose:
                continue
            if _END.match(purpose) or not 8 <= len(purpose) <= 400:
                break
            rows.append((purpose, am.group(0) if am else None))
            if re.search(r"general corporate", purpose, re.I) or len(rows) >= 12:
                break
        return rows
    for m in re.finditer(r"((?:(?!" + _AMT + r").){8,400}?)\s(" + _AMT + r")((?:\s(?:" + _AMT + r"|-|NA|Nil))*)", body):
        purpose = _clean_purpose(m.group(1))
        if _SUBTOTAL.match(purpose):
            continue
        if not purpose:
            continue  # a header-only row
        if _END.match(purpose) or not 8 <= len(purpose) <= 400 or _PROSE.search(purpose):
            break
        rows.append((purpose, m.group(2)))
        if re.search(r"general corporate", purpose, re.I) or len(rows) >= 12:
            break
    return rows


_OFS_OBJECTS = re.compile(r"the objects of the (?:offer|issue) (?:are|is) (?:to )?:?\s*(.{20,700}?stock exchanges?)\b", re.I)


def _ofs_objects(texts: list[str]) -> Disclosure | None:
    """An offer for sale only: 'The objects of the Offer are to (i) carry out the Offer for Sale ... and (ii) achieve the
    benefits of listing ...' — the company receives no proceeds, which is the answer for such issues."""
    for i, t in enumerate(texts[20:], start=20):
        flat = _flat(t)
        m = _OFS_OBJECTS.search(flat)
        if not m or "offer for sale" not in m.group(1).lower():
            continue
        items = [_clean_purpose(x) for x in re.split(r"\((?:i|ii|iii|iv|a|b|c)\)|;\s*and\s|\band\b(?=\s+(?:to\s+)?achieve)", m.group(1)) if x.strip()]
        items = [x for x in items if len(x) >= 8]
        if not items:
            continue
        rows: list[dict[str, Any]] = []
        for it in items:
            amt = re.search(r"aggregating (?:up )?to " + _RS + r"([\d,]+(?:\.\d+)?) ?(million|crores?|lakhs?)", it, re.I)
            factor = UNIT_TO_CRORE.get(detect_unit("₹ in " + amt.group(2)) or "") if amt else None
            rows.append({"purpose": it, "amount_cr": round(float(amt.group(1).replace(",", "")) * factor, 4) if amt and factor else None})
        return Disclosure("objects_of_issue", rows, i + 1, m.group(0)[:400], "offer for sale only: the company receives no proceeds")
    return None


def objects_of_issue(texts: list[str]) -> Disclosure | None:
    """The objects of the issue as the company lists them: purposes in order, with the amount where the table prints one.

    Read from the 'Objects of the Issue/Offer' chapter after 'The Net Proceeds are proposed to be utilised ...': either a
    numbered list ending with general corporate purposes, or the utilisation table (purpose, amount) up to its total row.
    Amounts are converted from the unit printed above the table; '[●]' (not yet determined) stays None.
    """
    listed: list[Disclosure] = []  # readings without amounts, kept in case no table with amounts follows

    def same_objects(found: Disclosure) -> bool:
        """A later table belongs to the same objects as a list already read when they share a purpose."""
        if not listed:
            return True
        keys = {str(r["purpose"])[:20].lower() for r in listed[0].value}
        return any(str(r["purpose"])[:20].lower() in keys for r in found.value)

    for i, t in enumerate(texts):
        if i < 20:
            continue  # skip the table of contents and definitions
        flat = _flat(t)
        context = flat + " " + (_flat(texts[i - 1]) if i else "")
        if not re.search(r"objects of the (?:issue|offer)", context, re.I):
            continue
        for m in _INTRO.finditer(flat):
            tail = (flat[m.end():] + " " + (_flat(texts[i + 1]) if i + 1 < len(texts) else ""))[:3000]
            unit = detect_unit(tail[:300]) or detect_unit(flat[max(0, m.start() - 300): m.end()])
            factor = UNIT_TO_CRORE.get(unit or "")
            cells = _rows(tail)
            if not cells or not re.search(r"general corporate", cells[-1][0], re.I):
                continue
            # a numbered list in the text carries no amounts: take them from the table that follows it, matched by purpose
            if all(a is None for _, a in cells):
                after = tail[tail.lower().find("general corporate") + 17:]
                table = {p[:30].lower(): a for p, a in _rows(after)}
                cells = [(p, table.get(p[:30].lower())) for p, _ in cells]
            rows = [{"purpose": p, "amount_cr": round(float(a.replace(",", "")) * factor, 4) if a and factor and a[0].isdigit() else None}
                    for p, a in cells]
            found = Disclosure("objects_of_issue", rows, i + 1, flat[m.start(): m.end() + 300][:400],
                               f"objects as listed by the company; amounts as printed ({unit})" if factor else "objects as listed by the company")
            if any(r["amount_cr"] is not None for r in rows):
                if same_objects(found):
                    return found
                continue
            listed.append(found)
    return listed[0] if listed else _ofs_objects(texts)


def extract_offer_terms(texts: list[str], registrars: list[str] | None = None, managers: list[str] | None = None) -> dict[str, Disclosure]:
    out: dict[str, Disclosure] = {}
    for fn in (face_value, issue_method, listing_exchanges, promoters, post_issue_shares, promoter_holding_pre, objects_of_issue,
               proposed_offer):
        d = fn(texts)
        if d is not None:
            out[d.key] = d
    out.update(contact(texts))
    if managers is not None:
        out.update(cover_intermediaries(texts, [*REGISTRARS, *(registrars or [])], managers))
    return out
