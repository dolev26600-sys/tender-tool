#!/usr/bin/env python3
"""
ממשק web (Streamlit) לכלי בדיקת עמידה בתנאי סף - א.ג דיור.

מריצים מקומית עם:
    streamlit run app.py

זה פותח דף בדפדפן שבו אפשר להעלות PDF של מכרז וללחוץ כפתור - בלי טרמינל,
בלי פקודות. מתאים לשליחה לעובדים שלא מכירים שורת פקודה.

הערות אבטחה:
- מפתח ה-API (ANTHROPIC_API_KEY) חייב להיות מוגדר בסביבה שבה *השרת* רץ -
  העובד שמשתמש בדפדפן אף פעם לא רואה אותו.
- אם מוגדר משתנה סביבה TENDER_TOOL_PASSWORD, האפליקציה תדרוש סיסמה משותפת
  לפני שימוש - מומלץ להפעיל את זה אם האפליקציה נגישה מעבר לרשת המקומית,
  כי המידע (פרופיל החברה, תנאי מכרזים) רגיש.
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

BASE_DIR = Path(__file__).resolve().parent
TENDERS_DIR = BASE_DIR / "tenders"
REPORTS_DIR = BASE_DIR / "reports"
PROFILE_PATH = BASE_DIR / "company_profile.json"

STATUS_ICON = {"met": "✅", "likely_met": "🟡", "gap": "🔴", "unknown": "⚪"}

st.set_page_config(page_title="בדיקת תנאי סף — א.ג דיור", page_icon="✅", layout="wide")

# יישור לימין (RTL) - Streamlit לא תומך בזה כברירת מחדל
st.markdown(
    """
    <style>
    html, body, [class*="css"] { direction: rtl; text-align: right; }
    .stTextInput input, .stTextArea textarea { direction: rtl; text-align: right; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _check_password() -> bool:
    """הגנת סיסמה משותפת פשוטה, מופעלת רק אם הוגדר TENDER_TOOL_PASSWORD."""
    required = os.environ.get("TENDER_TOOL_PASSWORD")
    if not required:
        return True  # לא הוגדרה סיסמה - אין הגנה (מתאים רק לשימוש מקומי/רשת פנימית סגורה)

    if st.session_state.get("authed"):
        return True

    st.title("🔒 בדיקת תנאי סף — א.ג דיור")
    pw = st.text_input("סיסמה", type="password")
    if st.button("כניסה"):
        if pw == required:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("סיסמה שגויה")
    return False


def main() -> None:
    if not _check_password():
        st.stop()

    st.title("✅ בדיקת עמידה בתנאי סף — א.ג דיור")
    st.caption("העלה קובץ PDF של תנאי הסף של מכרז, ולחץ על 'נתח את המכרז'.")

    if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        st.error("שגיאת הגדרה: לא הוגדר מפתח API בשרת. פנה למי שהקים את הכלי.")
        st.stop()

    if not PROFILE_PATH.exists():
        st.error(f"שגיאה: לא נמצא קובץ פרופיל החברה ({PROFILE_PATH.name}).")
        st.stop()

    with st.sidebar:
        st.header("הגדרות")
        verification_passes = st.slider(
            "כמות מעברי בדיקה-עצמית",
            min_value=1,
            max_value=5,
            value=3,
            help="כמה פעמים הכלי קורא שוב את המכרז כדי לוודא שלא הוחמץ תנאי סף. יותר = איטי יותר אך יסודי יותר.",
        )

    uploaded_file = st.file_uploader("קובץ PDF של תנאי הסף במכרז", type=["pdf"])

    if not uploaded_file:
        st.info("העלה קובץ PDF כדי להתחיל.")
        return

    if not st.button("🔍 נתח את המכרז", type="primary"):
        return

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(uploaded_file.getvalue())
            tmp_path = Path(tmp.name)

        with st.status("מתחיל ניתוח...", expanded=True) as status_box:
            status_box.write("שלב 1/3: מחלץ טקסט מה-PDF...")
            pdf_text = extract_text_from_pdf(tmp_path)
            status_box.write(f"חולצו {len(pdf_text):,} תווים.")

            status_box.write("שלב 2/3: מחלץ תנאי סף ובודק את עצמו מספר פעמים...")
            conditions = extract_and_verify_conditions(
                pdf_text,
                source_hint=uploaded_file.name,
                max_verification_passes=verification_passes,
                on_progress=lambda msg: status_box.write(msg),
            )
            saved_path = save_conditions(conditions, TENDERS_DIR)
            n_conditions = len(conditions.get("conditions", []))
            status_box.write(f"נשמר: {saved_path.name} ({n_conditions} תנאי סף שזוהו)")

            status_box.write("שלב 3/3: משווה מול פרופיל החברה...")
            with open(PROFILE_PATH, encoding="utf-8") as f:
                profile = json.load(f)
            evaluation = evaluate_eligibility(profile, conditions)

            report_text = format_report(conditions, evaluation)
            out_path = save_report(report_text, conditions.get("tender_id", "unknown"), REPORTS_DIR)

            status_box.update(label="הניתוח הושלם!", state="complete")

    except Exception as e:  # noqa: BLE001 - מציגים כל שגיאה למשתמש בצורה ברורה
        st.error("קרתה שגיאה במהלך הניתוח:")
        st.exception(e)
        return
    finally:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)

    # --- תצוגת תוצאות ---
    st.divider()
    st.header(f"מכרז {conditions.get('tender_id', '?')}: {conditions.get('tender_title', '')}")

    summary = evaluation.get("overall_summary")
    if summary:
        st.write(summary)

    results = evaluation.get("results", [])
    flagged = [r for r in results if r.get("status") in ("gap", "unknown")]

    col1, col2 = st.columns([1, 1])
    with col1:
        if flagged:
            st.warning(f"⚠️ {len(flagged)} תנאים עם פער או חוסר מידע - כדאי להשלים לפני שניגשים למכרז.")
        else:
            st.success("✅ לא נמצאו פערים או חוסרי מידע.")
    with col2:
        st.download_button(
            'הורד דו"ח כקובץ טקסט',
            data=report_text,
            file_name=out_path.name,
            mime="text/plain",
        )

    if flagged:
        st.subheader("⚠️ דברים לבדוק/להשלים")
        for r in flagged:
            st.markdown(f"- **[{r.get('id')}]** {STATUS_ICON.get(r.get('status'), '')} {r.get('requirement', '')}")

    st.subheader("פירוט מלא לכל תנאי")
    for r in results:
        status = r.get("status")
        icon = STATUS_ICON.get(status, "❔")
        title = f"{icon} [{r.get('id')}] {r.get('category', '')} — {(r.get('requirement') or '')[:90]}"
        with st.expander(title):
            st.markdown(f"**דרישה:** {r.get('requirement', '')}")
            st.markdown(f"**סטטוס:** {r.get('status_label', status)}")
            st.markdown(f"**נימוק:** {r.get('reasoning', '')}")
            missing = r.get("missing_info") or []
            if missing:
                st.markdown("**חסר להשלמה:** " + "; ".join(missing))


if __name__ == "__main__":
    main()
