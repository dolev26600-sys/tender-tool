#!/usr/bin/env python3
"""
עמוד: שיחת אפיון שהלקוח מנהל בעצמו.

שולחים ללקוח את הקישור לעמוד הזה, הוא מנהל שיחה קצרה עם עוזר שמכיר בדיוק
מה היועץ שואל, ובסוף היועץ מקבל תיק מסודר - בלי שהתקיימה פגישה.

שני מצבים באותו עמוד:
- **מצב לקוח** (ברירת מחדל): רק הצ'אט. אין תפריט, אין כפתורים של היועץ.
- **מצב יועץ**: אחרי שהשיחה הסתיימה, מייצר את הרשומה המובנית מהתמלול,
  דרך אותו מנוע שמעבד פגישה רגילה (meeting_intake).

הערת אבטחה: העמוד הזה נועד להיות נגיש ללקוח. אם הוגדרה סיסמה
(TENDER_TOOL_PASSWORD), היא תחסום גם את הלקוח - ולכן במצב הזה יש לשקול
להריץ את העמוד הזה בנפרד, או לשתף את הסיסמה עם הלקוח. הצ'אט עצמו לא
מבקש מהלקוח ת"ז, פרטי חשבון או מסמכים.
"""
from __future__ import annotations

import os

import streamlit as st

from client_intake import is_finished, next_reply, transcript_from_history
from meeting_intake import format_record_text, process_meeting, stated_plans_for_review
from ui_common import COMPANY_NAME, configure_page, render_footer, render_header

configure_page("אפיון עצמי")

if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
    st.error("שגיאת הגדרה: לא הוגדר מפתח API בשרת. פנה למי שהקים את הכלי.")
    st.stop()

for key, default in [("intake_history", []), ("intake_done", False), ("intake_record", None)]:
    if key not in st.session_state:
        st.session_state[key] = default

# --------------------------------------------------------------- מצב יועץ

advisor_mode = st.sidebar.toggle(
    "מצב יועץ",
    value=False,
    help="הלקוח לא אמור לראות את זה. הפעל כדי להפיק את הרשומה מהשיחה שהסתיימה.",
)

render_header(
    "💬 שיחה קצרה לפני שנתחיל",
    f"{COMPANY_NAME} · כמה שאלות כדי שהיועץ יגיע מוכן",
)

if not st.session_state["intake_history"]:
    st.caption(
        "השיחה לוקחת בערך חמש דקות. אין תשובות נכונות או לא נכונות, ואפשר לומר "
        "\"לא יודע\" בכל שלב. לא נבקש כאן תעודת זהות, פרטי חשבון או מסמכים."
    )

# --------------------------------------------------------------- הצ'אט

for msg in st.session_state["intake_history"]:
    with st.chat_message("assistant" if msg["role"] == "assistant" else "user"):
        st.markdown(msg["content"])

# פתיחת השיחה - העוזר מדבר ראשון
if not st.session_state["intake_history"]:
    try:
        with st.spinner(""):
            opening = next_reply([], company_name=COMPANY_NAME)
        st.session_state["intake_history"].append({"role": "assistant", "content": opening})
        st.rerun()
    except Exception as e:  # noqa: BLE001 - הלקוח מקבל הודעה אנושית, לא stack trace
        st.error("לא הצלחנו להתחיל את השיחה כרגע. אפשר לרענן את העמוד או לפנות ליועץ ישירות.")
        if advisor_mode:  # פרטים טכניים ליועץ בלבד - הלקוח לא אמור לראות אותם
            with st.expander("פרטים טכניים"):
                st.exception(e)
        st.stop()

if not st.session_state["intake_done"]:
    user_input = st.chat_input("הקלד כאן...")
    if user_input:
        st.session_state["intake_history"].append({"role": "user", "content": user_input})
        try:
            with st.spinner(""):
                reply = next_reply(st.session_state["intake_history"], company_name=COMPANY_NAME)
            st.session_state["intake_history"].append({"role": "assistant", "content": reply})
            if is_finished(reply):
                st.session_state["intake_done"] = True
        except Exception as e:  # noqa: BLE001
            st.error("קרתה תקלה. אפשר לנסות לשלוח שוב.")
            if advisor_mode:
                with st.expander("פרטים טכניים"):
                    st.exception(e)
        st.rerun()
else:
    st.success("השיחה הסתיימה. תודה! היועץ יחזור אליך.", icon="✅")

# ------------------------------------------------------- הכלים של היועץ

if advisor_mode:
    st.divider()
    st.subheader("🔒 מצב יועץ")

    n_turns = len([m for m in st.session_state["intake_history"] if m["role"] == "user"])
    st.caption(f"{n_turns} תשובות מהלקוח · השיחה {'הסתיימה' if st.session_state['intake_done'] else 'עדיין פתוחה'}")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📋 הפק רשומה מהשיחה", type="primary", use_container_width=True, disabled=n_turns == 0):
            try:
                with st.spinner("מעבד את השיחה..."):
                    transcript = transcript_from_history(st.session_state["intake_history"])
                    st.session_state["intake_record"] = process_meeting(transcript)
            except Exception as e:  # noqa: BLE001
                st.error("קרתה שגיאה בעיבוד השיחה.")
                with st.expander("פרטים טכניים"):
                    st.exception(e)
    with col_b:
        if st.button("🔄 התחל שיחה חדשה", use_container_width=True):
            st.session_state["intake_history"] = []
            st.session_state["intake_done"] = False
            st.session_state["intake_record"] = None
            st.rerun()

    with st.expander("תמלול מלא"):
        st.text(transcript_from_history(st.session_state["intake_history"]))

    record = st.session_state["intake_record"]
    if record:
        st.divider()
        tab_record, tab_todo, tab_review = st.tabs(
            ["📋 רשומה מסודרת", "✅ משימות ושאלות", "🛡️ לבקרת האיכות"]
        )

        with tab_record:
            record_text = format_record_text(record)
            st.text_area("רשומה", value=record_text, height=420, key="intake_record_out")
            st.download_button(
                "⬇️ הורד כטקסט",
                data=record_text,
                file_name="רשומת_לקוח.txt",
                mime="text/plain",
            )
            plans = record.get("stated_plans") or []
            if plans:
                st.info(
                    "**מה שהלקוח אמר על העתיד:**\n\n" + "\n".join(f"- {p}" for p in plans),
                    icon="🔑",
                )

        with tab_todo:
            for title, key, empty in [
                ("**משימות שלך:**", "advisor_action_items", "לא זוהו משימות המשך."),
                ("**שאלות פתוחות:**", "open_questions", "לא נותרו שאלות פתוחות."),
                ("**מסמכים לאיסוף:**", "documents_needed", "לא זוהו מסמכים."),
            ]:
                items = record.get(key) or []
                if items:
                    st.markdown(title)
                    for item in items:
                        st.markdown(f"- {item}")
                else:
                    st.caption(empty)

        with tab_review:
            st.caption(
                "הדבק את זה בשדה \"מה שהלקוח אמר בפגישה\" בעמוד בקרת האיכות, "
                "כדי שהתמהיל ייבדק מול הנסיבות של הלקוח."
            )
            st.text_area(
                "טקסט לבקרת האיכות",
                value=stated_plans_for_review(record),
                height=160,
                key="intake_for_review",
            )

    render_footer("אפיון עצמי ללקוח")
