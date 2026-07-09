#!/usr/bin/env python3
"""
רכיבים ועיצוב משותפים לכל עמודי אפליקציית ה-Streamlit (app.py + pages/*.py).

הערת אבטחה: unsafe_allow_html משמש כאן *רק* ל-CSS קבוע ולתגיות סטטוס
שבנויות מאוצר מילים סגור בקוד (STATUS_META) - לעולם לא לטקסט שמגיע
מ-PDF/מ-Claude. טקסט כזה תמיד יוצג עם st.markdown/st.write רגיל (ללא
unsafe_allow_html), כדי שלא יתאפשר הזרקת HTML/JS ממסמך זדוני.
"""
from __future__ import annotations

import os

import streamlit as st

COMPANY_NAME = "א.ג דיור"

STATUS_META = {
    "met": {"icon": "✅", "label": "עומדים", "color": "#15803d", "bg": "#dcfce7"},
    "likely_met": {"icon": "🟡", "label": "כנראה עומדים - נדרש אימות", "color": "#a16207", "bg": "#fef9c3"},
    "gap": {"icon": "🔴", "label": "פער", "color": "#b91c1c", "bg": "#fee2e2"},
    "unknown": {"icon": "⚪", "label": "חסר מידע", "color": "#475569", "bg": "#f1f5f9"},
}
DEFAULT_STATUS_META = {"icon": "❔", "label": "לא ידוע", "color": "#475569", "bg": "#f1f5f9"}

PLACEHOLDER = "לא צוין - יש להשלים"


def status_badge_html(status: str) -> str:
    """תגית סטטוס צבעונית. הקלט הוא תמיד אחד מארבעת המפתחות הקבועים
    ב-STATUS_META (met/likely_met/gap/unknown) - לא טקסט חיצוני."""
    meta = STATUS_META.get(status, DEFAULT_STATUS_META)
    return (
        f'<span class="status-badge" style="color:{meta["color"]}; background:{meta["bg"]};">'
        f'{meta["icon"]} {meta["label"]}</span>'
    )


def configure_page(title: str) -> None:
    """קריאה ראשונה בכל עמוד - הגדרות הדף + CSS משותף.

    הערה: כיוון RTL מוחל בזהירות - *לא* על [class*="css"] הגורף (שמתנגש
    עם המנגנון הפנימי של Streamlit לפתיחה/סגירה של הסרגל הצדדי ושובר
    אותו), אלא רק על אזורי תוכן וטקסט ספציפיים.
    """
    st.set_page_config(
        page_title=f"{title} — {COMPANY_NAME}",
        page_icon="✅",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700&display=swap');

        html, body {
            font-family: 'Assistant', -apple-system, 'Segoe UI', sans-serif;
        }

        /* RTL רק על טקסט עלים ספציפיים - לא נוגעים בשום מיכל/מבנה
        (block-container, sidebar, header, toolbar) כדי לא לשבור את
        מנגנון הפתיחה/סגירה של הסרגל הצדדי. */
        p, li, label, h1, h2, h3, h4, h5, h6 {
            direction: rtl;
            text-align: right;
        }
        .stTextInput input, .stTextArea textarea, .stNumberInput input {
            direction: rtl; text-align: right;
        }

        .app-header { text-align: center; padding: 1.25rem 0 1rem 0; border-bottom: 1px solid #e5e7eb; margin-bottom: 1.5rem; }
        .app-header h1 { font-size: 1.5rem; margin-bottom: 0.25rem; color: #0f172a; }
        .app-header p { color: #64748b; font-size: 0.92rem; }

        .status-badge { display: inline-block; padding: 0.2rem 0.7rem; border-radius: 999px; font-weight: 600; font-size: 0.85rem; white-space: nowrap; }

        .field-todo { color: #b45309; font-size: 0.8rem; font-weight: 600; }

        .footer-note { text-align: center; color: #94a3b8; font-size: 0.8rem; margin-top: 2.5rem; padding-top: 1rem; border-top: 1px solid #e5e7eb; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="app-header"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def render_footer() -> None:
    st.markdown(
        f'<div class="footer-note">{COMPANY_NAME} · כלי בדיקת עמידה בתנאי סף · מופעל בעזרת Claude AI</div>',
        unsafe_allow_html=True,
    )


def check_password() -> bool:
    """הגנת סיסמה משותפת פשוטה, מופעלת רק אם הוגדר TENDER_TOOL_PASSWORD.
    נקראת בתחילת *כל* עמוד (לא רק app.py) - כדי שלא יהיה אפשר לעקוף אותה
    דרך ניווט ישיר לעמוד אחר."""
    required = os.environ.get("TENDER_TOOL_PASSWORD")
    if not required:
        return True  # לא הוגדרה סיסמה - אין הגנה (מתאים רק לשימוש מקומי/רשת פנימית סגורה)

    if st.session_state.get("authed"):
        return True

    render_header(f"🔒 בדיקת תנאי סף — {COMPANY_NAME}", "הכניסה לכלי מוגנת בסיסמה")
    with st.form("login_form"):
        pw = st.text_input("סיסמה", type="password")
        submitted = st.form_submit_button("כניסה", type="primary", use_container_width=True)
    if submitted:
        if pw == required:
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("סיסמה שגויה")
    return False


def is_filled(value) -> bool:
    """True אם לשדה יש ערך אמיתי (לא ריק ולא placeholder של 'יש להשלים')."""
    text = str(value or "").strip()
    return bool(text) and PLACEHOLDER not in text


def clean_for_input(value) -> str:
    """מציג ערך לשדה טופס - ריק אם השדה עדיין placeholder, כדי לא להציג
    למשתמש טקסט 'לא צוין - יש להשלים' בתוך תיבת עריכה."""
    text = str(value or "")
    return "" if PLACEHOLDER in text else text


def restore_placeholder(value: str) -> str:
    """בשמירה - אם המשתמש השאיר שדה ריק, נחזיר placeholder ברור, כדי
    שמנוע ההשוואה ידע לפרש את זה כ'חסר מידע' (⚪) ולא יתבלבל מול מחרוזת ריקה."""
    stripped = (value or "").strip()
    return stripped if stripped else PLACEHOLDER
