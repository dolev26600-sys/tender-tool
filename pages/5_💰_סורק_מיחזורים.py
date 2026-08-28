#!/usr/bin/env python3
"""
עמוד: סריקת מאגר הלקוחות לאיתור מועמדים למיחזור.

מעלים ייצוא CSV של משכנתאות קיימות, מזינים את ריביות השוק הנוכחיות,
ומקבלים רשימה מדורגת של מי כדאי לפנות אליו - עם עלות היציאה האמיתית,
נקודת האיזון, והאם עדיף מיחזור חלקי.

הכל דטרמיניסטי - אין כאן קריאה למודל שפה, ולכן העמוד עובד גם בלי מפתח API.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import streamlit as st

from refi_scan import CsvFormatError, recommendation, scan, to_summary_rows
from ui_common import check_password, configure_page, render_footer, render_header

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = BASE_DIR / "refi_scan_template.csv"

MARKET_RATE_FIELDS = [
    ("fixed_unlinked", "קבועה לא צמודה", 4.3),
    ("fixed_linked_cpi", "קבועה צמודה מדד", 3.2),
    ("variable_prime", "פריים", 5.2),
    ("variable_unlinked", "משתנה לא צמודה", 4.6),
    ("variable_linked_cpi", "משתנה צמודה מדד", 3.5),
]

configure_page("סורק מיחזורים")

if not check_password():
    st.stop()

render_header(
    "💰 סורק מיחזורים",
    "מי מהלקוחות הקיימים כדאי לפנות אליו עכשיו - כולל עלות היציאה האמיתית",
)

st.caption(
    "הכלי מחשב את עמלת הפירעון המוקדם לכל לקוח, ולא רק את החיסכון החודשי. "
    "חיסכון חודשי בלי עלות היציאה הוא המספר שהכי קל לטעות בו."
)

# ------------------------------------------------------------------ קלט

st.subheader("1. ייצוא הלקוחות")

if TEMPLATE_PATH.exists():
    st.download_button(
        "⬇️ הורד קובץ CSV לדוגמה (מבנה העמודות הנדרש)",
        data=TEMPLATE_PATH.read_text(encoding="utf-8"),
        file_name="refi_scan_template.csv",
        mime="text/csv",
    )

st.caption(
    "שורה אחת לכל מסלול, מקובצות לפי `client_id`. עמודות חובה: "
    "`client_id`, `track_type`, `original_amount`, `annual_interest_rate_pct`, "
    "`original_period_months`, `months_elapsed`. אופציונלי: `client_name`, `phone`, `track_name`."
)

uploaded = st.file_uploader("ייצוא CSV מה-CRM", type=["csv"])

use_sample = st.checkbox(
    "הרץ על קובץ הדוגמה (לבדיקת הכלי לפני שמעלים נתונים אמיתיים)",
    value=False,
)

st.subheader("2. ריביות השוק הנוכחיות")
st.caption(
    "הנתון הקובע: עמלת היוון נגבית **רק** כשריבית ההלוואה גבוהה מריבית השוק "
    "לאותו מסלול. ריביות לא מעודכנות כאן ישבשו את כל התוצאות."
)

market_rates = {}
rate_cols = st.columns(3)
for i, (key, label, default) in enumerate(MARKET_RATE_FIELDS):
    with rate_cols[i % 3]:
        market_rates[key] = st.number_input(label + " (%)", min_value=0.0, max_value=15.0, value=default, step=0.05)

st.subheader("3. ההצעה החדשה ופרמטרים")

col1, col2 = st.columns(2)
with col1:
    new_offer_rate_pct = st.number_input("ריבית ההצעה החדשה (%)", min_value=0.0, max_value=15.0, value=4.4, step=0.05)
    new_term_months = st.number_input("תקופת ההצעה החדשה (חודשים)", min_value=12, max_value=480, value=300, step=12)
    avg_cpi = st.number_input(
        "שינוי מדד ממוצע ב-12 החודשים האחרונים (%)",
        min_value=0.0, max_value=15.0, value=2.5, step=0.1,
        help="משפיע על עמלת פיצוי המדד במסלולים צמודים בלבד.",
    )
with col2:
    horizon_years = st.slider(
        "אופק ההערכה (שנים)",
        min_value=1, max_value=25, value=5,
        help=(
            "הפרמטר המכריע. אותו מיחזור יכול להיות כדאי מאוד ללקוח שיישאר 15 שנה "
            "ולא כדאי כלל למי שמוכר בעוד 4."
        ),
    )
    seniority_discount = st.slider(
        "הנחת ותק על עמלת ההיוון (%)",
        min_value=0, max_value=40, value=0,
        help=(
            "על עמלת ההיוון חלה הנחה מדורגת. ברירת המחדל 0 היא הערכה שמרנית - "
            "העמלה בפועל עשויה להיות נמוכה יותר, כלומר המיחזור כדאי יותר."
        ),
    )

scan_clicked = st.button(
    "🔍 סרוק את המאגר",
    type="primary",
    use_container_width=True,
    disabled=uploaded is None and not use_sample,
)

if uploaded is None and not use_sample:
    st.caption("העלה קובץ CSV, או סמן את תיבת קובץ הדוגמה, כדי להפעיל את הכפתור.")

if scan_clicked:
    try:
        if uploaded is not None:
            csv_text = uploaded.getvalue().decode("utf-8-sig")
        else:
            csv_text = TEMPLATE_PATH.read_text(encoding="utf-8")

        results = scan(
            csv_text,
            market_rates_by_track_type=market_rates,
            new_offer_rate_pct=new_offer_rate_pct,
            new_term_months=int(new_term_months),
            avg_cpi_change_12m_pct=avg_cpi,
            seniority_discount_pct=float(seniority_discount),
            evaluation_horizon_months=horizon_years * 12,
        )
        phones = {}
        for row in csv.DictReader(io.StringIO(csv_text)):
            if row.get("client_id") and row.get("phone"):
                phones.setdefault(row["client_id"].strip(), row["phone"].strip())

        st.session_state["refi_results"] = results
        st.session_state["refi_phones"] = phones

    except CsvFormatError as e:
        st.error(f"בעיה בקובץ: {e}")
    except Exception as e:  # noqa: BLE001 - מציגים כל שגיאה למשתמש בצורה ברורה
        st.error("קרתה שגיאה במהלך הסריקה. אפשר לנסות שוב, ואם זה חוזר - לפנות למי שהקים את הכלי.")
        with st.expander("פרטים טכניים של השגיאה"):
            st.exception(e)

# ---------------------------------------------------------------- תוצאות

if "refi_results" in st.session_state:
    st.divider()
    results = st.session_state["refi_results"]
    phones = st.session_state.get("refi_phones", {})

    worth = [a for a in results if recommendation(a) != "לא למחזר"]
    total_benefit = sum(a.best_net_benefit for a in worth)

    cols = st.columns(3)
    cols[0].metric("לקוחות שנסרקו", len(results))
    cols[1].metric("מועמדים למיחזור", len(worth))
    cols[2].metric("תועלת מצטברת ללקוחות", f"{total_benefit:,.0f} ₪")

    if not worth:
        st.info("לא נמצאו מועמדים כדאיים בפרמטרים הנוכחיים. נסה אופק הערכה ארוך יותר או ריבית הצעה נמוכה יותר.")

    summary = to_summary_rows(results, phones)
    st.dataframe(summary, use_container_width=True, hide_index=True)

    out = io.StringIO()
    if summary:
        writer = csv.DictWriter(out, fieldnames=list(summary[0].keys()))
        writer.writeheader()
        writer.writerows(summary)
        st.download_button(
            "⬇️ הורד את הסיכום כ-CSV",
            data="﻿" + out.getvalue(),
            file_name="refi_scan_results.csv",
            mime="text/csv",
            use_container_width=True,
        )

    st.subheader("פירוט לכל לקוח")
    for a in results:
        rec = recommendation(a)
        icon = {"מיחזור חלקי": "🟢", "מיחזור מלא": "🟢", "לא למחזר": "⚪"}[rec]

        with st.expander(f"{icon} {a.client_name} — {rec} · תועלת נטו {a.best_net_benefit:,.0f} ₪"):
            if a.saving_is_mostly_term_extension:
                st.warning(
                    f"רוב ה\"חיסכון\" החודשי בהצעה כפי שהוזנה ({a.monthly_saving:,.0f} ₪) נובע "
                    f"מהארכת התקופה ב-{a.term_extended_months} חודשים, לא משיפור ריבית. "
                    f"שיפור הריבית לבדו שווה {a.rate_only_monthly_saving:,.0f} ₪ בחודש.",
                    icon="⚠️",
                )

            c = st.columns(3)
            c[0].metric("יתרת קרן", f"{a.exit_cost.total_balance:,.0f} ₪")
            c[1].metric("החזר חודשי היום", f"{a.current_monthly:,.0f} ₪")
            c[2].metric("עלות יציאה מלאה", f"{a.total_fee:,.0f} ₪")

            st.markdown("**כדאיות לכל מסלול בנפרד:**")
            for t in a.track_analyses:
                mark = "✅" if t.is_worthwhile_for(a.evaluation_horizon_months) else "❌"
                be = f"{t.breakeven_months:,.0f} חודשים" if t.breakeven_months is not None else "לא מחזיר את עצמו"
                st.markdown(
                    f"{mark} **{t.name or t.track_type}** · ריבית {t.loan_rate_pct}% · "
                    f"יתרה {t.balance:,.0f} ₪ · חיסכון {t.monthly_saving:,.0f} ₪/חודש · "
                    f"עמלת יציאה {t.exit_fee:,.0f} ₪ · איזון: {be}"
                )

            st.markdown(
                f"**מיחזור חלקי** (רק המסלולים המסומנים ✅): חיסכון "
                f"{a.partial_monthly_saving:,.0f} ₪/חודש, עלות יציאה {a.partial_exit_fee:,.0f} ₪, "
                f"תועלת נטו {a.partial_net_benefit:,.0f} ₪."
            )
            st.markdown(
                f"**מיחזור מלא** (ללא הארכת תקופה): תועלת נטו {a.term_neutral_net_benefit:,.0f} ₪."
            )

    st.caption(
        "עמלות הפירעון המוקדם הן הערכה על בסיס מבנה העמלות המקובל, ואינן תחליף "
        "לדף עמלות רשמי מהבנק. יש לאמת מול הבנק לפני פנייה ללקוח עם מספרים."
    )

render_footer("סורק מיחזורים")
