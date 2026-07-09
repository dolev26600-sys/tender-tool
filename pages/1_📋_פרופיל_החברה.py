#!/usr/bin/env python3
"""
עמוד: עריכת פרופיל החברה דרך טופס נוח - בלי לגעת ב-JSON.

השדות הכי קריטיים להשלמה (לפי מה שכבר סוכם): תאריכי הניסיון התפעולי,
פרטי כל אחד מ-5 המנהלים בנפרד, ומצב מסמכי הרישום/מס/עסק חי - מקבלים כאן
טופס ייעודי. שדות פחות דחופים (תחומי פעילות, אישורי ספק וכו') נגישים
תחת "שדות נוספים" בתחתית העמוד.
"""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from ui_common import (
    check_password,
    clean_for_input,
    configure_page,
    is_filled,
    render_footer,
    render_header,
    restore_placeholder,
)

BASE_DIR = Path(__file__).resolve().parent.parent
PROFILE_PATH = BASE_DIR / "company_profile.json"

configure_page("פרופיל החברה")

if not check_password():
    st.stop()

render_header("📋 פרופיל החברה", "הפרטים כאן משמשים את המנוע להשוואה מול תנאי כל מכרז - ככל שיהיו מדויקים יותר, כך ההשוואה תהיה מדויקת יותר")

if not PROFILE_PATH.exists():
    st.error("לא נמצא קובץ פרופיל החברה (company_profile.json).")
    st.stop()

with open(PROFILE_PATH, encoding="utf-8") as f:
    profile = json.load(f)


def _todo(*values) -> str:
    """מחזיר תווית '🔸 יש להשלים' אם אחד מהערכים עדיין לא מולא."""
    return "" if all(is_filled(v) for v in values) else " 🔸"


DOCUMENT_LABELS = [
    "רישום כדין",
    "אישור ניהול פנקסים / דיווח מס",
    "תצהיר היעדר הרשעות",
    "אישור עסק חי",
    "רישיון מוסד (אם קיים)",
]

MANAGER_FIELD_LABELS = {
    "name": "שם",
    "exact_degree": "תואר מדויק",
    "license": "רישיון",
    "seniority_years": "ותק בשנים",
    "role_start_date": "תאריך התחלה בתפקיד",
    "role_end_date": "תאריך סיום (או 'נוכחי')",
    "facility_type_managed": "סוג המסגרת שניהל/מנהל",
}

with st.form("profile_form"):
    st.markdown("### פרטי יסוד")
    col1, col2 = st.columns(2)
    with col1:
        org_name = st.text_input("שם הארגון", value=profile.get("org_name", ""))
        active_since_year = st.number_input(
            "פעילים משנת", value=int(profile.get("active_since_year") or 2000), step=1, format="%d"
        )
        employee_count_approx = st.number_input(
            "מספר עובדים (בקירוב)", value=int(profile.get("employee_count_approx") or 0), step=1, format="%d"
        )
    with col2:
        field = st.text_input("תחום", value=profile.get("field", ""))
        current_clients_served_approx = st.number_input(
            "מספר מטופלים/דיירים בקירוב", value=int(profile.get("current_clients_served_approx") or 0), step=1, format="%d"
        )

    st.divider()
    exp_list = profile.get("operational_experience") or [{}]
    exp = exp_list[0]
    st.markdown(f"### ניסיון במסגרת לינה חוץ-ביתית{_todo(exp.get('facility_name'), exp.get('start_date'), exp.get('end_date'), exp.get('population_served'), exp.get('avg_residents_per_month'))}")
    st.caption("קריטי למכרזים שדורשים ניסיון תפעולי מוכח בהיקף/תאריכים מדויקים.")

    col1, col2 = st.columns(2)
    with col1:
        exp_facility_name = st.text_input("שם המסגרת", value=clean_for_input(exp.get("facility_name")))
        exp_start_date = st.text_input("תאריך התחלה (MM/YYYY)", value=clean_for_input(exp.get("start_date")))
        exp_avg_residents = st.text_input("מספר דיירים ממוצע לחודש", value=clean_for_input(exp.get("avg_residents_per_month")))
    with col2:
        exp_population = st.text_input("סוג האוכלוסייה שטופלה", value=clean_for_input(exp.get("population_served")))
        exp_end_date = st.text_input("תאריך סיום (או 'מתמשך')", value=clean_for_input(exp.get("end_date")))
    exp_notes = st.text_area("הערות נוספות", value=exp.get("notes", ""))

    st.divider()
    st.markdown("### 5 המנהלים")
    st.caption("לכל מנהל בנפרד - כדי לבדוק התאמה פרטנית לדרישות 'מנהל מסגרת' בכל מכרז.")

    managers = profile.get("leadership", {}).get("managers") or [{} for _ in range(5)]
    while len(managers) < 5:
        managers.append({})

    manager_inputs = []
    for i, mgr in enumerate(managers[:5], start=1):
        todo = _todo(*[mgr.get(k) for k in MANAGER_FIELD_LABELS])
        with st.expander(f"מנהל/ת {i}{todo}", expanded=(i == 1)):
            mc1, mc2 = st.columns(2)
            with mc1:
                name = st.text_input(MANAGER_FIELD_LABELS["name"], value=clean_for_input(mgr.get("name")), key=f"mgr_{i}_name")
                exact_degree = st.text_input(MANAGER_FIELD_LABELS["exact_degree"], value=clean_for_input(mgr.get("exact_degree")), key=f"mgr_{i}_degree")
                license_ = st.text_input(MANAGER_FIELD_LABELS["license"], value=clean_for_input(mgr.get("license")), key=f"mgr_{i}_license")
                seniority_years = st.text_input(MANAGER_FIELD_LABELS["seniority_years"], value=clean_for_input(mgr.get("seniority_years")), key=f"mgr_{i}_seniority")
            with mc2:
                role_start_date = st.text_input(MANAGER_FIELD_LABELS["role_start_date"], value=clean_for_input(mgr.get("role_start_date")), key=f"mgr_{i}_start")
                role_end_date = st.text_input(MANAGER_FIELD_LABELS["role_end_date"], value=clean_for_input(mgr.get("role_end_date")), key=f"mgr_{i}_end")
                facility_type_managed = st.text_input(MANAGER_FIELD_LABELS["facility_type_managed"], value=clean_for_input(mgr.get("facility_type_managed")), key=f"mgr_{i}_facility")
        manager_inputs.append(
            {
                "name": name,
                "exact_degree": exact_degree,
                "license": license_,
                "seniority_years": seniority_years,
                "role_start_date": role_start_date,
                "role_end_date": role_end_date,
                "facility_type_managed": facility_type_managed,
            }
        )

    st.divider()
    docs = profile.get("documents_on_file", {})
    docs_todo = _todo(*[docs.get(label) for label in DOCUMENT_LABELS])
    st.markdown(f"### מסמכי רישום / מס / עסק חי{docs_todo}")
    st.caption("לכל מסמך - מצב עדכני (יש/אין, ותוקף אם רלוונטי).")

    doc_inputs = {}
    for label in DOCUMENT_LABELS:
        doc_inputs[label] = st.text_input(label, value=clean_for_input(docs.get(label)), key=f"doc_{label}")

    st.divider()
    with st.expander("שדות נוספים (פחות דחוף לעדכן)"):
        employee_roles = st.text_area(
            "תפקידי עובדים (שורה לכל תפקיד)",
            value="\n".join(profile.get("employee_roles", [])),
        )
        services_provided = st.text_area(
            "שירותים שניתנים (שורה לכל שירות)",
            value="\n".join(profile.get("services_provided", [])),
        )
        supplier_status = st.text_area(
            "רישום כספק מוכר אצל (שורה לכל גורם)",
            value="\n".join(profile.get("supplier_status", [])),
        )
        staff_credentials_available = st.text_area(
            "הכשרות זמינות בצוות (שורה לכל הכשרה)",
            value="\n".join(profile.get("staff_credentials_available", [])),
        )

    st.write("")
    save_clicked = st.form_submit_button("💾 שמור שינויים", type="primary", use_container_width=True)

if save_clicked:
    profile["org_name"] = org_name.strip()
    profile["field"] = field.strip()
    profile["active_since_year"] = int(active_since_year)
    profile["employee_count_approx"] = int(employee_count_approx)
    profile["current_clients_served_approx"] = int(current_clients_served_approx)

    profile["operational_experience"] = [
        {
            "type": exp.get("type", "מסגרת לינה חוץ ביתית טיפולית"),
            "facility_name": restore_placeholder(exp_facility_name),
            "population_served": restore_placeholder(exp_population),
            "start_date": restore_placeholder(exp_start_date),
            "end_date": restore_placeholder(exp_end_date),
            "avg_residents_per_month": restore_placeholder(exp_avg_residents),
            "notes": exp_notes.strip(),
        }
    ]

    profile.setdefault("leadership", {})
    profile["leadership"]["count"] = 5
    profile["leadership"]["managers"] = [
        {k: restore_placeholder(v) for k, v in mgr.items()} for mgr in manager_inputs
    ]
    profile["leadership"].setdefault("shared_experience", [])
    profile["leadership"].setdefault("notes", "")

    profile["documents_on_file"] = {label: restore_placeholder(value) for label, value in doc_inputs.items()}

    profile["employee_roles"] = [line.strip() for line in employee_roles.splitlines() if line.strip()]
    profile["services_provided"] = [line.strip() for line in services_provided.splitlines() if line.strip()]
    profile["supplier_status"] = [line.strip() for line in supplier_status.splitlines() if line.strip()]
    profile["staff_credentials_available"] = [line.strip() for line in staff_credentials_available.splitlines() if line.strip()]

    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    st.success("הפרופיל נשמר בהצלחה.", icon="✅")
    st.rerun()

render_footer()
