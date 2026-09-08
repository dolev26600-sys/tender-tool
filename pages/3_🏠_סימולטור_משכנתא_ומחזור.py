#!/usr/bin/env python3
"""
עמוד: סימולטור משכנתאות ומחזור.

כלי נפרד לגמרי מכלי בדיקת תנאי הסף (זהו מוצר אחר, שחי באותו repo)
לפי אפיון "סימולטור משכנתאות ומחזור" - ראה README.md, סעיף המתאים.

עקרון־על מהאפיון (סעיף 0): המנוע לא ממציא מספרים. כל מספר על המסך
נושא חותמת "מחושב לפי תצורה מתאריך X", וכל שדה חסר בתצורה מוצג כ"חסר
נתון" ולא כברירת מחדל שקטה. נתוני התצורה תחת data/mortgage/*.json הם
**נתוני דוגמה בלבד** לצורך הרצה - יש להחליף אותם בנתונים אמיתיים לפני
שימוש מול לקוחות (ראה אזהרה בראש העמוד).

היקף המימוש הנוכחי (MVP): מנוע לוח הסילוקין, שכבת התצורה, עמלת פירעון
מוקדם, מנוע הכללים, מנוע ההמלצות (כולל מחזור חלקי והמתנה לתחנה) ותרחישי
לחץ - ממומשים ובדוקים (tests/test_mortgage_*.py). קליטת PDF, ייצוא דו"ח
PDF ממותג, שמירה בקישור, ואינטגרציות ליד עדיין לא ממומשים (סעיפים 8, 9
החלקי, 11 באפיון) - מוזכר גם בהערת הפרטיות שבתחתית העמוד.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from mortgage.config import load_config
from mortgage.fees import total_prepayment_fee_for_tracks
from mortgage.metrics import combined_household_schedule, present_value, summarize
from mortgage.recommend import (
    evaluate_refinance_subsets, generate_alternatives, get_bank_rate,
    rank_alternatives, refinance_headline, wait_for_reset_alternative,
)
from mortgage.rules import evaluate_mix
from mortgage.scenarios import build_standard_scenarios
from mortgage.schedule import Scenario, Track, generate_schedule
from ui_common import check_password, render_footer

TRACK_KIND_LABELS = {
    "fixedNonLinked": "קבועה לא צמודה (קל\"צ)",
    "fixedLinked": "קבועה צמודה",
    "prime": "פריים",
    "varNonLinked": "משתנה לא צמודה",
    "varLinked": "משתנה צמודה",
    "bullet": "בלון / גרייס",
}
SCHEDULE_LABELS = {"spitzer": "שפיצר", "equalPrincipal": "קרן שווה", "bullet": "בלון", "grace": "גרייס"}


def _page_setup():
    st.set_page_config(page_title="סימולטור משכנתא ומחזור", page_icon="🏠", layout="wide")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700&display=swap');
        html, body { font-family: 'Assistant', -apple-system, 'Segoe UI', sans-serif; }
        p, li, label, h1, h2, h3, h4, h5, h6 { direction: rtl; text-align: right; }
        .stTextInput input, .stTextArea textarea, .stNumberInput input { direction: rtl; text-align: right; }
        .mtg-disclaimer { background:#fef9c3; border-radius:8px; padding:0.75rem 1rem; font-size:0.85rem; color:#713f12; }
        .mtg-freshness { color:#64748b; font-size:0.8rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


_page_setup()

if not check_password():
    st.stop()

st.title("🏠 סימולטור משכנתאות ומחזור")
st.caption("הזן את המשכנתא הקיימת שלך וקבל תמונת מצב, חלופות מחזור מנומקות, ותרחישי לחץ.")

try:
    CONFIG = load_config()
except Exception as e:  # noqa: BLE001
    st.error("שגיאת תצורה: לא ניתן לטעון את קבצי הנתונים (rates.json / rules.json / fees.json).")
    st.exception(e)
    st.stop()


def _freshness_banner():
    for label, freshness in [
        ("ריביות", CONFIG.rates_freshness), ("כללי רגולציה", CONFIG.rules_freshness),
        ("עמלות", CONFIG.fees_freshness),
    ]:
        if freshness.is_stale:
            st.warning(f"⚠️ תצורת \"{label}\" סומנה כישנה: {freshness.label}. יש לעדכן לפני הצגה ללקוח.")
    st.markdown(
        f'<div class="mtg-freshness">מחושב לפי תצורת ריביות מתאריך {CONFIG.rates_freshness.updated_at} · '
        f'תצורת כללים מתאריך {CONFIG.rules_freshness.updated_at} · '
        f'תצורת עמלות מתאריך {CONFIG.fees_freshness.updated_at}</div>',
        unsafe_allow_html=True,
    )


_freshness_banner()

st.markdown(
    '<div class="mtg-disclaimer">⚠️ <b>נתוני התצורה הנוכחיים הם נתוני דוגמה בלבד</b> '
    '(data/mortgage/*.json) לצורך הרצה ובדיקה - הריביות, הכללים והעמלות '
    'המוצגים אינם ריביות אמיתיות בשוק. יש להחליף אותם בנתונים מעודכנים '
    'לפני שימוש מול לקוחות אמיתיים.</div>',
    unsafe_allow_html=True,
)

mode = st.sidebar.radio("מצב תצוגה", ["מצב לקוח (פשוט)", "מצב יועץ (מלא)"], index=0)
is_advisor = mode.startswith("מצב יועץ")

# --------------------------------------------------------------------------
# קליטת המשכנתא הקיימת
# --------------------------------------------------------------------------
st.header("1. המשכנתא הקיימת שלך")

if "tracks_df" not in st.session_state:
    st.session_state["tracks_df"] = pd.DataFrame([
        {"מזהה": "מסלול 1", "סוג מסלול": "fixedNonLinked", "יתרה (ש\"ח)": 600000.0,
         "ריבית שנתית (%)": 5.2, "חודשים שנותרו": 220, "חודשים מקוריים": 240,
         "לוח סילוקין": "spitzer", "תחנת יציאה כל (חודשים)": 0, "חודשים לתחנה הקרובה": 0},
        {"מזהה": "מסלול 2", "סוג מסלול": "prime", "יתרה (ש\"ח)": 400000.0,
         "ריבית שנתית (%)": 7.0, "חודשים שנותרו": 220, "חודשים מקוריים": 240,
         "לוח סילוקין": "spitzer", "תחנת יציאה כל (חודשים)": 0, "חודשים לתחנה הקרובה": 0},
    ])

st.caption("ערוך/הוסף/מחק שורות לפי המסלולים במשכנתא הקיימת שלך (ניתן להוסיף עד כמה מסלולים שיש בפועל).")
edited = st.data_editor(
    st.session_state["tracks_df"],
    num_rows="dynamic",
    use_container_width=True,
    column_config={
        "סוג מסלול": st.column_config.SelectboxColumn(options=list(TRACK_KIND_LABELS.keys())),
        "לוח סילוקין": st.column_config.SelectboxColumn(options=list(SCHEDULE_LABELS.keys())),
    },
    key="tracks_editor",
)
st.session_state["tracks_df"] = edited


def _row_to_track(row) -> Track:
    kind = row["סוג מסלול"]
    reset_every = int(row.get("תחנת יציאה כל (חודשים)") or 0) or None
    next_reset = int(row.get("חודשים לתחנה הקרובה") or 0) if reset_every else None
    return Track(
        id=str(row["מזהה"]), kind=kind, balance=float(row["יתרה (ש\"ח)"]),
        rate=float(row["ריבית שנתית (%)"]), months_left=int(row["חודשים שנותרו"]),
        original_months=int(row["חודשים מקוריים"]), schedule=row["לוח סילוקין"],
        linked_to_cpi=kind in ("fixedLinked", "varLinked"),
        reset_every_months=reset_every, months_to_next_reset=next_reset,
    )


try:
    existing_tracks = [_row_to_track(row) for _, row in edited.iterrows() if row.get("יתרה (ש\"ח)", 0) > 0]
except Exception as e:  # noqa: BLE001
    st.error("שגיאה בקריאת המסלולים - בדוק שכל השדות מולאו כראוי.")
    st.exception(e)
    st.stop()

if not existing_tracks:
    st.info("הוסף לפחות מסלול אחד כדי להמשיך.")
    st.stop()

total_balance = sum(t.balance for t in existing_tracks)
base_scenario_current = Scenario(name="בסיס", annual_inflation=0.0, anchor_delta_path=[])

# --------------------------------------------------------------------------
# תמונת מצב נוכחית
# --------------------------------------------------------------------------
st.header("2. תמונת מצב נוכחית")

rows_by_track = {t.id: generate_schedule(t, base_scenario_current) for t in existing_tracks}
combined = combined_household_schedule(rows_by_track)
combined_df = pd.DataFrame(combined)

col1, col2, col3, col4 = st.columns(4)
col1.metric("יתרה כוללת", f"{total_balance:,.0f} ₪", help="סכום יתרות כל המסלולים כפי שהוזנו")
col2.metric("החזר חודשי כולל (היום)", f"{combined_df.iloc[0]['payment']:,.0f} ₪" if not combined_df.empty else "-",
            help="סכום ההחזר החודשי של כל המסלולים יחד, בחודש הראשון, בתרחיש הבסיס (ללא שינוי ריבית/אינפלציה)")
col3.metric("סך תשלומים עתידי (נומינלי)", f"{combined_df['payment'].sum():,.0f} ₪" if not combined_df.empty else "-",
            help="סכום כל התשלומים העתידיים על כל המסלולים, בערכים נומינליים (בלי היוון)")
col4.metric("סך ריבית+הצמדה צפויה", f"{(combined_df['payment'].sum()-combined_df['principal'].sum()):,.0f} ₪"
            if not combined_df.empty else "-", help="ריבית + הפרשי הצמדה שישולמו לאורך חיי ההלוואה מעבר לקרן")

if not combined_df.empty:
    chart_df = combined_df.set_index("month")[["principal", "interest"]]
    chart_df.columns = ["קרן", "ריבית+הצמדה"]
    st.bar_chart(chart_df)
    balance_df = combined_df.set_index("month")[["balance"]]
    balance_df.columns = ["יתרה לסילוק"]
    st.line_chart(balance_df)

st.subheader("כללי רגולציה (בזמן אמת)")
rules_cfg_new = CONFIG.rules.get("newLoan", {})
violations_now = evaluate_mix(existing_tracks, rules_cfg_new)
if violations_now:
    for v in violations_now:
        (st.error if v["severity"] == "blocking" else st.warning)(v["message"])
else:
    st.success("התמהיל הנוכחי עומד בכללי הרגולציה שהוגדרו בתצורה.")

# --------------------------------------------------------------------------
# תרחישי לחץ
# --------------------------------------------------------------------------
st.header("3. תרחישי לחץ")

with st.expander("הנחות תרחיש (ניתנות לשינוי)" if is_advisor else "הנחות תרחיש", expanded=is_advisor):
    base_inflation = st.number_input("אינפלציה שנתית - תרחיש בסיס (%)", value=2.0, step=0.5,
                                      disabled=not is_advisor)
    high_inflation = st.number_input("אינפלציה שנתית - תרחיש גבוה (%)", value=5.0, step=0.5,
                                      disabled=not is_advisor)
    rate_steps_str = st.text_input("מדרג עליית ריבית (%, מופרד בפסיקים)", value="1,2,3",
                                    disabled=not is_advisor)
    ramp_months = st.number_input("אורך כל שלב עלייה (חודשים)", value=12, step=1, min_value=1,
                                   disabled=not is_advisor)
    rate_steps = [float(x.strip()) for x in rate_steps_str.split(",") if x.strip()]

scenarios = build_standard_scenarios(base_inflation, high_inflation, rate_steps, int(ramp_months))

scenario_rows = []
for key, label in [("base", "בסיס"), ("rate_up", "עליית ריבית"), ("inflation_up", "אינפלציה גבוהה"), ("combined", "משולב")]:
    sc = scenarios[key]
    rows_by_track_sc = {t.id: generate_schedule(t, sc) for t in existing_tracks}
    combined_sc = combined_household_schedule(rows_by_track_sc)
    summary_payments = [r["payment"] for r in combined_sc]
    scenario_rows.append({
        "תרחיש": label,
        "החזר ראשון": summary_payments[0] if summary_payments else 0,
        "החזר מקסימלי": max(summary_payments) if summary_payments else 0,
        "סך תשלומים": sum(summary_payments),
    })
st.dataframe(pd.DataFrame(scenario_rows).style.format({
    "החזר ראשון": "{:,.0f} ₪", "החזר מקסימלי": "{:,.0f} ₪", "סך תשלומים": "{:,.0f} ₪"
}), use_container_width=True, hide_index=True)
st.caption("ההחזר החודשי המקסימלי בתרחיש המשולב הוא המספר הקריטי - הוא קובע אם משק הבית שורד במקרה הגרוע.")

# --------------------------------------------------------------------------
# עמלת פירעון מוקדם
# --------------------------------------------------------------------------
st.header("4. עמלת פירעון מוקדם (לו היית ממחזר היום)")
notice_given = st.checkbox("הודעתי לבנק מראש (מבטל את עמלת אי-ההודעה המוקדמת)", value=False)
fee_result = total_prepayment_fee_for_tracks(existing_tracks, CONFIG, notice_given)
for per_track in fee_result["per_track"]:
    with st.expander(f"מסלול {per_track['track_id']} - " +
                      (f"סה\"כ {per_track['total']:,.0f} ₪" if per_track["total"] is not None else "חסר נתון בחלק מהרכיבים")):
        for name, comp in per_track["components"].items():
            if comp.get("missing"):
                st.warning(f"{name}: חסר נתון - {comp.get('reason')}")
            else:
                amount = comp.get("amount")
                st.write(f"**{name}**: {amount:,.0f} ₪" if amount is not None else f"**{name}**: לא רלוונטי")
                if comp.get("reason"):
                    st.caption(comp["reason"])
if fee_result["has_missing_data"]:
    st.warning("סך העמלה הכולל לא ניתן לחישוב מלא - יש רכיב עם נתון חסר בתצורה (ראה לעיל).")
else:
    st.info(f"סך עמלת הפירעון המוקדם על כל המסלולים יחד: **{fee_result['total']:,.0f} ₪** — {CONFIG.fees_freshness.label}")

# --------------------------------------------------------------------------
# מנוע ההמלצות
# --------------------------------------------------------------------------
st.header("5. חלופות מחזור")

term_years = st.slider("תקופת ההלוואה החדשה המבוקשת (שנים)", 5, 30, 20)
discount_rate = st.number_input("שיעור היוון להשוואה (%)", value=4.0, step=0.5,
                                help="שיעור ההיוון (ריבית) המשמש לחישוב ערך נוכחי - קובע כמה 'שווה היום' תשלום עתידי")

if st.button("🔍 מצא חלופות מחזור", type="primary"):
    with st.spinner("סורק חלופות מחזור..."):
        alternatives = generate_alternatives(
            amount=total_balance, term_years=term_years, config=CONFIG,
            rules_cfg=rules_cfg_new, scenarios=scenarios, discount_rate=discount_rate,
        )
    if not alternatives:
        st.error("לא נמצאה אף חלופה חוקית מול כללי הרגולציה שהוגדרו בתצורה.")
    else:
        ranked = rank_alternatives(alternatives)
        cols = st.columns(4)
        for col, key in zip(cols, ["cheapest", "lowest_payment", "most_resilient", "balanced"]):
            entry = ranked[key]
            alt = entry["alternative"]
            with col:
                st.subheader(entry["label"])
                st.caption(f"בנק: {alt['bank_name']}")
                shares_text = ", ".join(f"{TRACK_KIND_LABELS.get(k,k)}: {s:.0%}" for k, s in alt["shares"].items() if s > 0)
                st.write(shares_text)
                st.metric("ערך נוכחי (תרחיש בסיס)", f"{alt['metrics']['per_scenario']['base']['pv']:,.0f} ₪")
                if "combined" in alt["metrics"]["per_scenario"]:
                    st.metric("החזר מקס' בתרחיש משולב", f"{alt['metrics']['per_scenario']['combined']['max_payment']:,.0f} ₪")
                st.caption(entry["explanation"])

        # מחזור חלקי מול מלא מול אי-עשייה
        st.subheader("מחזור חלקי מול מלא מול אי-עשייה")
        best_bank = min(CONFIG.banks(), key=lambda b: get_bank_rate(b, "fixedNonLinked", "typ", term_years=term_years)
                        if "byTerm" in (b.get("tracks", {}).get("fixedNonLinked") or {}) and
                           str(term_years) in b["tracks"]["fixedNonLinked"]["byTerm"] else 999)

        def replacement_builder(amount, avg_term_months):
            avg_term_years = max(5, min(30, round(avg_term_months / 12 / 5) * 5))
            rate = get_bank_rate(best_bank, "fixedNonLinked", "typ", term_years=avg_term_years)
            return [Track(id="new_replacement", kind="fixedNonLinked", balance=amount, rate=rate,
                          months_left=avg_term_months, original_months=avg_term_months, schedule="spitzer")]

        all_results, comparable = evaluate_refinance_subsets(
            existing_tracks, replacement_builder, CONFIG, rules_cfg_new, scenarios, discount_rate, notice_given,
        )
        headline = refinance_headline(comparable)
        if headline["has_data"] and headline["worthwhile"] is not None:
            if headline["worthwhile"]:
                st.success(f"## מחזור כדאי - חיסכון של כ-{headline['savings']:,.0f} ₪ בערך נוכחי")
            else:
                st.error(f"## מחזור לא כדאי כרגע - עלות נוספת של כ-{abs(headline['savings']):,.0f} ₪ בערך נוכחי לעומת השארת המצב הקיים")

        table_rows = []
        for r in comparable[:10]:
            label = "אי-עשייה" if r["is_do_nothing"] else ("מחזור מלא" if r["is_full_refinance"] else "מחזור חלקי: " + ", ".join(r["subset_ids"]))
            table_rows.append({"חלופה": label, "עלות כוללת (ערך נוכחי + עמלה)": r["total_cost_pv"]})
        if table_rows:
            st.dataframe(pd.DataFrame(table_rows).style.format({"עלות כוללת (ערך נוכחי + עמלה)": "{:,.0f} ₪"}),
                        use_container_width=True, hide_index=True)

        # חלופת המתנה לתחנה
        variable_tracks = [t for t in existing_tracks if t.is_variable() and t.months_to_next_reset]
        if variable_tracks:
            st.subheader("חלופת המתנה לתחנת יציאה")
            for t in variable_tracks:
                new_rate_now = get_bank_rate(best_bank, "fixedNonLinked", "typ", term_years=term_years)
                wait_result = wait_for_reset_alternative(t, CONFIG, new_rate_now, discount_rate, scenarios["base"])
                if wait_result["comparable"]:
                    winner_label = "🟢 עדיף להמתין לתחנה" if wait_result["winner"] == "wait" else "🟡 עדיף למחזר עכשיו"
                    st.write(f"**{t.id}** ({wait_result['months_to_reset']} חודשים לתחנה): {winner_label} "
                            f"(הפרש: {wait_result['savings']:,.0f} ₪ בערך נוכחי)")

# --------------------------------------------------------------------------
# הסתייגויות ופרטיות
# --------------------------------------------------------------------------
st.divider()
st.caption(
    "⚠️ הכלי מציג הערכה בלבד ואינו מהווה ייעוץ משכנתאות ואינו התחייבות לתנאים. "
    "התוצאות מבוססות על הנתונים שהוזנו ועל תצורת הריביות/כללים/עמלות שהוגדרה במערכת "
    "(ראו תאריכי עדכון למעלה) - יש לאמת מול הבנק לפני כל החלטה. "
    "הנתונים שהוזנו בעמוד זה מעובדים בזיכרון הדפדפן/השרת בלבד ואינם נשמרים על השרת. "
    "קליטת דוח יתרות מ-PDF, ייצוא דוח PDF ממותג, שמירה בקישור ואינטגרציות ליד "
    "טרם מומשו בגרסה הנוכחית."
)
render_footer()
