"""Key issue facts for the research page: every value with its source and status, or the reason it is missing.

The list covers what IPO portals show on an issue page (price band, face value, lot, issue size, shares offered,
promoter holding, listing exchanges, registrar, lead managers, promoters, website) plus a few derived figures. Each
entry states where the value came from (NSE, the offer document with its page, an NSE filing, or a derivation from
those) and whether it is verified or an estimate. A missing value is never shown as zero: it carries the reason —
not announced yet at this stage of the issue, not published by the sources tried, or waiting for a filing.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion import normalizer as nz
from app.ingestion.ipo_data_service import field_provenance
from app.models import FieldObservation, FinancialStatement, IPOIssue, SourceDocument, SubscriptionSnapshot
from app.services.completeness import DOC_SOURCE, SOURCE_LABEL

LABELS = {**SOURCE_LABEL, "nse_equity_list": "NSE listed-equity list", "nse_shareholding": "NSE shareholding pattern",
          "nse_rhp:derived": "Derived from offer terms", "sebi_rhp:derived": "Derived from offer terms",
          "sebi_drhp:derived": "Derived from offer terms"}
_PRICED = ("open", "closed", "listed")
PREFERENCE = ("nse_shareholding", "nse_ipo", "nse_equity_list", "nse_bhavcopy", "nse_rhp", "sebi_rhp", "sebi_drhp")
# reasons that mean "expected later", not "no source has it"
_PENDING = ("needs a price, or",
            "not announced yet", "announced when", "set after bidding", "filed with NSE", "needs a price", "published by NSE when", "fresh issue ₹")


def _fact(key: str, label: str, value: Any, unit: str, *, prov: dict[str, Any] | None = None, status: str | None = None,
          source: str | None = None, basis: str | None = None, page: int | None = None, document_id: int | None = None,
          url: str | None = None, reason: str | None = None) -> dict[str, Any]:
    p = prov or {}
    if value is None or value == [] or value == "":
        waiting = bool(reason and reason.startswith(_PENDING))
        return {"key": key, "label": label, "value": None, "unit": unit, "status": "pending" if waiting else "unavailable", "reason": reason}
    st = status or p.get("data_status") or "verified"
    src_key = p.get("source_key") or ""
    return {"key": key, "label": label, "value": value, "unit": unit,
            "status": "derived" if st == "verified" and src_key.endswith(":derived") else st,
            "source": source or LABELS.get(src_key, src_key or None), "basis": basis or p.get("basis"), "page": page,
            "document_id": document_id, "url": url or p.get("source_url"), "reason": None}


def _valuation(db: Session, ipo: IPOIssue, price: float | None, mcap: float | None, shares_est: bool) -> list[dict[str, Any]]:
    """P/E at the issue price from the latest annual restated statement, labelled by that statement's status.

    Verified statements give verified (or, at the upper band, estimated) multiples — the same figures the score uses.
    Statements read as printed but not reconciled give an 'unverified' multiple that is shown and never scored; a
    statement that failed an accounting check gives none.
    """
    stmts = db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.is_current.is_(True),
                                                        FinancialStatement.period_months == 12)).scalars().all()
    usable = [s for s in stmts if s.data_status in ("verified", "extracted", "imported", "synthetic")]
    if not price:
        why = "needs a price: the price band is not announced yet"
        return [_fact("pe_pre", "P/E on pre-issue EPS", None, "x", reason=why), _fact("pe_post", "P/E after the issue (market cap ÷ PAT)", None, "x", reason=why)]
    if not usable:
        why = ("the latest annual statements failed an accounting check (shown for review only)" if stmts else
               "needs annual statements from the offer document")
        return [_fact("pe_pre", "P/E on pre-issue EPS", None, "x", reason=why), _fact("pe_post", "P/E after the issue (market cap ÷ PAT)", None, "x", reason=why)]
    latest = max(usable, key=lambda s: s.period_end)
    unverified = latest.data_status == "extracted"
    at = "the issue price" if ipo.final_issue_price else "the upper band"
    status = "unverified" if unverified else ("estimated" if (not ipo.final_issue_price or shares_est) else "verified")
    source = f"{latest.period_label} restated statements" + (" (not reconciled; never scored)" if unverified else "")
    eps = latest.eps_diluted if latest.eps_diluted is not None else latest.eps_basic
    eps_basis = f"{'diluted' if latest.eps_diluted is not None else 'basic'} EPS ₹{eps:g}" if eps is not None else None
    if eps is None and latest.pat is not None and ipo.pre_issue_shares:
        # no EPS line read: profit after tax over the shares before the issue (the weighted count may differ after a bonus issue)
        eps = round(latest.pat * 1e7 / ipo.pre_issue_shares, 2)
        eps_basis = f"EPS ₹{eps:g} = PAT ₹{latest.pat:,.2f} cr ÷ {ipo.pre_issue_shares:,.0f} shares before the issue (no EPS line printed)"
    pre = round(price / eps, 2) if price and eps and eps > 0 else None
    post = round(mcap / latest.pat, 2) if mcap and latest.pat and latest.pat > 0 else None
    loss = latest.pat is not None and latest.pat <= 0
    return [
        _fact("pe_pre", f"P/E at {at} on pre-issue EPS", pre, "x", status=status, source=source,
              basis=f"₹{price:g} ÷ {eps_basis}" if pre and price and eps_basis else None,
              reason=f"not meaningful: {latest.period_label} EPS is zero or negative" if loss or (eps is not None and eps <= 0)
              else f"{latest.period_label} EPS was not read from the statements"),
        _fact("pe_post", f"P/E at {at} after the issue", post, "x", status=status, source=source,
              basis=f"market cap ₹{mcap:,.2f} cr ÷ {latest.period_label} PAT ₹{latest.pat:,.2f} cr" if post and mcap and latest.pat else None,
              reason=f"not meaningful: {latest.period_label} PAT is zero or negative" if loss else
              f"{latest.period_label} PAT was not read from the statements" if latest.pat is None else "needs the post-issue share count"),
    ]


def _shares_offered(db: Session, ipo: IPOIssue, prov: dict[str, Any], total: float | None, total_status: str, status: str,
                    reason: str) -> dict[str, Any]:
    """Shares offered in the bidding categories (anchor portion excluded), most exact source first.

    1. NSE's issue list (published while the issue is upcoming or open).
    2. NSE's consolidated bid details stored while the issue was open (total row).
    3. Shares in the issue − the anchor portion printed in NSE's issue-size sentence (matches NSE's own figure on every
       issue where both exist).
    """
    label = "Shares offered to bidders"
    if ipo.shares_offered:
        return _fact("shares_offered", label, ipo.shares_offered, "shares", prov=prov, basis="excludes the anchor portion")
    snap = db.execute(select(SubscriptionSnapshot.shares_offered).where(
        SubscriptionSnapshot.ipo_id == ipo.id, SubscriptionSnapshot.category == "total", SubscriptionSnapshot.shares_offered > 0)
        .order_by(SubscriptionSnapshot.as_of.desc()).limit(1)).scalar_one_or_none()
    if snap:
        return _fact("shares_offered", label, round(snap), "shares", status="verified", source="NSE bid details (consolidated)",
                     basis="shares offered in the bidding categories while the issue was open; excludes the anchor portion")
    anchor = nz.parse_reserved_portions(ipo.issue_size_text).get("anchor")
    if total and anchor and anchor < total:
        return _fact("shares_offered", label, round(total - anchor), "shares", status=total_status, source="Derived from NSE issue size",
                     basis=f"{total:,.0f} shares in the issue − {anchor:,.0f} anchor portion")
    return _fact("shares_offered", label, None, "shares",
                 reason="NSE did not print the anchor portion and listed the figure only while the issue was open" if status == "listed" else reason)


def _promoter_range(ipo: IPOIssue, comp: dict[str, float], pv: dict[str, Any], price: float | None) -> tuple[float, float, str] | None:
    """Post-issue promoter holding before the listing-time filing, for an issue with an offer for sale.

    The promoters' share of the offer for sale is not in these fields, so the result is a range: from all of it sold by
    promoters (low) to none of it (high). Promoter shares = pre-issue % × pre-issue shares.
    """
    pre_pct, pre_shares = ipo.promoter_holding_pre_pct, ipo.pre_issue_shares
    if pre_pct is None or not pre_shares:
        return None
    ofs = comp.get("ofs_shares") or pv.get("ofs_shares")
    if ofs is None:
        ofs_cr = ipo.ofs_cr if ipo.ofs_cr is not None else (comp.get("ofs_cr") or pv.get("ofs_cr"))
        ofs = ofs_cr * 1e7 / price if ofs_cr and price else None
    if not ofs:
        return None
    post = ipo.post_issue_shares
    if post is None and (pv.get("fresh_shares") == 0 or pv.get("fresh_cr") == 0):
        post = pre_shares  # an offer for sale only adds no shares
    if not post or post < pre_shares:
        return None
    held = pre_pct / 100 * pre_shares
    low, high = max(held - ofs, 0.0) / post * 100, held / post * 100
    return (round(low, 2), round(high, 2),
            f"promoters hold {held:,.0f} shares ({pre_pct:g}% before the issue); {ofs:,.0f} shares offered for sale; {post:,.0f} shares after the "
            "issue — low if promoters sell all of the offer for sale, high if they sell none; the filing at listing gives the figure")


def _versus_peers(db: Session, ipo: IPOIssue, result: dict[str, Any] | None, price: float | None) -> list[dict[str, Any]]:
    """The issue's valuation against its listed peers (estimates; never scored).

    Premium = issue P/E ÷ peer-median P/E − 1; the price at the peer multiple = issue price × peer median ÷ issue P/E.
    Before a price exists: indicative equity value = latest verified PAT × peer-median P/E.
    """
    peers = (result or {}).get("peers") or {}
    med, n = peers.get("median_pe"), peers.get("with_pe") or peers.get("count")
    pe = (((result or {}).get("metrics") or {}).get("pe") or {}).get("value")
    if not med:
        why = ("fewer than two listed peers with a usable P/E in the offer document's comparison" if (result or {}).get("peers") is not None
               else "needs the listed-peer comparison from the offer document")
        return [_fact("peer_premium", "Valuation vs listed peers", None, "pct_signed", reason=why)]
    if pe and price:
        prem = round((pe / med - 1) * 100, 1)
        return [_fact("peer_premium", "Valuation vs listed peers", prem, "pct_signed", status="estimated", source="Derived: issue P/E vs peer median",
                      basis=f"issue P/E {pe:.1f}x vs median {med:.1f}x of {n} listed peers (positive = priced above peers)"),
                _fact("peer_price", "Price at the peer-median P/E", round(price * med / pe, 2), "inr", status="estimated",
                      source="Speculative: issue price × peer median ÷ issue P/E", basis=f"₹{price:g} × {med:.1f} ÷ {pe:.1f}; a comparison, not a forecast")]
    stmt = db.execute(select(FinancialStatement).where(FinancialStatement.company_id == ipo.company_id, FinancialStatement.is_current.is_(True),
                                                       FinancialStatement.period_months == 12, FinancialStatement.data_status == "verified")
                      .order_by(FinancialStatement.period_end.desc()).limit(1)).scalar_one_or_none()
    if stmt is None or not stmt.pat or stmt.pat <= 0:
        return [_fact("peer_premium", "Valuation vs listed peers", None, "pct_signed",
                      reason="needs a price, or verified positive profit for an indicative value")]
    value = round(stmt.pat * med, 2)
    return [_fact("peer_value", "Indicative equity value at the peer-median P/E", value, "cr", status="estimated",
                  source="Speculative: latest PAT × peer-median P/E", basis=f"{stmt.period_label} PAT ₹{stmt.pat:,.2f} cr × {med:.1f}x "
                  f"(median of {n} listed peers); a comparison before any price is set, not a valuation of the offer")]


def upper_band_rate(db: Session) -> tuple[int, int]:
    """(issues priced at the upper end of the band, listed book-built issues with a final price) — the base rate for estimates."""
    rows = db.execute(select(IPOIssue.final_issue_price, IPOIssue.price_band_high).where(
        IPOIssue.data_mode == "source", IPOIssue.final_issue_price.is_not(None), IPOIssue.price_band_low < IPOIssue.price_band_high)).all()
    return sum(1 for f, h in rows if h and abs(f - h) < 0.005), len(rows)


def issue_facts(db: Session, ipo: IPOIssue, today: date | None = None, result: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """``result`` is the issue's score result (``score_ipo``), used for the comparison with listed peers."""
    from app.services.ipo_service import effective_status

    today = today or date.today()
    status = effective_status(ipo, today)
    prov = field_provenance(db, ipo.id)
    facts = ipo.document_facts or {}
    doc_facts_read = "offer_terms_version" in facts
    pipeline = status == "pipeline"
    demo = ipo.data_mode == "demo"

    def doc_fact(key: str) -> dict[str, Any]:
        return facts.get(key) or {}

    docs = db.execute(select(SourceDocument).where(SourceDocument.ipo_id == ipo.id, SourceDocument.source_key.in_(tuple(DOC_SOURCE)))).scalars().all()

    def doc_state() -> str:
        """Why an offer-document field is empty, from the state of the issue's documents."""
        if doc_facts_read:
            return "not found in a readable form in the offer document"
        if not docs:
            return "no offer document linked by NSE or filed with SEBI yet"
        if all(d.extraction_status == "failed" for d in docs):
            return "the offer document could not be downloaded or read (retried with backoff)"
        return "the offer document is queued to be read"

    def missing(nse: bool = True, doc: bool = True, stage: tuple[str, ...] = ()) -> str:
        if stage and status not in stage:
            return "not announced yet: only an offer document has been filed" if pipeline else "announced when the issue is priced"
        parts = []
        if nse and ipo.nse_symbol:
            parts.append("not published by NSE")
        if doc and not demo:
            parts.append(doc_state())
        return "; ".join(parts) if parts else "no source publishes it for this issue"

    # every source that reported the value now stored, per field (latest observation of each): when several agree, the most
    # authoritative is named — an NSE filing or NSE's issue page before the offer document, and any of them before a derivation
    agree: dict[str, dict[str, FieldObservation]] = {}
    current = {f: v.get("value") for f, v in prov.items()}
    for o in db.execute(select(FieldObservation).where(FieldObservation.ipo_id == ipo.id).order_by(FieldObservation.id)).scalars():
        if o.value is not None and o.field in current and json.loads(o.value) == current[o.field]:
            agree.setdefault(o.field, {})[o.source_key] = o

    def best(field: str) -> dict[str, Any]:
        p = dict(prov.get(field) or {})
        seen = agree.get(field, {})
        top = next((k for k in PREFERENCE if k in seen), None)
        if top and top != p.get("source_key"):
            o = seen[top]
            p.update({"source_key": top, "source_url": o.source_url, "basis": o.basis, "data_status": o.data_status})
        return p

    def from_doc_or_obs(field: str) -> tuple[dict[str, Any], int | None, int | None]:
        p = best(field)
        d = doc_fact(field)
        if p.get("source_key") in DOC_SOURCE and d:
            return p, d.get("page"), d.get("document_id")
        if d and set(agree.get(field, {})) & set(DOC_SOURCE):
            p["basis"] = None  # the page link says the offer document states the same value
            return p, d.get("page"), d.get("document_id")
        return p, None, None

    out: list[dict[str, Any]] = []
    method = {"book_built": "Book built", "fixed_price": "Fixed price"}.get(ipo.issue_method or "")
    p, page, doc_id = from_doc_or_obs("issue_method")
    out.append(_fact("issue_method", "Issue type", method, "text", prov=p, page=page, document_id=doc_id, reason=missing()))

    band = None
    if ipo.price_band_low and ipo.price_band_high:
        band = [ipo.price_band_low, ipo.price_band_high]
    out.append(_fact("price_band", "Price band" if ipo.issue_method != "fixed_price" else "Issue price (fixed)", band, "inr_range",
                     prov=best("price_band_high"), reason=missing(doc=False, stage=_PRICED)))
    if ipo.issue_method != "fixed_price":
        if ipo.final_issue_price is None and ipo.price_band_high and status in ("upcoming", "open", "closed"):
            at_cap, n_book = upper_band_rate(db)
            out.append(_fact("final_issue_price", "Final issue price", ipo.price_band_high, "inr", status="estimated",
                             source="Estimate: upper end of the price band",
                             basis=f"{at_cap} of {n_book} listed book-built issues on record were priced at the upper band; "
                                   "NSE publishes the final price with the listing" if n_book else "book-built issues are usually priced at the upper band"))
        else:
            out.append(_fact("final_issue_price", "Final issue price", ipo.final_issue_price, "inr", prov=best("final_issue_price"),
                             reason=missing(doc=False, stage=("listed",))))

    p, page, doc_id = from_doc_or_obs("face_value")
    out.append(_fact("face_value", "Face value", ipo.face_value, "inr", prov=p, page=page, document_id=doc_id, reason=missing()))
    out.append(_fact("lot_size", "Lot size", ipo.lot_size, "shares", prov=best("lot_size"), reason=missing(doc=False, stage=_PRICED)))
    price = ipo.final_issue_price or ipo.price_band_high
    per_lot = round(ipo.lot_size * price) if ipo.lot_size and price else None
    out.append(_fact("lot_value", "One lot at " + ("the issue price" if ipo.final_issue_price else "the upper band"), per_lot, "inr",
                     status="verified" if ipo.final_issue_price else "estimated", source="Derived: lot size × price",
                     basis=f"{ipo.lot_size} shares × ₹{price:g}" if per_lot and price else None,
                     reason="needs the lot size and the price" if status in _PRICED else missing(doc=False, stage=_PRICED)))

    comp = nz.parse_issue_components(ipo.issue_size_text) or {}
    size_basis = None
    if ipo.issue_size_cr is not None:
        size_basis = best("issue_size_cr").get("basis")
    proposed = doc_fact("proposed_offer")
    pv: dict[str, Any] = (proposed.get("value") or {}) if ipo.issue_size_cr is None else {}  # draft terms only before NSE's
    prop_src = "Offer document cover (proposed)" if pv else None
    if ipo.issue_size_cr is None and pv.get("total_cr"):
        out.append(_fact("issue_size", "Issue size (proposed)", pv["total_cr"], "cr", status="proposed", source=prop_src,
                         basis="total offer size as printed on the cover", page=proposed.get("page"), document_id=proposed.get("document_id")))
    else:
        out.append(_fact("issue_size", "Issue size", ipo.issue_size_cr, "cr", prov=best("issue_size_cr"), basis=size_basis,
                         reason=(f"fresh issue ₹{pv['fresh_cr']:,.2f} cr proposed; the offer-for-sale value is set with the price"
                                 if pv.get("fresh_cr") and pv.get("ofs_shares") else missing(doc=False, stage=_PRICED))))
    split = None
    if ipo.fresh_issue_cr is not None or ipo.ofs_cr is not None:
        split = {"fresh_cr": ipo.fresh_issue_cr, "ofs_cr": ipo.ofs_cr, "fresh_shares": comp.get("fresh_shares"), "ofs_shares": comp.get("ofs_shares")}
        out.append(_fact("issue_split", "Fresh issue / offer for sale", split, "split", prov=best("fresh_issue_cr"),
                         reason=missing(doc=False, stage=_PRICED)))
    elif pv and any(pv.get(k) is not None for k in ("fresh_cr", "fresh_shares", "ofs_cr", "ofs_shares")):
        out.append(_fact("issue_split", "Fresh issue / offer for sale (proposed)", {"fresh_cr": pv.get("fresh_cr"), "ofs_cr": pv.get("ofs_cr"),
                         "fresh_shares": pv.get("fresh_shares"), "ofs_shares": pv.get("ofs_shares")}, "split", status="proposed", source=prop_src,
                         basis="as printed on the draft offer document's cover; '[●]' parts are set with the price", page=proposed.get("page"),
                         document_id=proposed.get("document_id")))
    else:
        out.append(_fact("issue_split", "Fresh issue / offer for sale", None, "split", reason=missing(doc=False, stage=_PRICED)))
    # total shares in the issue: share counts printed in NSE's issue-size sentence, else rupee amounts ÷ price
    def part_shares(kind: str) -> float | None:
        if f"{kind}_shares" in comp:
            return comp[f"{kind}_shares"]
        if f"{kind}_cr" in comp:
            return comp[f"{kind}_cr"] * 1e7 / price if price else None
        return 0.0

    total, t_status, t_basis = None, "verified", None
    if "total_shares" in comp:
        total, t_basis = comp["total_shares"], "as printed in NSE's issue-size sentence"
    elif any(k.startswith(("fresh_", "ofs_")) for k in comp):
        parts = [part_shares("fresh"), part_shares("ofs")]
        total = None if None in parts else sum(p or 0.0 for p in parts)
        priced = any(k.endswith("_cr") for k in comp)
        t_status = "estimated" if priced and not ipo.final_issue_price else "verified"
        t_basis = ("fresh + offer-for-sale shares from NSE's issue-size sentence"
                   + (f"; rupee amounts ÷ {'final issue price' if ipo.final_issue_price else 'upper band'} ₹{price:g}" if priced and price else ""))
    if total is None and pv.get("total_shares"):
        out.append(_fact("total_shares", "Total shares in the issue (proposed)", round(pv["total_shares"]), "shares", status="proposed",
                         source=prop_src, basis="as printed on the cover", page=proposed.get("page"), document_id=proposed.get("document_id")))
    else:
        out.append(_fact("total_shares", "Total shares in the issue", round(total) if total else None, "shares", status=t_status if total else None,
                         source="Derived from NSE issue size" if total else None, basis=t_basis, url=ipo.offer_document_url,
                         reason="needs NSE's issue-size sentence (and a price when it states rupees)" if status in _PRICED else missing(doc=False, stage=_PRICED)))
    out.append(_shares_offered(db, ipo, best("shares_offered"), total, t_status, status, missing(doc=False, stage=_PRICED)))

    p, page, doc_id = from_doc_or_obs("listing_exchanges")
    out.append(_fact("listing_exchanges", "Listing on", ipo.listing_exchanges, "text", prov=p, page=page, document_id=doc_id,
                     reason=missing(nse=False)))
    out.append(_fact("isin", "ISIN", ipo.isin, "text", prov=best("isin"),
                     reason="not published by NSE or its listed-equity list" if status == "listed" else
                     "filed with NSE at listing (issue page or listed-equity list)" if ipo.nse_symbol else
                     "not announced yet: only an offer document has been filed"))

    p, page, doc_id = from_doc_or_obs("pre_issue_shares")
    pre_doc = doc_fact("pre_issue_shares")
    out.append(_fact("pre_issue_shares", "Shares before the issue", ipo.pre_issue_shares, "shares", prov=p,
                     page=page or pre_doc.get("page"), document_id=doc_id or pre_doc.get("document_id"), reason=missing(nse=False)))
    out.append(_fact("post_issue_shares", "Shares after the issue", ipo.post_issue_shares, "shares", prov=best("post_issue_shares"),
                     reason="needs the shares before the issue and the fresh-issue size" if ipo.pre_issue_shares is None or status in _PRICED
                     else missing(nse=False, stage=_PRICED)))
    mcap = round(ipo.post_issue_shares * price / 1e7, 2) if ipo.post_issue_shares and price else None
    shares_est = (prov.get("post_issue_shares") or {}).get("data_status") == "estimated"
    out.append(_fact("market_cap", "Market cap at " + ("the issue price" if ipo.final_issue_price else "the upper band"), mcap, "cr",
                     status="estimated" if (shares_est or not ipo.final_issue_price) else "verified", source="Derived: post-issue shares × price",
                     basis=f"{ipo.post_issue_shares:,.0f} shares × ₹{price:g}" if mcap and price and ipo.post_issue_shares else None,
                     reason="needs a price: the price band is not announced yet" if not price else "needs the post-issue share count"))

    out.extend(_valuation(db, ipo, price, mcap, shares_est))

    p, page, doc_id = from_doc_or_obs("promoter_holding_pre_pct")
    out.append(_fact("promoter_holding_pre", "Promoter holding before the issue", ipo.promoter_holding_pre_pct, "pct", prov=p, page=page,
                     document_id=doc_id, reason=missing(nse=False)))
    post_reason = ("filed with NSE in the shareholding pattern at listing" if status != "listed" else
                   "not yet found in NSE's shareholding-pattern filings (re-checked daily for a month after listing)")
    if status != "listed" and ipo.ofs_cr:
        post_reason += "; the offer for sale changes promoter holdings, so it is not derived before then"
    rng = None if ipo.promoter_holding_post_pct is not None or status == "listed" else _promoter_range(ipo, comp, pv, price)
    if ipo.promoter_holding_post_pct is None and ipo.promoter_holding_pre_pct == 0:
        out.append(_fact("promoter_holding_post", "Promoter holding after the issue", 0.0, "pct", status="derived", source="Derived from offer terms",
                         basis="the company has no identifiable promoter, so no promoter holding before or after the issue"))
    elif rng is not None:
        out.append(_fact("promoter_holding_post", "Promoter holding after the issue (range)", [rng[0], rng[1]], "pct_range", status="estimated",
                         source="Derived from offer terms", basis=rng[2]))
    else:
        out.append(_fact("promoter_holding_post", "Promoter holding after the issue", ipo.promoter_holding_post_pct, "pct",
                         prov=best("promoter_holding_post_pct"), reason=post_reason))
    latest = doc_fact("shareholding_latest")
    # the latest filing, when it is a later one than the pattern filed for listing (otherwise it repeats the row above)
    if latest.get("value") is not None and ipo.listing_date and str(latest.get("as_of")) > ipo.listing_date.isoformat():
        out.append(_fact("promoter_holding_latest", "Promoter holding (latest filing)", latest.get("value"), "pct", status="verified",
                         source=f"NSE shareholding pattern, {latest.get('as_of')}", url=latest.get("source_url")))
    pr = doc_fact("promoters")
    out.append(_fact("promoters", "Promoters", pr.get("value") if pr else None, "list", status="verified" if pr else None,
                     source="Offer document" if pr else None, basis=pr.get("basis"), page=pr.get("page"), document_id=pr.get("document_id"),
                     reason=missing(nse=False)) if not (pr and pr.get("value") == []) else
               _fact("promoters", "Promoters", "No identifiable promoter", "text", status="verified", source="Offer document",
                     page=pr.get("page"), document_id=pr.get("document_id")))
    intermediary = ("published by NSE when the issue is announced; none of the names known from NSE records is on the draft document's cover"
                    if pipeline else missing(doc=False))
    for fld, label in (("registrar", "Registrar"), ("lead_managers", "Lead managers")):
        p = best(fld)
        if pipeline and getattr(ipo, fld) and p.get("source_key") in DOC_SOURCE:  # read from the draft document's cover
            d = doc_fact(fld)
            out.append(_fact(fld, label, getattr(ipo, fld), "text", status="proposed", source="Draft offer document (cover)", basis=p.get("basis"),
                             page=d.get("page"), document_id=d.get("document_id")))
        else:
            out.append(_fact(fld, label, getattr(ipo, fld), "text", prov=p, reason=intermediary))
    out.extend(_versus_peers(db, ipo, result, price))
    site = doc_fact("website")
    out.append(_fact("website", "Company website", ipo.company.website, "url", status="verified" if ipo.company.website else None,
                     source="Offer document" if site else ("Import" if ipo.company.website else None), page=site.get("page"),
                     document_id=site.get("document_id"), url=ipo.company.website, reason=missing(nse=False)))
    return out
