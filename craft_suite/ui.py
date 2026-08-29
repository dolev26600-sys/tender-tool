#!/usr/bin/env python3
"""עיצוב ורכיבי ממשק משותפים לעמוד ה-Streamlit של craft_suite."""
from __future__ import annotations

import streamlit as st

APP_NAME = "יומן עסק"


def configure_page() -> None:
    st.set_page_config(page_title=APP_NAME, page_icon="🧰", layout="centered")
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Assistant:wght@400;600;700&display=swap');

        html, body { font-family: 'Assistant', -apple-system, 'Segoe UI', sans-serif; }

        p, li, label, h1, h2, h3, h4, h5, h6, .stMarkdown { direction: rtl; text-align: right; }
        .stTextInput input, .stTextArea textarea, .stNumberInput input, .stSelectbox div { direction: rtl; text-align: right; }

        .app-header { text-align: center; padding: 1rem 0; border-bottom: 1px solid #e5e7eb; margin-bottom: 1.25rem; }
        .app-header h1 { font-size: 1.4rem; margin-bottom: 0.2rem; color: #0f172a; }
        .app-header p { color: #64748b; font-size: 0.9rem; }

        .status-pill { display: inline-block; padding: 0.15rem 0.65rem; border-radius: 999px; font-weight: 600; font-size: 0.8rem; background: #eef2ff; color: #4338ca; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(subtitle: str) -> None:
    st.markdown(f'<div class="app-header"><h1>🧰 {APP_NAME}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)
