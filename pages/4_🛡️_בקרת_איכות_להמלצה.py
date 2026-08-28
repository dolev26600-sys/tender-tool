#!/usr/bin/env python3
"""
עמוד: בקרת איכות על המלצת תמהיל, לפני שהיא יוצאת ללקוח.

מזינים את התמהיל המוצע (ידנית או מ-PDF של הצעת בנק), את נתוני העסקה, ומה
שהלקוח אמר בפגישה - והכלי מריץ שתי שכבות בדיקה: כללים מספריים
דטרמיניסטיים, ואחריהם סקירת שיפוט של Claude שמחפשת סתירות מול מה שהלקוח
אמר. ראה mortgage_review.py.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import streamlit as st

from mortgage_review import (
    BUYER_TYPE_LABELS,
    SEVERITY_LABELS,
    review_mix,
)
from mortgage_offer_extraction import extract_offer
from pdf_extraction import extract_text_from_pdf
from ui_common import check_password, configure_page, render_footer, render_header

TRACK_TYPE_OPTIONS = [
    "fixed_unlinked",
    "fixed_linked_cpi",
    "variable_prime",
    "variable_unlinked",
    "variable_linked_cpi",
    "eligibility",
    "other",
]

TRACK_TYPE_LABELS = {
    "fixed_unlinked": "קבועה לא צמודה",
    "fixed_linked_cpi": "קבועה צמודה מדד",
    "variable_prime": "פריים",
    "variable_unlinked": "משתנה לא צמודה",
    "variable_linked_cpi": "משתנה צמודה מדד",
    "eligibility": "זכאות",
    "other": "אחר",
}

SEVERITY_STYLE = {
    "critical": {"color": "#b91c1c", "bg": "#fee2e2"},
    "warning": {"color": "#a16207", "bg": "#fef9c3"},
    "note": {"color": "#475569", "bg": "#f1f5f9"},
}

EMPTY_ROW = {
    "name": "",
    "track_type": "fixed_unlinked",
    "amount": 0,
    "period_months": 240,
    "annual_interest_rate_pct": 0.0,
}

configure_page("בקרת איכות להמלצה")

if not check_password():
    st.stop()

render_header(
    "🛡️ בקרת איכות להמלצה",
    "חוות דעת שנייה על התמהיל, לפני שהוא יוצא ללקוח",
)

if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    st.error("שגיאת הגדרה: לא הוגדר מפתח API בשרת. פנה למי שהקים את הכלי.")
    st.stop()

st.caption(
    "הכלי מריץ בדיקות מספריות מדויקות, ואז סקירה שמחפשת סתירות בין התמהיל למה שהלקוח אמר. "
    "הוא לא מחליף את שיקול הדעת שלך - הוא נועד לתפוס את מה שקל לפספס."
)

if "qc_tracks" not in st.session_state:
    st.session_state["qc_tracks"] = [dict(EMPTY_ROW)]

# ---------------------------------------------------------------- התמהיל

st.subheader("התמהיל המוצע")

with st.expander("📄 טעינת התמהיל מקובץ PDF של הצעת בנק (במקום הזנה ידנית)"):
    offer_pdf = st.file_uploader("קובץ PDF של ההצעה", type=["pdf"], key="qc_pdf")
    if st.button("טען את התמהיל מהקובץ", disabled=offer_pdf is None):
        tmp_path = None
        try:
            with st.spinner("קורא את ההצעה..."):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                    tmp.write(offer_pdf.getvalue())
                    tmp_path = Path(tmp.name)
                pdf_text = extract_text_from_pdf(tmp_path)
                offer = extract_offer(pdf_text, source_hint=offer_pdf.name)
            st.session_state["qc_tracks"] = [
                {
                    "name": t.get("name", ""),
                    "track_type": t.get("track_type", "other"),
                    "amount": t.get("amount", 0),
                    "period_months": t.get("period_months", 0),
                    "annual_interest_rate_pct": t.get("annual_interest_rate_pct", 0.0),
                }
                for t in offer.get("tracks", [])
            ] or [dict(EMPTY_ROW)]
            st.success(f"נטענו {len(st.session_state['qc_tracks'])} מסלולים. אפשר לערוך אותם בטבלה למטה.")
        except Exception as e:  # noqa: BLE001 - מציגים כל שגיאה למשתמש בצורה ברורה
            st.error("לא הצלחתי לקרוא את התמהיל מהקובץ. אפשר להזין אותו ידנית בטבלה למטה.")
            with st.expander("פרטים טכניים של השגיאה"):
                st.exception(e)
        finally:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)

edited_tracks = st.data_editor(
    st.session_state["qc_tracks"],
    num_rows="dynamic",
    use_container_width=True,
    key="qc_editor",
    column_config={
        "name": st.column_config.TextColumn("שם המסלול", width="small"),
        "track_type": st.column_config.SelectboxColumn(
            "סוג", options=TRACK_TYPE_OPTIONS, required=True, width="small"
        ),
        "amount": st.column_config.NumberColumn("סכום (₪)", min_value=0, step=10000, format="%d", width="small"),
        "period_months": st.column_config.NumberColumn("תקופה (חודשים)", min_value=0, max_value=480, step=12, width="small"),
        "annual_interest_rate_pct": st.column_config.NumberColumn("ריבית (%)", min_value=0.0, step=0.05, format="%.2f", width="small"),
    },
)

st.caption(
    "סוגי מסלולים: "
    + " · ".join(f"`{k}` = {v}" for k, v in TRACK_TYPE_LABELS.items())
)

# ------------------------------------------------------------ נתוני העסקה

st.subheader("נתוני העסקה והלקוח")
st.caption("כל שדה אופציונלי - בדיקה שאין לה נתונים פשוט לא תרוץ. ככל שיש יותר נתונים, הבדיקה יסודית יותר.")

col1, col2 = st.columns(2)
with col1:
    property_value = st.number_input("שווי הנכס (₪)", min_value=0, step=50000, value=0)
    monthly_income = st.number_input("הכנסה חודשית פנויה (₪)", min_value=0, step=1000, value=0)
with col2:
    buyer_type_key = st.selectbox(
        "סוג הרוכש",
        options=["", *BUYER_TYPE_LABELS.keys()],
        format_func=lambda k: "לא צוין" if k == "" else BUYER_TYPE_LABELS[k],
    )
    horizon_years = st.number_input(
        "אופק התכנון של הלקוח (שנים)",
        min_value=0.0,
        max_value=40.0,
        step=1.0,
        value=0.0,
        help="בעוד כמה שנים הלקוח צופה למכור, לפרוע מוקדם או למחזר. 0 = לא צוין.",
    )

client_context = st.text_area(
    "מה שהלקוח אמר בפגישה",
    height=140,
    placeholder=(
        "לדוגמה: זוג בני 34, שכירים, מתכננים ילד שני בשנתיים הקרובות. "
        "אמרו שיקבלו ירושה בעוד כ-4 שנים ורוצים לפרוע חלק מהמשכנתא. "
        "בן הזוג שוקל לעבור לעצמאי."
    ),
    help="החלק הכי חשוב - כאן נמצאות הסתירות שבדיקה מספרית לא תופסת.",
)

with st.expander("⚙️ פרמטרים לתרחיש הקיצון"):
    rate_increase_pct = st.slider("עליית ריבית למסלולים משתנים (%)", 0.0, 5.0, 2.0, step=0.5, key="qc_rate")
    cpi_annual_pct = st.slider("עליית מדד שנתית למסלולים צמודים (%)", 0.0, 8.0, 3.0, step=0.5, key="qc_cpi")

valid_tracks = [t for t in edited_tracks if (t.get("amount") or 0) > 0 and (t.get("period_months") or 0) > 0]

review_clicked = st.button(
    "🛡️ בדוק את ההמלצה",
    type="primary",
    use_container_width=True,
    disabled=not valid_tracks,
)

if not valid_tracks:
    st.caption("הזן לפחות מסלול אחד עם סכום ותקופה כדי להפעיל את הכפתור.")

if review_clicked:
    st.session_state["qc_tracks"] = edited_tracks
    try:
        with st.spinner("בודק את התמהיל..."):
            result = review_mix(
                valid_tracks,
                property_value=property_value or None,
                monthly_income=monthly_income or None,
                buyer_type=buyer_type_key or None,
                horizon_years=horizon_years or None,
                client_context=client_context,
                rate_increase_pct=rate_increase_pct,
                cpi_annual_pct=cpi_annual_pct,
            )
        st.session_state["qc_result"] = result
    except Exception as e:  # noqa: BLE001 - מציגים כל שגיאה למשתמש בצורה ברורה
        st.error("קרתה שגיאה במהלך הבדיקה. אפשר לנסות שוב, ואם זה חוזר - לפנות למי שהקים את הכלי.")
        with st.expander("פרטים טכניים של השגיאה"):
            st.exception(e)


def _render_finding(f: dict) -> None:
    style = SEVERITY_STYLE.get(f.get("severity"), SEVERITY_STYLE["note"])
    source_label = "בדיקה מספרית" if f.get("source") == "rule" else "סקירת שיפוט"

    with st.container(border=True):
        st.markdown(
            f'<span class="status-badge" style="color:{style["color"]}; background:{style["bg"]};">'
            f'{SEVERITY_LABELS.get(f.get("severity"), "")}</span>'
            f'<span style="color:#94a3b8; font-size:0.78rem; margin-inline-start:0.6rem;">{source_label}</span>',
            unsafe_allow_html=True,
        )
        st.markdown(f"**{f.get('title', '')}**")
        st.markdown(f.get("detail", ""))
        action = f.get("suggested_action")
        if action:
            st.markdown(f"**מה לעשות:** {action}")


if "qc_result" in st.session_state:
    st.divider()
    result = st.session_state["qc_result"]
    stats = result["stats"]
    stress = result["stress_test"]
    findings = result["findings"]

    counts = {"critical": 0, "warning": 0, "note": 0}
    for f in findings:
        counts[f.get("severity", "note")] = counts.get(f.get("severity", "note"), 0) + 1

    if counts["critical"]:
        st.error(f"נמצאו {counts['critical']} ממצאים קריטיים — כדאי לטפל בהם לפני שההמלצה יוצאת ללקוח.", icon="🔴")
    elif counts["warning"]:
        st.warning(f"נמצאו {counts['warning']} נקודות ששוות בדיקה לפני סגירה.", icon="🟡")
    else:
        st.success("לא נמצאו ממצאים מהותיים — התמהיל נראה תקין.", icon="✅")

    verdict = result.get("overall_verdict")
    if verdict:
        st.info(verdict, icon="💬")

    cols = st.columns(4)
    cols[0].metric("סכום כולל", f"{stats.get('total_amount', 0):,.0f} ₪")
    cols[1].metric("ריבית משוקללת", f"{stats.get('blended_annual_interest_rate_pct', 0)}%")
    cols[2].metric("החזר חודשי", f"{stats.get('initial_total_monthly_payment', 0):,.0f} ₪")
    cols[3].metric(
        "בתרחיש קיצון",
        f"{stress.get('stressed_total_monthly_payment', 0):,.0f} ₪",
        delta=f"{stress.get('stressed_total_monthly_payment', 0) - stats.get('initial_total_monthly_payment', 0):,.0f} ₪",
        delta_color="inverse",
    )

    if findings:
        st.subheader(f"ממצאים ({len(findings)})")
        for f in findings:
            _render_finding(f)

    questions = result.get("questions_for_client") or []
    if questions:
        st.subheader("שאלות ללקוח לפני סגירה")
        for q in questions:
            st.markdown(f"- {q}")

    st.caption(
        "ערכי הסף הרגולטוריים בכלי הם ברירות מחדל לאימות מול הוראות בנק ישראל העדכניות, "
        "ולא ציטוט שלהן. תרחיש הקיצון הוא הערכה גסה להמחשה. האחריות המקצועית נשארת אצל היועץ."
    )

render_footer("בקרת איכות להמלצה")
