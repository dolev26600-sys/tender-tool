#!/usr/bin/env python3
"""
עמוד: השוואת הצעות משכנתא בין בנקים - מעלים כמה קבצי PDF של אישורים
עקרוניים/הצעות, ומקבלים טבלת השוואה + מבחן קיצון + המלצה מנומקת.

תהליך: PDF -> טקסט (pdf_extraction) -> חילוץ תמהיל מובנה לכל הצעה
(mortgage_offer_extraction, Claude) -> חישוב מדויק בפייתון של החזר חודשי/
ריבית משוקללת/מבחן קיצון (mortgage_math) -> ניתוח והמלצה איכותית
(mortgage_comparison, Claude) -> דו"ח.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from mortgage_comparison import build_offer_analysis, compare_offers
from mortgage_offer_extraction import extract_offer
from pdf_extraction import extract_text_from_pdf
from report_mortgage import format_report, save_report
from ui_common import check_password, configure_page, render_footer, render_header

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"

TRACK_TYPE_LABELS = {
    "fixed_unlinked": "קבועה לא צמודה",
    "fixed_linked_cpi": "קבועה צמודה מדד",
    "variable_prime": "פריים",
    "variable_unlinked": "משתנה לא צמודה",
    "variable_linked_cpi": "משתנה צמודה מדד",
    "eligibility": "זכאות",
    "other": "אחר",
}

configure_page("השוואת הצעות משכנתא")

if not check_password():
    st.stop()

render_header("🏦 השוואת הצעות משכנתא", "העלה כמה הצעות/אישורים עקרוניים מבנקים, וקבל השוואה + המלצה מנומקת")

if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    st.error("שגיאת הגדרה: לא הוגדר מפתח API בשרת. פנה למי שהקים את הכלי.")
    st.stop()

st.caption(
    "1️⃣ מעלים 2+ קבצי PDF של הצעות משכנתא  ·  2️⃣ ניתוח אוטומטי (תמהיל, ריבית, החזר חודשי, מבחן קיצון)  "
    "·  3️⃣ השוואה והמלצה"
)

uploaded_files = st.file_uploader(
    "העלה קבצי PDF של הצעות/אישורים עקרוניים (לפחות 2)",
    type=["pdf"],
    accept_multiple_files=True,
    help="כל קובץ הוא הצעה אחת מבנק אחד",
)

client_preferences = st.text_area(
    "העדפות/אילוצים של הלקוח (אופציונלי)",
    placeholder='למשל: "מעדיף יציבות על פני ריבית נמוכה", "תקציב חודשי עד 6,000 ש\"ח", "מתכנן למחזר בעוד 3-4 שנים"',
)

with st.expander("⚙️ פרמטרים למבחן הקיצון"):
    st.caption("קירוב פשוט להמחשה - לא תחזית מדויקת. משפיע על מסלולים בריבית משתנה ומסלולים צמודי מדד בלבד.")
    rate_increase_pct = st.slider("עליית ריבית משוערת למסלולים משתנים (%)", 0.0, 5.0, 2.0, step=0.5)
    cpi_annual_pct = st.slider("עליית מדד שנתית משוערת למסלולים צמודים (%)", 0.0, 8.0, 3.0, step=0.5)

analyze_clicked = st.button(
    "🔍 השווה הצעות",
    type="primary",
    use_container_width=True,
    disabled=not uploaded_files or len(uploaded_files) < 2,
)

if not uploaded_files or len(uploaded_files) < 2:
    st.caption("העלה לפחות 2 קבצי PDF כדי להפעיל את הכפתור.")

if analyze_clicked and uploaded_files:
    analyzed_offers = []
    progress = st.progress(0.0, text="מתחיל ניתוח...")

    try:
        n = len(uploaded_files)
        for i, uploaded_file in enumerate(uploaded_files):
            progress.progress(i / n, text=f"מנתח את {uploaded_file.name}...")

            tmp_path = None
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(uploaded_file.getvalue())
                    tmp_path = Path(tmp.name)

                pdf_text = extract_text_from_pdf(tmp_path)
                raw_offer = extract_offer(pdf_text, source_hint=uploaded_file.name)
                analyzed = build_offer_analysis(
                    raw_offer,
                    rate_increase_pct=rate_increase_pct,
                    cpi_annual_pct=cpi_annual_pct,
                )
                analyzed_offers.append(analyzed)
            finally:
                if tmp_path is not None:
                    tmp_path.unlink(missing_ok=True)

        progress.progress(0.9, text="משווה בין ההצעות ובונה המלצה...")
        comparison = compare_offers(analyzed_offers, client_preferences=client_preferences)
        report_text = format_report(comparison, client_preferences=client_preferences)
        out_path = save_report(report_text, [o["bank_name"] for o in analyzed_offers], REPORTS_DIR)

        progress.progress(1.0, text="הושלם")
        progress.empty()

        st.session_state["mortgage_comparison"] = comparison
        st.session_state["mortgage_report_text"] = report_text
        st.session_state["mortgage_report_path"] = out_path

    except Exception as e:  # noqa: BLE001 - מציגים כל שגיאה למשתמש בצורה ברורה
        progress.empty()
        st.error("קרתה שגיאה במהלך הניתוח. אפשר לנסות שוב, ואם זה חוזר - לפנות למי שהקים את הכלי.")
        with st.expander("פרטים טכניים של השגיאה"):
            st.exception(e)


def _render_bank_card(entry: dict) -> None:
    stats = entry.get("stats", {})
    stress = entry.get("stress_test", {})

    with st.container(border=True):
        st.markdown(f"### {entry.get('bank_name', '?')}")

        cols = st.columns(3)
        cols[0].metric("סכום כולל", f"{stats.get('total_amount', 0):,.0f} ₪")
        cols[1].metric("ריבית ממוצעת משוקללת", f"{stats.get('blended_annual_interest_rate_pct', 0)}%")
        cols[2].metric("החזר חודשי התחלתי", f"{stats.get('initial_total_monthly_payment', 0):,.0f} ₪")

        if stress:
            st.caption(
                f"⚠️ בתרחיש קיצון (ריבית +{stress.get('rate_increase_pct')}%, מדד +{stress.get('cpi_annual_pct')}% "
                f"בשנה): החזר חודשי משוער **{stress.get('stressed_total_monthly_payment', 0):,.0f} ₪** "
                "(הערכה גסה להמחשה)"
            )

        pros = entry.get("pros") or []
        cons = entry.get("cons") or []
        col_pros, col_cons = st.columns(2)
        with col_pros:
            if pros:
                st.markdown("**יתרונות:**")
                for p in pros:
                    st.markdown(f"- {p}")
        with col_cons:
            if cons:
                st.markdown("**חסרונות:**")
                for c in cons:
                    st.markdown(f"- {c}")

        risk_notes = entry.get("risk_notes")
        if risk_notes:
            st.markdown(f"**הערכת סיכון:** {risk_notes}")

        with st.expander("פירוט מסלולים"):
            for t in stats.get("tracks", []):
                label = TRACK_TYPE_LABELS.get(t.get("track_type"), t.get("track_type"))
                st.markdown(
                    f"- **{t.get('name')}** ({label}) — {t.get('amount', 0):,.0f} ₪, "
                    f"{t.get('period_months', 0)} חודשים, ריבית {t.get('annual_interest_rate_pct')}%, "
                    f"החזר התחלתי {t.get('initial_monthly_payment', 0):,.0f} ₪"
                )


if "mortgage_comparison" in st.session_state:
    st.divider()
    comparison = st.session_state["mortgage_comparison"]

    ranking = comparison.get("ranking", [])
    if ranking:
        st.success("דירוג מומלץ: " + " > ".join(ranking), icon="🏆")

    recommendation = comparison.get("overall_recommendation")
    if recommendation:
        st.info(recommendation, icon="💡")

    per_bank = comparison.get("per_bank", [])
    by_name = {b.get("bank_name"): b for b in per_bank}
    ordered_names = ranking if ranking else list(by_name.keys())

    for name in ordered_names:
        entry = by_name.get(name)
        if entry:
            _render_bank_card(entry)

    questions = comparison.get("questions_to_verify") or []
    if questions:
        with st.expander("❓ כדאי לוודא מול הבנקים לפני החלטה סופית"):
            for q in questions:
                st.markdown(f"- {q}")

    st.download_button(
        '⬇️ הורד את הדו"ח המלא (קובץ טקסט)',
        data=st.session_state["mortgage_report_text"],
        file_name=st.session_state["mortgage_report_path"].name,
        mime="text/plain",
        use_container_width=True,
    )

    st.caption(
        'הדו"ח הוא כלי עזר להחלטה ואינו תחליף לבדיקה סופית מול הבנק ולשיקול הדעת המקצועי של היועץ.'
    )

render_footer("כלי השוואת הצעות משכנתא")
