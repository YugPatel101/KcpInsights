"""Industry classification from the offer document, and lender KPIs as printed.

NSE's issue data carries no sector, so KcpInsights reads it from the prospectus: weighted
industry phrases ("non-banking financial company", "installed capacity", "order book",
"software as a service", ...) are counted across the business sections, and the sector with the
clearly highest weight wins. The result is a *derived* classification, stored with its evidence
(phrases, counts and pages) and status ``extracted``; when no sector clearly leads, the issue stays
"Unclassified" rather than guessing.

The sector picks an **analysis profile** (lender, insurer, technology, manufacturing,
infrastructure, real estate, general) that decides which ratios apply — see
``services.industry_profiles``.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from app.financials.pdf_tables import page_rows

# sector -> (analysis profile, [(phrase regex, weight)])
SECTORS: dict[str, tuple[str, list[tuple[str, float]]]] = {
    "Banking": ("lender", [(r"small finance bank", 4), (r"scheduled commercial bank", 3), (r"banking licen[cs]e", 3), (r"\bcasa\b", 2),
                           (r"current account and savings account", 3)]),
    "NBFC & Lending": ("lender", [(r"(registered|registration) (with the )?(rbi|reserve bank of india) as an? (nbfc|non[- ]banking)", 6),
                                  (r"non[- ]banking financial compan", 2), (r"housing finance compan", 3), (r"microfinance", 2),
                                  (r"gold loans?", 2), (r"\bloan book\b", 2), (r"\bdisbursements?\b", 1), (r"gross (npa|non[- ]performing)", 2),
                                  (r"\bgnpa\b", 2), (r"net interest margin", 2), (r"capital adequacy", 2), (r"\bcrar\b", 2), (r"stage (3|iii) assets", 2),
                                  (r"assets under management", 0.5)]),
    "Insurance": ("insurer", [(r"\birdai\b", 3), (r"gross written premium", 4), (r"solvency ratio", 3), (r"claims? ratio", 2),
                              (r"insurance compan", 1)]),
    "Capital Markets & Asset Management": ("general", [(r"alternative investment funds?", 3), (r"portfolio management services", 3),
                                                       (r"asset management compan", 2), (r"wealth management", 2), (r"stock[- ]?broking", 3),
                                                       (r"stock exchange", 1), (r"clearing corporation", 2), (r"fee[- ]earning", 2)]),
    "Information Technology & Software": ("technology", [(r"software as a service|\bsaas\b", 4), (r"\bit services\b", 3),
                                                         (r"software (products?|platform|development|solutions?)", 2),
                                                         (r"annual recurring revenue", 4), (r"net revenue retention", 4),
                                                         (r"digital transformation", 1), (r"cloud[- ]based", 1)]),
    "Internet & E-commerce": ("technology", [(r"e[- ]?commerce", 2), (r"online marketplace", 3), (r"gross merchandise value|\bgmv\b", 3),
                                             (r"monthly (active|transacting) users", 3), (r"mobile app(lication)?s?", 0.5)]),
    "Telecom & Digital Services": ("technology", [(r"telecom(munication)? services", 3), (r"\barpu\b", 3), (r"wireless subscribers", 3),
                                                  (r"\b5g\b", 1), (r"spectrum", 1)]),
    "Defence & Electronics": ("manufacturing", [(r"defen[cs]e", 1), (r"thermal imaging|night vision|electro[- ]optic", 3),
                                                (r"electronic (components|manufacturing)", 2), (r"\bems\b", 2), (r"printed circuit board|\bpcb\b", 2)]),
    "Pharmaceuticals": ("manufacturing", [(r"pharmaceutical", 2), (r"\busfda\b", 3), (r"formulations?", 2), (r"active pharmaceutical ingredients?", 3),
                                          (r"\bapis?\b", 1)]),
    "Medical Devices": ("manufacturing", [(r"medical devices?", 3), (r"\bstents?\b", 3), (r"implants?", 2), (r"\bcdsco\b", 2)]),
    "Building Materials": ("manufacturing", [(r"vitrified|ceramic tiles?|\btiles\b", 3), (r"sanitaryware", 3), (r"\bcement\b", 2),
                                             (r"granite|marble", 2), (r"plywood|laminates", 2)]),
    "Healthcare Services": ("general", [(r"hospitals?", 2), (r"bed capacity|operational beds", 3), (r"diagnostic", 2), (r"\barpob\b", 4)]),
    "Chemicals": ("manufacturing", [(r"specialty chemicals?", 4), (r"agrochemicals?", 3), (r"chemicals?", 0.5), (r"intermediates", 1)]),
    "Metals & Steel": ("manufacturing", [(r"\bsteel\b", 1), (r"stainless", 2), (r"galvani[sz]ed|colou?r[- ]coated", 3), (r"aluminium", 1),
                                         (r"\bcoils?\b", 1), (r"ferro[- ]alloys?", 3)]),
    "Industrial & Engineering Products": ("manufacturing", [(r"gear ?(boxes|motors)|power transmission", 3), (r"capital goods", 2),
                                                           (r"precision (engineering|components)", 2), (r"industrial (machinery|equipment)", 2),
                                                           (r"\bcnc\b", 1), (r"contract manufacturing", 2)]),
    "Auto Components": ("manufacturing", [(r"auto(motive)? components?", 3), (r"\boems?\b", 1), (r"two[- ]wheelers?", 1), (r"passenger vehicles?", 1)]),
    "Textiles & Apparel": ("manufacturing", [(r"textiles?", 2), (r"\byarns?\b", 2), (r"fabrics?", 1.5), (r"garments?", 1.5), (r"apparel", 1),
                                             (r"woven|knitted", 1)]),
    "Jewellery & Accessories": ("manufacturing", [(r"jewell?ery", 2), (r"imitation jewell?ery", 4), (r"hallmark", 1)]),
    "Food & Agri Products": ("manufacturing", [(r"food products?", 2), (r"\bpapads?\b", 4), (r"snacks?", 2), (r"edible oils?", 3), (r"\brice\b", 1),
                                               (r"spices", 2), (r"dairy", 2), (r"agri(cultural)? (products|commodities)", 2)]),
    "Packaging & Plastics": ("manufacturing", [(r"packaging", 2), (r"polymers?", 1.5), (r"plastics?", 1), (r"\bpet\b|\bhdpe\b|\bpvc\b", 1),
                                               (r"woven sacks|fibc", 3)]),
    "Infrastructure & Construction": ("infrastructure", [(r"\bepc\b", 2), (r"engineering,? procurement and construction", 3), (r"order book", 2),
                                                         (r"hybrid annuity", 3), (r"(road|highway|railway|metro) projects?", 2),
                                                         (r"infrastructure projects?", 2), (r"civil construction", 2)]),
    "Energy & Utilities": ("infrastructure", [(r"renewable energy", 2), (r"solar (power|modules?|cells?|projects?|epc)", 2),
                                              (r"power purchase agreements?", 3), (r"wind (power|energy)", 2), (r"\bmwp?\b", 0.5),
                                              (r"transmission (lines|towers)", 2), (r"city gas distribution|\bcgd\b", 3), (r"gas pipelines?", 2)]),
    "Environmental Services": ("infrastructure", [(r"waste ?water treatment|sewage treatment", 3), (r"water treatment", 2),
                                                  (r"waste management", 2), (r"effluent", 1), (r"environmental (engineering|technologies)", 2)]),
    "Real Estate": ("real_estate", [(r"\brera\b", 3), (r"real estate", 2), (r"saleable area|carpet area", 2), (r"residential projects?", 2),
                                    (r"land bank", 3), (r"pre[- ]sales", 2)]),
    "Logistics": ("general", [(r"logistics", 2), (r"warehous(e|ing)", 1), (r"freight", 1.5), (r"third[- ]party logistics|\b3pl\b", 3),
                              (r"fleet of (trucks|vehicles)", 2)]),
    "Consumer & Retail": ("general", [(r"retail stores?", 2), (r"\bfmcg\b", 3), (r"direct[- ]to[- ]consumer|\bd2c\b", 3),
                                      (r"(company|exclusive)[- ]owned stores?", 2), (r"distributors?", 0.3)]),
    "Hospitality & Travel": ("general", [(r"hotels?", 2), (r"occupancy", 1), (r"average room rate|\barr\b", 2), (r"restaurants?|\bqsr\b", 2),
                                         (r"travel (services|agency)", 2)]),
    "Media & Education": ("general", [(r"broadcast", 2), (r"content (library|production)", 2), (r"students? enrolled", 3), (r"edtech", 3),
                                      (r"schools?", 0.5)]),
}

MIN_SCORE = 8.0  # weighted evidence needed to classify at all
MIN_LEAD = 1.3  # the winner must lead the runner-up by this factor


@dataclass
class Classification:
    sector: str
    profile: str
    status: str  # extracted | unavailable
    confidence: float  # winner's share of the top-two evidence (0.5–1.0); not a probability
    evidence: list[dict[str, Any]] = field(default_factory=list)
    runner_up: str | None = None
    note: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"sector": self.sector, "profile": self.profile, "status": self.status, "confidence": round(self.confidence, 2),
                "evidence": self.evidence, "runner_up": self.runner_up, "note": self.note, "method": "weighted industry phrases in the offer document"}


def _business_pages(texts: list[str]) -> list[int]:
    """Pages of the business and industry sections; the whole document when those headings are not found."""
    start = [i for i, t in enumerate(texts) if re.search(r"^\s*(our business|business overview|industry overview)\s*$", t[:400], re.I | re.M)]
    if not start:
        return list(range(min(len(texts), 300)))
    pages: set[int] = set()
    for i in start:
        pages.update(range(i, min(i + 40, len(texts))))
    return sorted(pages)


def classify_industry(texts: list[str], company_name: str = "") -> Classification:
    pages = _business_pages(texts)
    blob = [(i, texts[i].lower()) for i in pages]
    name = company_name.lower()
    scores: dict[str, float] = {}
    evidence: dict[str, list[dict[str, Any]]] = {}
    for sector, (_, phrases) in SECTORS.items():
        total = 0.0
        ev: list[dict[str, Any]] = []
        for pat, w in phrases:
            rx = re.compile(pat)
            hits = [(i, len(rx.findall(t))) for i, t in blob]
            n = sum(c for _, c in hits)
            in_name = len(rx.findall(name))
            if n or in_name:
                total += w * math.log2(1 + n) + 6.0 * in_name  # the company's own name is strong evidence ("... Steels Limited")
                first = next((m.group(0) for _, t in blob if (m := rx.search(t))), None) or next((m.group(0) for m in [rx.search(name)] if m), pat)
                ev.append({"phrase": re.sub(r"\s+", " ", first).strip(), "pattern": pat, "count": n, "pages": [i + 1 for i, c in hits if c][:5],
                           "in_company_name": bool(in_name)})
        scores[sector] = total
        evidence[sector] = sorted(ev, key=lambda e: -e["count"])[:5]
    ranked = sorted(scores, key=lambda s: -scores[s])
    top, second = ranked[0], ranked[1]
    a, b = scores[top], scores[second]
    if a < MIN_SCORE or (b > 0 and a / b < MIN_LEAD):
        return Classification("Unclassified", "general", "unavailable", a / (a + b) if a + b else 0.0, evidence.get(top, []), top if a else None,
                              note=(f"no sector clearly leads ({top} {a:.1f} vs {second} {b:.1f})" if a >= MIN_SCORE
                                    else "too little industry-specific language found"))
    return Classification(top, SECTORS[top][0], "extracted", a / (a + b) if a + b else 1.0, evidence[top], second if b else None)


# ---------------------------------------------------------------------------- lender KPIs (as printed)
LENDER_KPIS = {
    "gnpa_pct": r"^gross (npa|non[- ]performing assets?|stage[- ]?(3|iii)( assets)?)( ratio)?\b.*%|^gnpa( ratio)?\b",
    "nnpa_pct": r"^net (npa|non[- ]performing assets?|stage[- ]?(3|iii)( assets)?)( ratio)?\b.*%|^nnpa( ratio)?\b",
    "crar_pct": r"^(capital (to risk[- ]weighted assets|adequacy)( ratio)?|crar)\b",
    "nim_pct": r"^net interest margin\b|^nim\b",
    "aum_cr": r"^(assets under management|aum|gross loan (book|portfolio))\b",
    "provision_coverage_pct": r"^provision(ing)? coverage( ratio)?\b",
    "credit_cost_pct": r"^credit cost\b",
}


def lender_kpis(doc: Any, texts: list[str]) -> dict[str, dict[str, Any]]:
    """First KPI-table row per lender metric, with its figures exactly as printed. Unverified: shown, never scored."""
    out: dict[str, dict[str, Any]] = {}
    compiled = {k: re.compile(p, re.I) for k, p in LENDER_KPIS.items()}
    for i, t in enumerate(texts):
        low = t.lower()
        if not re.search(r"key performance indicators|operational (and|&) financial (metrics|parameters)|key (financial|operational) metrics", low):
            continue
        for r in page_rows(doc[i], i + 1):
            if len(r.cells) < 2:
                continue
            lab = re.sub(r"\s+", " ", r.label.strip().lower())
            lab = re.sub(r"^[\d.()a-z]{1,4}[.)]\s+", "", lab)
            for k, rx in compiled.items():
                if k not in out and rx.search(lab):
                    out[k] = {"label": r.label.strip()[:120], "values_as_printed": [c.text for c in r.cells][:6], "page": i + 1,
                              "status": "extracted", "note": "as printed in the KPI table; periods follow the table's column order"}
        if len(out) == len(compiled):
            break
    return out
