#!/usr/bin/env python3
"""
עמוד: סריקת דוח יתרות ובדיקת כדאיות מיחזור.

תהליך: PDF של דוח יתרות -> טקסט (pdf_extraction) -> חילוץ מסלולים
(mortgage_balance_extraction, Claude) -> בדיקות תקינות והשוואה מול שחזור
(דטרמיניסטי) -> ניתוח כדאיות מיחזור (mortgage_refi, דטרמיניסטי).

Claude קורא את המסמך. כל מספר נגזר מחושב בפייתון.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from market_rates import load_rates, market_rates_by_track_type, rates_status
from mortgage_balance_extraction import (
    blockers,
    extract_balance_report,
    to_refi_tracks,
    validate_report,
)
from mortgage_refi import analyze_refi, reconcile_tracks
from pdf_extraction import extract_text_from_pdf
from refi_scan import recommendation
from ui_common import check_password, configure_page, render_footer, render_header

TRACK_TYPE_LABELS = {
    "fixed_unlinked": "קבועה לא צמודה",
    "fixed_linked_cpi": "קבועה צמודה מדד",
    "variable_prime": "פריים",
    "variable_unlinked": "משתנה לא צמודה",
    "variable_linked_cpi": "משתנה צמודה מדד",
    "eligibility": "זכאות",
    "other": "אחר",
}
SEVERITY_ICON = {"blocker": "🔴", "warn": "🟡", "note": "⚪"}

configure_page("סריקת דוח יתרות")

if not check_password():
    st.stop()

render_header(
    "📄 סריקת דוח יתרות",
    "מעלים דוח יתרות מהבנק, והכלי קורא את המסלולים ובודק כדאיות מיחזור",
)

if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    st.error("שגיאת הגדרה: לא הוגדר מפתח API בשרת. פנה למי שהקים את הכלי.")
    st.stop()

st.caption(
    "1️⃣ מעלים דוח יתרות (PDF)  ·  2️⃣ הכלי קורא את המסלולים ומסמן מה חסר  "
    "·  3️⃣ משלימים ידנית ומריצים כדאיות"
)

# ------------------------------------------------------------ ריביות השוק
rates_data = load_rates()
status = rates_status(rates_data)
if status.warning:
    st.warning(f"⚠️ {status.warning}")

uploaded = st.file_uploader("דוח יתרות של המשכנתא הקיימת (PDF)", type=["pdf"])

if st.button("📄 קרא את הדוח", type="primary", use_container_width=True, disabled=not uploaded):
    tmp_path = None
    try:
        with st.spinner("קורא את הדוח..."):
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(uploaded.getvalue())
                tmp_path = Path(tmp.name)
            pdf_text = extract_text_from_pdf(tmp_path)
            if len(pdf_text.strip()) < 100:
                st.error(
                    "כמעט ולא חולץ טקסט מהקובץ. סביר שזה סריקה/צילום ולא PDF טקסטואלי. "
                    "בקש מהבנק את הדוח כקובץ דיגיטלי, או הקלד את המסלולים ידנית."
                )
                st.stop()
            report = extract_balance_report(pdf_text, source_hint=uploaded.name)
        st.session_state["balance_report"] = report
    except Exception as e:  # noqa: BLE001 - מציגים שגיאה ברורה למשתמש
        st.error(f"שגיאה בקריאת הדוח: {e}")
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

report = st.session_state.get("balance_report")
if not report:
    st.stop()

st.divider()
meta = " · ".join(x for x in [
    report.get("bank_name"),
    f"נכון ל-{report['report_date']}" if report.get("report_date") else None,
    f"{len(report.get('tracks') or [])} מסלולים",
] if x)
st.subheader("מה נקרא מהדוח")
st.write(meta)

# ------------------------------------------------------------- תקינות
issues = validate_report(report)
if issues:
    with st.expander(f"בדיקות תקינות ({len(issues)})", expanded=bool(blockers(issues))):
        for i in issues:
            st.write(f"{SEVERITY_ICON.get(i['severity'], '•')} {i['message']}")

# --------------------------------------------------- טבלת מסלולים לעריכה
tracks = to_refi_tracks(report)
if not tracks:
    st.error("לא זוהו מסלולים בדוח.")
    st.stop()

st.markdown("**המסלולים — אפשר לתקן כל שדה לפני החישוב**")
st.caption(
    "שדה ריק פירושו שלא נמצא בדוח, לא שהוא אפס. מועד עדכון הריבית הוא "
    "השדה ששווה הכי הרבה: בתחנה אין עמלת היוון."
)

editor_df = pd.DataFrame([{
    "מסלול": t.get("name", ""),
    "סוג": TRACK_TYPE_LABELS.get(t.get("track_type"), t.get("track_type", "")),
    "יתרה היום": t.get("current_balance"),
    "חודשים שנותרו": t.get("remaining_months"),
    "ריבית %": t.get("annual_interest_rate_pct"),
    "החזר חודשי": t.get("current_monthly_payment"),
    "עדכון ריבית כל (ח׳)": t.get("rate_reset_period_months"),
    "חודשים לתחנה": t.get("months_to_next_reset"),
} for t in tracks])

edited = st.data_editor(
    editor_df, use_container_width=True, hide_index=True, num_rows="fixed",
    column_config={
        "סוג": st.column_config.SelectboxColumn(options=list(TRACK_TYPE_LABELS.values())),
        "חודשים לתחנה": st.column_config.NumberColumn(
            help="0 = פירעון בתחנה עצמה (ללא עמלת היוון). ריק = לא ידוע, והכלי יחשב עמלה מלאה."),
    },
)

label_to_type = {v: k for k, v in TRACK_TYPE_LABELS.items()}


def _num(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else float(v)


engine_tracks = []
for (_, row), original in zip(edited.iterrows(), tracks):
    t = {
        "name": row["מסלול"],
        "track_type": label_to_type.get(row["סוג"], original.get("track_type", "other")),
        "current_balance": _num(row["יתרה היום"]),
        "remaining_months": _num(row["חודשים שנותרו"]),
        "annual_interest_rate_pct": _num(row["ריבית %"]),
        "current_monthly_payment": _num(row["החזר חודשי"]),
        "rate_reset_period_months": _num(row["עדכון ריבית כל (ח׳)"]),
        "months_to_next_reset": _num(row["חודשים לתחנה"]),
        "original_amount": original.get("original_amount"),
        "original_period_months": original.get("original_period_months"),
        "months_elapsed": original.get("months_elapsed"),
    }
    engine_tracks.append({k: v for k, v in t.items() if v is not None})

# ------------------------------------------------------------- קלטים
st.divider()
col_a, col_b = st.columns(2)
with col_a:
    st.markdown("**ההצעה החדשה**")
    new_rate = st.number_input("ריבית מוצעת (%)", value=4.5, step=0.05, format="%.2f")
    longest = max((int(t.get("remaining_months") or 0) for t in engine_tracks), default=240)
    new_term = st.number_input("תקופה (חודשים)", value=longest or 240, step=12)
with col_b:
    st.markdown("**פרמטרים**")
    horizon = st.number_input("אופק ההערכה (חודשים)", value=60, step=12,
                              help="כמה זמן הלקוח מתכנן להישאר. זה מה שקובע אם המיחזור מחזיר את עצמו.")
    cpi = st.number_input("מדד ממוצע 12ח׳ (%)", value=0.0, step=0.1)
    seniority = st.number_input("הנחת ותק (%)", value=0.0, step=5.0,
                                help="0 מעריך את העמלה כלפי מעלה — הכיוון הבטוח.")
    notice = st.checkbox("הודעה מוקדמת בכתב (10–45 יום)", value=True)

with st.expander("ריביות השוק לחישוב עמלת ההיוון"):
    st.caption(f"נכון ל-{status.as_of} · מקור: {status.source}")
    market = {}
    used_types = sorted({t["track_type"] for t in engine_tracks} - {"variable_prime"})
    defaults = market_rates_by_track_type(rates_data)
    for ty in used_types:
        market[ty] = st.number_input(
            TRACK_TYPE_LABELS.get(ty, ty), value=float(defaults.get(ty, 4.5)), step=0.05, format="%.2f",
            key=f"mkt_{ty}")

if blockers(issues):
    st.warning("יש שדות חסרים שסומנו כחוסמים. השלם אותם בטבלה למעלה לפני שמסתמכים על התוצאה.")

# ------------------------------------------------------------- ניתוח
if not st.button("💰 בדוק כדאיות מיחזור", type="primary", use_container_width=True):
    st.stop()

analysis = analyze_refi(
    "scan", report.get("bank_name", "לקוח"), engine_tracks,
    market_rates_by_track_type=market,
    new_offer_rate_pct=new_rate, new_term_months=int(new_term),
    avg_cpi_change_12m_pct=cpi, seniority_discount_pct=seniority,
    give_advance_notice=notice, evaluation_horizon_months=int(horizon),
)
ec = analysis.exit_cost
rec = recommendation(analysis)

st.divider()
{"מיחזור מלא": st.success, "מיחזור חלקי": st.warning}.get(rec, st.error)(f"### {rec}")

m1, m2, m3, m4 = st.columns(4)
m1.metric("יתרת קרן", f"{ec.total_balance:,.0f} ₪")
m2.metric("עלות יציאה", f"{analysis.total_fee:,.0f} ₪")
m3.metric("שיפור ריבית", f"{analysis.rate_only_monthly_saving:,.0f} ₪",
          help="לחודש, בלי הארכת תקופה")
m4.metric("תועלת נטו", f"{analysis.best_net_benefit:,.0f} ₪", help=f"על פני {horizon} חודשים")

# ---- ההמלצה ששווה הכי הרבה: המתנה לתחנה
saving = ec.saving_from_waiting_for_resets
if saving > 0:
    nearest = ec.tracks_with_upcoming_reset[0]
    st.info(
        f"**המתנה לתחנה חוסכת {saving:,.0f} ₪.** במסלול «{nearest.name}» יש תחנת עדכון ריבית "
        f"בעוד {nearest.months_to_next_reset} חודשים, ובתחנה אין עמלת היוון. "
        f"עלות היציאה יורדת מ-{analysis.total_fee:,.0f} ₪ ל-"
        f"{analysis.total_fee - saving:,.0f} ₪."
    )

if analysis.saving_is_mostly_term_extension:
    st.warning(
        f"**רוב ה״חיסכון״ הוא הארכת תקופה.** ההחזר יורד ב-{analysis.monthly_saving:,.0f} ₪, "
        f"אבל רק {analysis.rate_only_monthly_saving:,.0f} ₪ מזה מהריבית."
    )

st.markdown("**פירוט לפי מסלול**")
st.dataframe(pd.DataFrame([{
    "מסלול": t.name or TRACK_TYPE_LABELS.get(t.track_type, ""),
    "יתרה": round(t.balance),
    "ריבית %": t.loan_rate_pct,
    "עמלת היוון": round(t.capitalization),
    "פטור": t.capitalization_exempt_reason or "",
    "חודשים לתחנה": t.months_to_next_reset if t.months_to_next_reset is not None else "",
} for t in ec.tracks]), use_container_width=True, hide_index=True)

# ---- יתרה מדווחת מול משוחזרת
recon = reconcile_tracks(engine_tracks)
flagged = [r for r in recon if r.severity != "ok"]
if flagged:
    with st.expander(f"יתרה מדווחת מול שחזור מלוח הסילוקין ({len(flagged)})"):
        for r in flagged:
            st.write(
                f"{'🟡' if r.severity == 'check' else '⚪'} **{r.name}** — "
                f"דוח {r.reported_balance:,.0f} ₪ מול שחזור {r.reconstructed_balance:,.0f} ₪ "
                f"({r.gap_pct:+.1f}%). {r.explanation}"
            )

render_footer("סריקת דוח יתרות")
