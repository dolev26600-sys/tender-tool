#!/usr/bin/env python3
"""
יומן עסק - MVP לכלי הצעות מחיר, תיאום עבודות וגבייה לבעלי מקצוע
(חשמלאים, אינסטלטורים, שיפוצניקים וכו').

הבידול מול כלים קיימים (כמו פיקס): לא רק הצעת מחיר - גם מה שקורה
אחריה. שלושה טאבים: הצעת מחיר חדשה -> יומן עבודות -> לקוחות וגבייה,
אותו זרימת עבודה מלאה ש-Jobber/Housecall Pro מוכרים כחבילה אחת, בעברית.

הרצה מקומית:
    export ANTHROPIC_API_KEY="sk-ant-..."
    streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

import storage
from quote_agent import draft_quote
from ui import configure_page, render_header

configure_page()
render_header("הצעת מחיר, יומן עבודות וגבייה - במקום ניר ווטסאפ")

tab_quote, tab_calendar, tab_clients = st.tabs(["📝 הצעת מחיר חדשה", "📅 יומן עבודות", "👥 לקוחות וגבייה"])

# ---------------------------------------------------------------- טאב 1
with tab_quote:
    st.subheader("הצעת מחיר חדשה")
    with st.form("new_quote_form"):
        client_name = st.text_input("שם הלקוח")
        client_phone = st.text_input("טלפון")
        trade = st.selectbox("תחום", ["חשמלאי", "אינסטלטור", "שיפוצניק", "אחר"])
        description = st.text_area(
            "תיאור העבודה (כמו שהיית כותב בוואטסאפ)",
            placeholder="למשל: החלפת לוח חשמל ראשי בדירה של 4 חדרים, כולל 3 מפסקי פחת חדשים",
            height=120,
        )
        submitted = st.form_submit_button("צור הצעת מחיר", type="primary", use_container_width=True)

    if submitted:
        if not client_name or not description:
            st.error("צריך למלא לפחות שם לקוח ותיאור עבודה")
        else:
            with st.spinner("מכין הצעת מחיר..."):
                quote = draft_quote(description, trade=trade)
            st.session_state["draft_quote"] = quote
            st.session_state["draft_client"] = {"name": client_name, "phone": client_phone}
            st.session_state["draft_trade"] = trade
            st.session_state["draft_description"] = description

    if "draft_quote" in st.session_state:
        quote = st.session_state["draft_quote"]
        st.markdown(f"### {quote['job_title']}")
        st.table(
            [
                {
                    "סעיף": item["description"],
                    "כמות": item["quantity"],
                    "יח'": item["unit"],
                    "מחיר יח'": f"{item['unit_price']:,.0f} ₪",
                    "סה\"כ": f"{item['line_total']:,.0f} ₪",
                }
                for item in quote["items"]
            ]
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("לפני מע\"מ", f"{quote['subtotal']:,.0f} ₪")
        col2.metric(f"מע\"מ ({quote['vat_rate']*100:.0f}%)", f"{quote['vat_amount']:,.0f} ₪")
        col3.metric("סה\"כ לתשלום", f"{quote['total']:,.0f} ₪")
        if quote.get("notes"):
            st.info(quote["notes"])

        if st.button("💾 שמור ותוסיף ליומן", type="primary"):
            client = storage.add_client(
                st.session_state["draft_client"]["name"],
                st.session_state["draft_client"]["phone"],
            )
            storage.add_job(
                client["id"],
                st.session_state["draft_description"],
                st.session_state["draft_trade"],
                quote,
            )
            st.success("נשמר! אפשר לתאם תור בטאב 'יומן עבודות'")
            for key in ("draft_quote", "draft_client", "draft_trade", "draft_description"):
                st.session_state.pop(key, None)

# ---------------------------------------------------------------- טאב 2
with tab_calendar:
    st.subheader("יומן עבודות")
    jobs = storage.list_jobs()
    if not jobs:
        st.caption("עדיין אין עבודות שמורות - התחילו מטאב 'הצעת מחיר חדשה'")
    for job in sorted(jobs, key=lambda j: j.get("scheduled_date") or "9999"):
        client = storage.get_client(job["client_id"]) or {}
        with st.expander(f"{job['quote']['job_title']} — {client.get('name', '?')} ({job['status']})"):
            st.write(f"**תיאור:** {job['description']}")
            st.write(f"**סה\"כ הצעה:** {job['quote']['total']:,.0f} ₪")
            new_date = st.date_input("תאריך מתוזמן", key=f"date_{job['id']}")
            new_status = st.selectbox(
                "סטטוס", storage.JOB_STATUSES, index=storage.JOB_STATUSES.index(job["status"]), key=f"status_{job['id']}"
            )
            if st.button("עדכן", key=f"update_{job['id']}"):
                storage.update_job(job["id"], scheduled_date=str(new_date), status=new_status)
                st.rerun()

# ---------------------------------------------------------------- טאב 3
with tab_clients:
    st.subheader("לקוחות וגבייה")
    clients = storage.list_clients()
    jobs = storage.list_jobs()
    if not clients:
        st.caption("עדיין אין לקוחות שמורים")
    for client in clients:
        client_jobs = [j for j in jobs if j["client_id"] == client["id"]]
        total_open = sum(j["quote"]["total"] for j in client_jobs if j["status"] != "שולם")
        with st.expander(f"{client['name']} · {client['phone']} · פתוח: {total_open:,.0f} ₪"):
            for job in client_jobs:
                st.write(f"- {job['quote']['job_title']}: {job['quote']['total']:,.0f} ₪ · {job['status']}")
