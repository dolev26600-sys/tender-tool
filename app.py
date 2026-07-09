#!/usr/bin/env python3
"""
ממשק web (Streamlit) לכלי בדיקת עמידה בתנאי סף - א.ג דיור.
עמוד ראשי: העלאת PDF של מכרז חדש וניתוח מלא.

מריצים מקומית עם:
    streamlit run app.py

זה פותח דף בדפדפן שבו אפשר להעלות PDF של מכרז וללחוץ כפתור - בלי טרמינל,
בלי פקודות. מתאים לשליחה לעובד שלא מכיר שורת פקודה.

עמודים נוספים (בסרגל הצד): פרופיל החברה (pages/1_...), מכרזים שנבדקו
(pages/2_...).

הערות אבטחה:
- מפתח ה-API (ANTHROPIC_API_KEY) חייב להיות מוגדר בסביבה שבה *השרת* רץ -
  העובד שמשתמש בדפדפן אף פעם לא רואה אותו.
- אם מוגדר משתנה סביבה TENDER_TOOL_PASSWORD, האפליקציה תדרוש סיסמה משותפת
  לפני שימוש - מומלץ להפעיל את זה אם האפליקציה נגישה מעבר לרשת המקומית.
- טקסט שמגיע מה-PDF/מ-Claude (דרישות, נימוקים) מוצג תמיד דרך st.markdown
  ללא unsafe_allow_html - כדי שלא יתאפשר הזרקת HTML/JS ממסמך זדוני.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import streamlit as st

from pdf_extraction import extract_text_from_pdf
from condition_extraction import extract_and_verify_conditions, save_conditions
from eligibility_engine import evaluate_eligibility
from report import format_report, save_report
from ui_common import (
    COMPANY_NAME,
    STATUS_META,
    check_password,
    configure_page,
    render_footer,
    render_header,
    status_badge_html,
)

BASE_DIR = Path(__file__).resolve().parent
TENDERS_DIR = BASE_DIR / "tenders"
REPORTS_DIR = BASE_DIR / "reports"
PROFILE_PATH = BASE_DIR / "company_profile.json"

configure_page("נתח מכרז חדש")

if "upload_key" not in st.session_state:
    st.session_state["upload_key"] = 0


def _run_analysis(uploaded_file, verification_passes: int):
    tmp_path = None
    progress_log: list[str] = []

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = Path(tmp.name)

        with st.status("מנתח את המכרז...", expanded=True) as status_box:
            status_box.write("📄 קורא את קובץ ה-PDF...")
            pdf_text = extract_text_from_pdf(tmp_path)
            status_box.write(f"נקרא בהצלחה ({len(pdf_text):,} תווים).")

            status_box.write("🔎 מזהה את תנאי הסף, ובודק את עצמו כמה פעמים כדי לא לפספס אף תנאי...")
            conditions = extract_and_verify_conditions(
                pdf_text,
                source_hint=uploaded_file.name,
                max_verification_passes=verification_passes,
                on_progress=progress_log.append,
            )
            saved_path = save_conditions(conditions, TENDERS_DIR)
            n_conditions = len(conditions.get("conditions", []))
            status_box.write(f"זוהו {n_conditions} תנאי סף.")

            status_box.write(f"📊 משווה מול פרופיל {COMPANY_NAME}...")
            with open(PROFILE_PATH, encoding="utf-8") as f:
                profile = json.load(f)
            evaluation = evaluate_eligibility(profile, conditions)

            report_text = format_report(conditions, evaluation)
            out_path = save_report(report_text, conditions.get("tender_id", "unknown"), REPORTS_DIR)

            status_box.update(label="✅ הניתוח הושלם", state="complete", expanded=False)

        if progress_log:
            with st.expander("פרטים טכניים של הבדיקה העצמית"):
                for msg in progress_log:
                    st.write(msg)

        return conditions, evaluation, report_text, out_path

    except Exception as e:  # noqa: BLE001 - מציגים כל שגיאה למשתמש בצורה ברורה, לא רק בלוג
        st.error("קרתה שגיאה במהלך הניתוח. אפשר לנסות שוב, ואם זה חוזר - לפנות למי שהקים את הכלי.")
        with st.expander("פרטים טכניים של השגיאה"):
            st.exception(e)
        return None
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)


def _verdict_banner(counts: dict) -> None:
    if counts.get("gap", 0) > 0:
        st.error(f"נמצאו {counts['gap']} תנאים עם פער — כדאי לטפל בהם לפני שניגשים למכרז.", icon="🔴")
    elif counts.get("unknown", 0) > 0:
        st.warning(f"יש {counts['unknown']} תנאים עם חוסר מידע בפרופיל החברה — כדאי להשלים אותם קודם.", icon="🟡")
    elif counts.get("likely_met", 0) > 0:
        st.warning(f"החברה כנראה עומדת בכל התנאים, אבל {counts['likely_met']} מהם דורשים אימות/פרטים מדויקים.", icon="🟡")
    else:
        st.success("החברה עומדת בכל תנאי הסף שזוהו במכרז!", icon="🎉")


def _group_by_category(results: list[dict]):
    groups: dict[str, list[dict]] = {}
    order: list[str] = []
    for r in results:
        cat = r.get("category") or "אחר"
        if cat not in groups:
            groups[cat] = []
            order.append(cat)
        groups[cat].append(r)
    return order, groups


def _render_condition_card(r: dict) -> None:
    with st.container(border=True):
        top_col1, top_col2 = st.columns([5, 2])
        with top_col1:
            st.markdown(f"**[{r.get('id')}]** {r.get('requirement', '')}")
        with top_col2:
            st.markdown(status_badge_html(r.get("status")), unsafe_allow_html=True)

        with st.expander("נימוק מפורט"):
            st.markdown(f"**נימוק:** {r.get('reasoning', '')}")
            missing = r.get("missing_info") or []
            if missing:
                st.markdown("**חסר להשלמה:** " + "; ".join(missing))


def _render_condition_list(results_subset: list[dict]) -> None:
    if not results_subset:
        st.caption("אין תנאים להצגה כאן.")
        return
    order, groups = _group_by_category(results_subset)
    for cat in order:
        st.markdown(f"##### {cat}")
        for r in groups[cat]:
            _render_condition_card(r)


def _render_results(conditions: dict, evaluation: dict, report_text: str, out_path: Path) -> None:
    st.divider()

    st.subheader(f"מכרז {conditions.get('tender_id', '?')}")
    st.caption(conditions.get("tender_title", ""))

    results = evaluation.get("results", [])
    counts = {key: 0 for key in STATUS_META}
    for r in results:
        counts[r.get("status")] = counts.get(r.get("status"), 0) + 1

    _verdict_banner(counts)

    summary = evaluation.get("overall_summary")
    if summary:
        st.write(summary)

    cols = st.columns(4)
    for col, key in zip(cols, ["met", "likely_met", "gap", "unknown"]):
        meta = STATUS_META[key]
        col.metric(f"{meta['icon']} {meta['label']}", counts.get(key, 0))

    st.write("")
    dl_col, reset_col = st.columns([3, 1])
    with dl_col:
        st.download_button(
            '⬇️ הורד את הדו"ח המלא (קובץ טקסט)',
            data=report_text,
            file_name=out_path.name,
            mime="text/plain",
            use_container_width=True,
        )
    with reset_col:
        if st.button("🔄 מכרז נוסף", use_container_width=True):
            st.session_state["upload_key"] += 1
            st.rerun()

    flagged = [r for r in results if r.get("status") in ("gap", "unknown")]
    ready = [r for r in results if r.get("status") in ("met", "likely_met")]

    st.write("")
    tab_attention, tab_ready, tab_all = st.tabs(
        [f"⚠️ דורש תשומת לב ({len(flagged)})", f"✅ מוכן ({len(ready)})", f"הכל ({len(results)})"]
    )
    with tab_attention:
        _render_condition_list(flagged)
    with tab_ready:
        _render_condition_list(ready)
    with tab_all:
        _render_condition_list(results)


def main() -> None:
    if not check_password():
        st.stop()

    render_header("✅ בדיקת עמידה בתנאי סף", f"{COMPANY_NAME} · העלה קובץ PDF של מכרז, וקבל ניתוח מלא של תנאי הסף")

    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        st.error("שגיאת הגדרה: לא הוגדר מפתח API בשרת. פנה למי שהקים את הכלי.")
        st.stop()

    if not PROFILE_PATH.exists():
        st.error(f"שגיאה: לא נמצא קובץ פרופיל החברה ({PROFILE_PATH.name}).")
        st.stop()

    st.caption("1️⃣ מעלים PDF של תנאי הסף  ·  2️⃣ ניתוח אוטומטי (כ-30-60 שניות, כולל בדיקה עצמית)  ·  3️⃣ דו\"ח מלא לכל תנאי")

    uploaded_file = st.file_uploader(
        "העלה קובץ PDF של תנאי הסף במכרז",
        type=["pdf"],
        help="קובץ ה-PDF שמכיל את תנאי הסף/ההשתתפות של המכרז",
        key=f"uploader_{st.session_state['upload_key']}",
    )

    with st.expander("⚙️ הגדרות מתקדמות"):
        verification_passes = st.slider(
            "כמות מעברי בדיקה-עצמית",
            min_value=1,
            max_value=5,
            value=3,
            help="כמה פעמים הכלי קורא שוב את המכרז כדי לוודא שלא הוחמץ תנאי סף. יותר = איטי יותר אך יסודי יותר. ברירת המחדל (3) מתאימה כמעט תמיד.",
        )

    analyze_clicked = st.button(
        "🔍 נתח את המכרז",
        type="primary",
        use_container_width=True,
        disabled=uploaded_file is None,
    )

    if uploaded_file is None:
        st.caption("העלה קובץ PDF כדי להפעיל את הכפתור.")
        return

    if not analyze_clicked:
        return

    result = _run_analysis(uploaded_file, verification_passes)
    if result is None:
        return

    conditions, evaluation, report_text, out_path = result
    _render_results(conditions, evaluation, report_text, out_path)
    render_footer()


if __name__ == "__main__":
    main()
