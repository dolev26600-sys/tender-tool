#!/usr/bin/env python3
"""
עמוד: היסטוריית מכרזים שנבדקו - רשימת כל הדו"חות שנשמרו, מהחדש לישן,
עם אפשרות לצפות ולהוריד כל אחד מהם בלי להריץ ניתוח מחדש.
"""
from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from ui_common import check_password, configure_page, render_footer, render_header

BASE_DIR = Path(__file__).resolve().parent.parent
REPORTS_DIR = BASE_DIR / "reports"

configure_page("מכרזים שנבדקו")

if not check_password():
    st.stop()

render_header("📚 מכרזים שנבדקו", "היסטוריית כל הדו\"חות שנשמרו - מהחדש לישן")

if not REPORTS_DIR.exists() or not any(REPORTS_DIR.glob("*.txt")):
    st.info("עדיין לא נשמרו דו\"חות. נתח מכרז ראשון בעמוד 'נתח מכרז חדש'.")
    render_footer()
    st.stop()

HEADER_RE = re.compile(r"מכרז\s+(?P<id>\S+)\s*:\s*(?P<title>.*?)\s*===")

reports = sorted(REPORTS_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)

for report_path in reports:
    text = report_path.read_text(encoding="utf-8")
    match = HEADER_RE.search(text)
    tender_id = match.group("id") if match else report_path.stem
    tender_title = match.group("title") if match else ""

    warning_flag = "⚠️" if "⚠️  דברים לבדוק" in text else "✅"
    mtime = report_path.stat().st_mtime
    from datetime import datetime

    date_str = datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")

    with st.container(border=True):
        col1, col2 = st.columns([5, 2])
        with col1:
            st.markdown(f"**{warning_flag} מכרז {tender_id}**")
            if tender_title:
                st.caption(tender_title)
            st.caption(f"נבדק בתאריך {date_str}")
        with col2:
            st.download_button(
                "⬇️ הורדה",
                data=text,
                file_name=report_path.name,
                mime="text/plain",
                use_container_width=True,
                key=f"dl_{report_path.name}",
            )

        with st.expander("הצג דו\"ח מלא"):
            st.text(text)

render_footer()
