#!/usr/bin/env python3
"""
עמוד: אופטימיזציית תמהיל.

מזינים את הריביות של היום (הן משתנות, ולכן הן קלט בכל הרצה) ואת האילוצים,
והמנוע סורק אלפי חלוקות ומחזיר את האופטימום לכל מטרה.

**עמוד דטרמיניסטי לחלוטין - אין קריאה למודל שפה ולא צריך מפתח API.**
כל מספר כאן הוא תוצאה של חשבון, לא של שיפוט.
"""
from __future__ import annotations

import streamlit as st

from mortgage_optimizer import TRACK_LABELS, describe, optimize_across_terms
from ui_common import check_password, configure_page, render_footer, render_header

# ברירות מחדל למסלולים. צמודי מדד מכובים כברירת מחדל בהתאם למדיניות
# המשרד - לא עובדים איתם, אלא אם ללקוח אין ברירה.
TRACK_DEFAULTS = [
    ("fixed_unlinked", 4.60, True),
    ("variable_prime", 5.40, True),
    ("variable_unlinked", 4.90, True),
    ("fixed_linked_cpi", 3.40, False),
    ("variable_linked_cpi", 3.60, False),
]

OBJECTIVE_LABELS = {
    "cheapest_total": ("💰 העלות הכוללת הנמוכה ביותר", "הכי פחות כסף לאורך כל התקופה"),
    "lowest_monthly": ("📉 ההחזר החודשי הנמוך ביותר", "הכי נוח בחודש הראשון - לא בהכרח הזול"),
    "most_stable": ("🛡️ החשוף פחות מכולם", "ההחזר זז הכי מעט אם השוק משתנה"),
    "cheapest_exit": ("🚪 הזול ביותר ליציאה מוקדמת", "אם הלקוח צפוי לפרוע או למחזר"),
}

configure_page("אופטימיזציית תמהיל")

if not check_password():
    st.stop()

render_header(
    "🎯 אופטימיזציית תמהיל",
    "מזינים ריביות ואילוצים, המנוע סורק אלפי חלוקות ומוצא את האופטימום",
)

st.caption(
    "המנוע לא מציע תמהיל - הוא **מחשב** אותו. סריקה ממצה על מרחב החלוקות, "
    "עם אופטימום נפרד לכל מטרה, כי אין תמהיל אחד שהוא הכי טוב בכל הממדים."
)

# ---------------------------------------------------------------- ריביות

st.subheader("1. הריביות של היום")
st.caption("סמן אילו מסלולים זמינים, והזן את הריבית לכל אחד.")

rates: dict[str, float] = {}
for track_type, default_rate, default_on in TRACK_DEFAULTS:
    col_check, col_rate = st.columns([2, 1])
    with col_check:
        enabled = st.checkbox(TRACK_LABELS[track_type], value=default_on, key=f"en_{track_type}")
    with col_rate:
        rate = st.number_input(
            "ריבית",
            min_value=0.0, max_value=15.0, value=default_rate, step=0.05,
            key=f"rate_{track_type}", label_visibility="collapsed",
            disabled=not enabled,
        )
    if enabled:
        rates[track_type] = rate

# ---------------------------------------------------------------- אילוצים

st.subheader("2. העסקה והאילוצים")

col1, col2 = st.columns(2)
with col1:
    loan_amount = st.number_input("סכום ההלוואה (₪)", min_value=50_000, max_value=20_000_000,
                                  value=1_200_000, step=50_000)
    term_range = st.slider(
        "טווח תקופות לבדיקה (שנים)",
        min_value=5, max_value=30, value=(15, 30),
        help=(
            "התקופה היא חלק מהאופטימיזציה, לא קלט קבוע. המנוע יבדוק כל תקופה "
            "בטווח ויראה לך את התמורה - קיצור תקופה הוא בדרך כלל החיסכון הגדול "
            "ביותר במשכנתא, גדול בהרבה מהפרש קטן בריבית."
        ),
    )
with col2:
    max_monthly = st.number_input(
        "תקרת החזר חודשי (₪) — 0 = ללא תקרה",
        min_value=0, max_value=200_000, value=0, step=250,
        help="נבדק מול ההחזר בפועל בחודש הראשון, לא מול העלות האפקטיבית.",
    )
    min_fixed_pct = st.slider(
        "שיעור מזערי בריבית קבועה (%)", min_value=0, max_value=100, value=33,
        help="ערך ברירת מחדל לאימות מול הוראות בנק ישראל העדכניות.",
    )

with st.expander("⚙️ הנחות ותרחישים"):
    col_a, col_b = st.columns(2)
    with col_a:
        expected_cpi = st.number_input(
            "אינפלציה שנתית צפויה (%)", min_value=0.0, max_value=10.0, value=2.0, step=0.25,
            help=(
                "משמש להשוואה הוגנת: ריבית נקובה של מסלול צמוד אינה בת-השוואה "
                "לריבית של מסלול לא צמוד, כי הקרן הצמודה גדלה עם המדד."
            ),
        )
        stress_rate = st.number_input("עליית ריבית בתרחיש הקיצון (%)", 0.0, 6.0, 2.0, step=0.5)
    with col_b:
        stress_cpi = st.number_input("אינפלציה בתרחיש הקיצון (%)", 0.0, 12.0, 4.0, step=0.5)
        step_pct = st.select_slider(
            "רזולוציית החיפוש",
            options=[10.0, 5.0, 2.5],
            value=5.0,
            format_func=lambda v: f"{v:g}% — {'מהיר' if v >= 10 else ('מאוזן' if v >= 5 else 'עדין ואיטי')}",
        )

    exit_year = st.slider(
        "בדוק גם עלות יציאה מוקדמת בשנה", min_value=0, max_value=20, value=5,
        help="0 = לא לבדוק. רלוונטי כשהלקוח צופה לפרוע מוקדם, למכור או למחזר.",
    )

market_rates: dict[str, float] = {}
if exit_year > 0 and rates:
    with st.expander("📉 ריביות ממוצעות במשק — לחישוב עמלת היוון", expanded=False):
        st.caption(
            "**עמלת היוון נגבית רק כשריבית הלקוח גבוהה מהריבית הממוצעת במשק** לאותו מסלול. "
            "אם תשאיר את הערכים זהים לריביות שהזנת למעלה, העמלה תצא אפס בכל התמהילים — "
            "וזה נכון מתמטית אבל חסר תועלת. בנק ישראל מפרסם את הריבית הממוצעת "
            "לפירעון מוקדם מדי חודש; הזן אותה כאן."
        )
        for track_type in rates:
            market_rates[track_type] = st.number_input(
                f"ממוצע במשק — {TRACK_LABELS[track_type]} (%)",
                min_value=0.0, max_value=15.0, value=rates[track_type], step=0.05,
                key=f"mkt_{track_type}",
            )

linked_policy = st.radio(
    "מדיניות מסלולים צמודי מדד",
    options=["only_if_needed", "exclude", "allow"],
    format_func=lambda k: {
        "only_if_needed": "רק אם אין ברירה (ברירת המחדל)",
        "exclude": "לעולם לא — להיכשל במקום ליפול לצמוד",
        "allow": "לשקול ככל מסלול אחר",
    }[k],
    horizontal=True,
    help="ברירת המחדל מחפשת קודם בלי צמוד, ומסמנת אם הלקוח לא עומד באילוצים בלעדיו.",
)

run = st.button("🎯 מצא את התמהיל האופטימלי", type="primary", use_container_width=True,
                disabled=not rates)

if not rates:
    st.warning("סמן לפחות מסלול אחד כדי להריץ.")

if run:
    try:
        with st.spinner("סורק חלוקות על פני כל התקופות..."):
            result = optimize_across_terms(
                rates,
                float(loan_amount),
                term_years_options=range(term_range[0], term_range[1] + 1),
                min_fixed_share=min_fixed_pct / 100,
                max_monthly_payment=float(max_monthly) if max_monthly > 0 else None,
                step_pct=step_pct,
                stress_rate_pct=stress_rate,
                stress_cpi_pct=stress_cpi,
                expected_cpi_pct=expected_cpi,
                early_exit_year=exit_year if exit_year > 0 else None,
                market_rates=market_rates or None,
                linked_policy=linked_policy,
            )
        st.session_state["opt_result"] = result
        st.session_state["opt_rates"] = rates
        st.session_state["opt_exit_year"] = exit_year
    except ValueError as e:
        st.error(str(e))
        st.session_state.pop("opt_result", None)

# ---------------------------------------------------------------- תוצאות

if "opt_result" in st.session_state:
    result = st.session_state["opt_result"]
    used_rates = st.session_state["opt_rates"]
    shown_exit_year = st.session_state.get("opt_exit_year", 0)
    feasible = [r for r in result["per_term"] if r.feasible]

    st.divider()

    # --- הכותרת: התקופה הקצרה ביותר שהלקוח עומד בה ---
    shortest_years = result["shortest_feasible_term_years"]
    longest = max(feasible, key=lambda r: r.term_months)
    shortest = min(feasible, key=lambda r: r.term_months)
    saving = longest.best["cheapest_total"].total_cost - shortest.best["cheapest_total"].total_cost
    extra_monthly = (
        shortest.best["cheapest_total"].base_monthly_nominal
        - longest.best["cheapest_total"].base_monthly_nominal
    )

    st.subheader("התקופה")
    if len(feasible) > 1 and saving > 0:
        st.success(
            f"**התקופה הקצרה ביותר שעומדת באילוצים: {shortest_years:g} שנים.** "
            f"לעומת {longest.term_years:g} שנים היא מייקרת את ההחזר ב-{extra_monthly:,.0f} ₪ בחודש — "
            f"וחוסכת **{saving:,.0f} ₪** לאורך התקופה.",
            icon="⏱️",
        )
    else:
        st.info(f"התקופה הקצרה ביותר שעומדת באילוצים: {shortest_years:g} שנים.", icon="⏱️")

    if result["n_terms_feasible"] < result["n_terms_checked"]:
        skipped = result["n_terms_checked"] - result["n_terms_feasible"]
        st.caption(f"{skipped} תקופות קצרות יותר נבדקו ואינן עומדות בתקרת ההחזר.")

    st.dataframe(
        [
            {
                "תקופה": f"{r.term_years:g} שנים",
                "החזר חודשי": round(r.best["cheapest_total"].base_monthly_nominal),
                "עלות כוללת": round(r.best["cheapest_total"].total_cost),
                "מול הארוכה ביותר": round(
                    r.best["cheapest_total"].total_cost
                    - longest.best["cheapest_total"].total_cost
                ),
                "הרכב": describe(r.best["cheapest_total"], used_rates),
            }
            for r in feasible
        ],
        use_container_width=True,
        hide_index=True,
    )

    # --- האופטימום לכל מטרה, על פני כל התקופות ---
    st.subheader("האופטימום לכל מטרה")
    st.caption("כל שורה היא התמהיל **והתקופה** הטובים ביותר עבור אותה מטרה.")

    if any(r.linked_required for r in feasible):
        st.warning(
            "בחלק מהתקופות לא נמצאה חלוקה שעומדת באילוצים בלי מסלול צמוד מדד — "
            "כלומר שם הלקוח אינו עומד בתקרה עם מסלולים לא צמודים בלבד.",
            icon="⚠️",
        )

    for key, entry in result["best_overall"].items():
        label, sub = OBJECTIVE_LABELS.get(key, (key, ""))
        cand = entry["candidate"]
        years = entry["term_months"] / 12
        with st.container(border=True):
            st.markdown(f"**{label}** — {years:g} שנים")
            st.caption(sub)
            st.markdown(describe(cand, used_rates))

            cols = st.columns(4)
            cols[0].metric("החזר בפועל", f"{cand.base_monthly_nominal:,.0f} ₪",
                           help="מה שיורד מהחשבון בחודש הראשון")
            cols[1].metric("בתרחיש קיצון", f"{cand.worst_monthly:,.0f} ₪",
                           delta=f"{cand.exposure:,.0f} ₪", delta_color="inverse")
            cols[2].metric("עלות כוללת", f"{cand.total_cost:,.0f} ₪",
                           help="אפקטיבית — כוללת אינפלציה צפויה על מסלולים צמודים")
            if cand.exit_fee is not None:
                cols[3].metric(f"יציאה בשנה {shown_exit_year}", f"{cand.exit_fee:,.0f} ₪")

            st.caption(
                f"קבוע {cand.fixed_share:.0%} · משתנה {cand.variable_share:.0%} · צמוד {cand.cpi_share:.0%}"
            )

    # --- חזית היעילות, לתקופה שנבחרה ---
    st.subheader("חזית היעילות")
    term_choice = st.selectbox(
        "לאיזו תקופה להציג",
        options=[r.term_months for r in feasible],
        format_func=lambda m: f"{m/12:g} שנים",
        index=0,
    )
    chosen = next(r for r in feasible if r.term_months == term_choice)

    if len(chosen.frontier) == 1:
        st.info(
            "נקודה אחת בלבד — מסלול אחד גם הזול וגם היציב, ואין כאן דילמה לפתור.",
            icon="💡",
        )
    else:
        st.caption("מלמעלה למטה: זול וחשוף → יקר ויציב. כל שורה היא תמהיל שאי אפשר לשפר בממד אחד בלי להחמיר באחר.")

    st.dataframe(
        [
            {
                "עלות כוללת": round(f.total_cost),
                "החזר בפועל": round(f.base_monthly_nominal),
                "חשיפה": round(f.exposure),
                "קבוע": f"{f.fixed_share:.0%}",
                "משתנה": f"{f.variable_share:.0%}",
                "צמוד": f"{f.cpi_share:.0%}",
                "הרכב": describe(f, used_rates),
            }
            for f in chosen.frontier
        ],
        use_container_width=True,
        hide_index=True,
    )

    st.caption(
        "העלות הכוללת היא הערכה שמניחה שתנאי התרחיש נשארים קבועים לכל התקופה. "
        "ערכי הסף הרגולטוריים הם ברירות מחדל לאימות מול הוראות בנק ישראל העדכניות."
    )

render_footer("אופטימיזציית תמהיל")
