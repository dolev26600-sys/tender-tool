#!/usr/bin/env python3
"""
עמוד: הפיכת הערות משיחת אפיון לרשומה מובנית + הודעה מוכנה ללקוח.

מטרה: לחסל את השעה שאחרי כל פגישה. זו עלות קבועה לכל לקוח, ולכן היא מה
שמגביל כמה לקוחות אפשר לטפל בהם.

הפלט זורם הלאה: הכפתור בסוף מעביר את מה שהלקוח אמר ישירות לבקרת האיכות,
כדי שהתמהיל ייבדק מול הנסיבות שלו בלי הקלדה מחדש.
"""
from __future__ import annotations

import json
import os

import streamlit as st

from meeting_intake import format_record_text, process_meeting, stated_plans_for_review
from ui_common import check_password, configure_page, render_footer, render_header

EXAMPLE_NOTES = """פגישה עם רונית ואבי מזרחי. רונית בת 36, מורה, שכירה 8 שנים באותו מקום,
מרוויחה 14 אלף נטו. אבי בן 38, עובד בהייטק, שכיר, בערך 22 אלף נטו, אבל אמר
שהוא שוקל לעבור לפרילנס בשנה הבאה.

מחפשים דירה יד שנייה בפתח תקווה, בסביבות 2.3 מיליון. יש להם 700 אלף הון עצמי,
מזה 200 אלף מהורים של רונית. צריכים בערך 1.6 מיליון.

יש להם הלוואת רכב, נשארו בערך 45 אלף, החזר 1,800 בחודש.

אמרו שההורים של אבי מבוגרים ויש סיכוי שתגיע ירושה בעוד 4-5 שנים, ואז ירצו
לפרוע חלק גדול מהמשכנתא. גם אמרו שהם מתכננים ילד שני בשנתיים הקרובות.

רונית אמרה שהיא לא רוצה החזר מעל 7,000 בחודש, ושהיא מפחדת מריבית משתנה.
צריכים אישור עקרוני תוך חודש כי יש להם אופציה על הדירה."""

configure_page("סיכום פגישה")

if not check_password():
    st.stop()

render_header(
    "🎙️ סיכום פגישה",
    "הערות מהשיחה → רשומה מסודרת + הודעה מוכנה ללקוח",
)

if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    st.error("שגיאת הגדרה: לא הוגדר מפתח API בשרת. פנה למי שהקים את הכלי.")
    st.stop()

st.caption(
    "השעה שאחרי כל פגישה היא עלות קבועה לכל לקוח - ולכן היא מה שמגביל כמה לקוחות אפשר לקחת. "
    "הדבק כאן הערות גולמיות (או תמלול), ותקבל את שלושת הדברים שאתה עושה ידנית אחרי כל שיחה."
)

if "meeting_notes" not in st.session_state:
    st.session_state["meeting_notes"] = ""

if st.button("טען פגישה לדוגמה (לראות איך זה עובד)"):
    st.session_state["meeting_notes"] = EXAMPLE_NOTES
    st.rerun()

notes = st.text_area(
    "הערות מהפגישה",
    height=280,
    key="meeting_notes",
    placeholder=(
        "הדבק כאן מה שרשמת תוך כדי השיחה - בכתיבה חופשית, לא צריך סדר. "
        "אפשר גם להדביק תמלול של הקלטה."
    ),
)

advisor_name = st.text_input("שמך (לחתימה בהודעה ללקוח)", value="")

process_clicked = st.button(
    "✍️ עבד את הפגישה",
    type="primary",
    use_container_width=True,
    disabled=not notes.strip(),
)

if not notes.strip():
    st.caption("הדבק הערות כדי להפעיל את הכפתור.")

if process_clicked:
    try:
        with st.spinner("מעבד את הפגישה..."):
            record = process_meeting(notes, advisor_name=advisor_name or None)
        st.session_state["meeting_record"] = record
    except Exception as e:  # noqa: BLE001 - מציגים כל שגיאה למשתמש בצורה ברורה
        st.error("קרתה שגיאה בעיבוד. אפשר לנסות שוב, ואם זה חוזר - לפנות למי שהקים את הכלי.")
        with st.expander("פרטים טכניים של השגיאה"):
            st.exception(e)

# ---------------------------------------------------------------- תוצאות

if "meeting_record" in st.session_state:
    st.divider()
    record = st.session_state["meeting_record"]

    tab_client, tab_record, tab_todo = st.tabs(
        ["💬 הודעה ללקוח", "📋 רשומה מסודרת", "✅ משימות ושאלות"]
    )

    with tab_client:
        st.caption("מוכן להעתקה ל-WhatsApp או למייל. עבור עליו לפני שליחה.")
        message = record.get("client_message", "")
        st.text_area("הודעה ללקוח", value=message, height=320, key="client_msg_out")
        st.download_button(
            "⬇️ הורד כקובץ טקסט",
            data=message,
            file_name="הודעה_ללקוח.txt",
            mime="text/plain",
        )

        docs = record.get("documents_needed") or []
        if docs:
            st.markdown("**המסמכים שנכללו בהודעה:**")
            for d in docs:
                st.markdown(f"- {d}")

    with tab_record:
        record_text = format_record_text(record)
        st.text_area("רשומה מסודרת", value=record_text, height=420, key="record_out")

        col_a, col_b = st.columns(2)
        with col_a:
            st.download_button(
                "⬇️ הורד כטקסט",
                data=record_text,
                file_name="רשומת_לקוח.txt",
                mime="text/plain",
                use_container_width=True,
            )
        with col_b:
            st.download_button(
                "⬇️ הורד כ-JSON",
                data=json.dumps(record, ensure_ascii=False, indent=2),
                file_name="רשומת_לקוח.json",
                mime="application/json",
                use_container_width=True,
            )

        plans = record.get("stated_plans") or []
        if plans:
            st.info(
                "**מה שהלקוח אמר על העתיד** — אלה הדברים שהכי נשכחים ואז סותרים את התמהיל:\n\n"
                + "\n".join(f"- {p}" for p in plans),
                icon="🔑",
            )

    with tab_todo:
        actions = record.get("advisor_action_items") or []
        questions = record.get("open_questions") or []

        if actions:
            st.markdown("**משימות שלך:**")
            for a in actions:
                st.checkbox(a, key=f"action_{hash(a)}")
        else:
            st.caption("לא זוהו משימות המשך.")

        if questions:
            st.markdown("**שאלות פתוחות — כדאי לברר לפני שממשיכים:**")
            for q in questions:
                st.markdown(f"- {q}")
        else:
            st.caption("לא נותרו שאלות פתוחות — הפגישה כיסתה את מה שצריך.")

    st.divider()
    st.markdown("**המשך לבקרת האיכות**")
    st.caption(
        "כשתבנה את התמהיל, הדבק את הטקסט הבא בשדה \"מה שהלקוח אמר בפגישה\" בעמוד בקרת האיכות — "
        "כך התמהיל ייבדק מול הנסיבות האמיתיות של הלקוח, בלי להקליד הכל מחדש."
    )
    st.text_area(
        "טקסט מוכן לבקרת האיכות",
        value=stated_plans_for_review(record),
        height=140,
        key="for_review_out",
    )

render_footer("סיכום פגישה")
