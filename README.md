# כלי בדיקת עמידה בתנאי סף — א.ג דיור

בודק אם א.ג דיור עומדת בתנאי הסף של מכרזים ממשלתיים, לפני שניגשים אליהם.

## מבנה הפרויקט

```
tender_tool/
├── company_profile.json      # פרופיל החברה (עדכן שדות "לא צוין - יש להשלים")
├── tenders/                  # תנאי סף של מכרזים, כ-JSON קבוע (נוצר אוטומטית או ידנית)
│   └── tender_68_2026_conditions.json
├── reports/                  # דוחות שנשמרים אוטומטית (נוצר בהרצה ראשונה)
├── pdf_extraction.py         # שלב 1: PDF -> טקסט (pdftotext -layout, נופל ל-pdfplumber)
├── condition_extraction.py   # שלב 2: טקסט -> תנאי סף ב-JSON (קריאה ל-Claude)
├── eligibility_engine.py     # שלב 3: השוואה סמנטית פרופיל <-> תנאי סף (קריאה ל-Claude)
├── report.py                 # עיצוב ושמירת דו"ח
├── analyze_tender.py         # CLI - מריץ את כל השרשרת על PDF חדש (משורת פקודה)
├── compare_eligibility.py    # CLI חלופי - למכרז שתנאיו כבר קיימים כ-JSON
├── app.py                    # ממשק web (Streamlit) - להעלאת PDF ולחיצת כפתור, לשליחה לעובדים
└── requirements.txt
```

## התקנה

```bash
cd tender_tool
python3 -m venv venv && source venv/bin/activate   # מומלץ, לא חובה
pip install -r requirements.txt

export ANTHROPIC_API_KEY="sk-ant-..."   # מפתח Claude API - חובה
```

`pdftotext` (חלק מ-poppler) הוא אופציונלי - אם הוא לא מותקן, הכלי נופל
אוטומטית ל-pdfplumber (שמותקן דרך requirements.txt וזה מספיק כדי שהכלי יעבוד).
להתקנת poppler ב-Mac: `brew install poppler`.

## שימוש

### מכרז חדש (יש רק PDF)

```bash
python analyze_tender.py path/to/tender.pdf
```

מריץ את כל השרשרת: מחלץ טקסט מה-PDF → שולח ל-Claude לחילוץ תנאי הסף
לפורמט JSON קבוע → **בודק את עצמו שוב עד 3 פעמים** (קורא מחדש את הטקסט
המלא מול הרשימה שחולצה, כדי לתפוס תנאים שהוחמצו או טעויות סיווג) → שומר
אוטומטית ב-`tenders/` → משווה מול `company_profile.json` → מדפיס ושומר
דו"ח (ב-`reports/`).

הבדיקה החוזרת (verification) היא כדי לא לפספס אף תנאי סף - זה קריטי כי
פספוס תנאי סף יכול לגרום לפסילת הצעה על הסף. אפשר לשלוט בכמות המעברים:

```bash
python analyze_tender.py path/to/tender.pdf --verification-passes 5
python analyze_tender.py path/to/tender.pdf --no-save   # לא לשמור דו"ח לקובץ
```

### מכרז שתנאיו כבר חולצו (יש קובץ JSON ב-tenders/)

```bash
python compare_eligibility.py tenders/tender_68_2026_conditions.json
```

מריץ רק את שלב ההשוואה (לא צריך PDF, לא מריץ מחדש את שלב החילוץ - מהיר
וזול יותר אם התנאים כבר מוכרים).

## ממשק Web — לשליחה לעובדים

`app.py` הוא אותו כלי בדיוק, אבל בממשק דפדפן: העלאת קובץ PDF + כפתור, בלי
טרמינל ובלי פקודות. מתאים לשליחה לעובד שלא מכיר שורת פקודה.

### הרצה מקומית (בדיקה על המחשב שלך)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
streamlit run app.py
```

זה פותח אוטומטית טאב בדפדפן בכתובת `http://localhost:8501`.

### הגנת סיסמה (מומלץ אם האפליקציה נגישה למישהו חוץ ממך)

```bash
export TENDER_TOOL_PASSWORD="בחר-סיסמה-משותפת"
```

אם משתנה הסביבה הזה מוגדר, האפליקציה תבקש סיסמה לפני שימוש. **חשוב**:
המידע שהאפליקציה מטפלת בו (תנאי מכרזים, פרופיל החברה) הוא מידע עסקי של
החברה - כדאי להגן עליו אם האפליקציה נגישה מעבר למחשב שלך בלבד.

### איך "שולחים לעובד"

יש שתי דרכים שונות מאוד לגרום לעובד להגיע לאפליקציה, וכדאי לבחור לפי
הצורך בפועל:

1. **רשת פנימית / אותו Wi-Fi** (הכי מהיר להתחיל, בלי הרשמה לשום שירות):
   מריצים `streamlit run app.py` על המחשב שלך, ו-Streamlit מדפיס גם
   "Network URL" (כתובת IP פנימית) - עובד שנמצא על אותה רשת (משרד) יכול
   להיכנס לכתובת הזו מהדפדפן שלו. חיסרון: זה עובד רק כשהמחשב שלך דלוק
   ומחובר לאותה רשת.

2. **אחסון אמיתי באינטרנט** (כתובת קבועה, נגישה מכל מקום, לא תלוי שהמחשב
   שלך דלוק) - דרך **Streamlit Community Cloud** (חינמי). זה דורש הקמה
   חד-פעמית של חשבונות שלך (GitHub + Streamlit Cloud):

   **מה כבר מוכן בקוד** (בוצע): הפרויקט הוא כבר repo של git, עם `.gitignore`
   שמוודא שה-`.env` (המפתח הסודי) **לא** יעלה ל-GitHub בטעות.

   **מה שרק אתה יכול לעשות** (כי זה דורש את החשבונות שלך):

   1. **התקן GitHub Desktop** (ממשק גרפי, בלי צורך בפקודות טרמינל
      להעלאה): https://desktop.github.com - התקן והתחבר עם חשבון GitHub
      (או צור חשבון חינמי אם אין לך, ישירות באפליקציה).
   2. ב-GitHub Desktop: **File → Add Local Repository** → בחר את התיקייה
      `~/Desktop/tender_tool` → **Publish repository** (מומלץ לסמן
      **Keep this code private**).
   3. כנס ל-https://share.streamlit.io והתחבר עם **אותו חשבון GitHub**.
   4. **Create app** → **Deploy a public app from GitHub** → בחר את
      ה-repository שפרסמת, Branch: `main`, Main file path: `app.py`.
   5. לפני שלוחצים Deploy - פתח **Advanced settings → Secrets** והדבק:
      ```
      ANTHROPIC_API_KEY = "sk-ant-המפתח-שלך"
      TENDER_TOOL_PASSWORD = "בחר-סיסמה-לעובדים"
      ```
      (זה המקום הבטוח לשים את המפתח - הוא לא נכנס לקוד ולא ל-GitHub.)
   6. **Deploy**. אחרי דקה-שתיים תקבל כתובת קבועה בסגנון
      `https://tender-tool-xxxx.streamlit.app` - זו הכתובת ששולחים לעובדים.
      הגישה בפועל עדיין מוגנת בסיסמה (`TENDER_TOOL_PASSWORD`) שהגדרת.

## איך זה עובד

1. **`pdf_extraction.py`** מחלץ טקסט גולמי מה-PDF (`pdftotext -layout`,
   ואם זה לא זמין/לא נקי - `pdfplumber`).
2. **`condition_extraction.py`** שולח את הטקסט ל-Claude עם פרומפט שמכיר
   בדיוק את סכימת ה-JSON של תנאי סף (`tender_id`, `tender_title`,
   ורשימת `conditions` עם `id`/`category`/`requirement`/`type`/
   `alternative_group`/`applies_per_cluster`/`proof_needed`), ומקבל
   JSON תקין בחזרה (structured output - לא צריך "לפרסר" טקסט חופשי).
3. **`eligibility_engine.py`** שולח את פרופיל החברה + תנאי המכרז ל-Claude
   ומקבל בחזרה הערכה סמנטית לכל תנאי בנפרד: סטטוס (met/likely_met/gap/unknown),
   נימוק מפורט, ורשימת פרטים חסרים - **בלי שום if/else ידני בקוד**.
4. **`report.py`** מעצב את התוצאה לדו"ח קריא: קודם בלוק "⚠️ דברים לבדוק/
   להשלים" עם כל התנאים שיש בהם פער או חוסר מידע (כדי שזה לא ייקבר בתוך
   רשימה ארוכה), ואז פירוט מלא לכל תנאי (✅/🟡/🔴/⚪ + נימוק).

## עקרון מפתח

כל עוד שני קבצי ה-JSON (פרופיל החברה ותנאי המכרז) נשארים באותה סכימה,
מנוע ההשוואה לא צריך להשתנות בין מכרז למכרז - רק הנתונים משתנים. זה מה
שהופך את זה מ"סקריפט חד פעמי" ל"כלי חי" שאפשר להריץ על כל מכרז חדש בלי
לגעת בקוד.

## תחזוקה שוטפת

- **פרופיל החברה** (`company_profile.json`): כדאי לעדכן ולהשלים לאורך
  זמן - ככל שיש יותר פרטים מדויקים (תאריכים, מספרים, שמות), כך הדיוק
  של הסטטוסים (met לעומת likely_met) משתפר. שדות מסומנים
  "לא צוין - יש להשלים" מתפרשים כחוסר מידע (⚪), לא כפער (🔴).
- **תנאי מכרזים** (`tenders/*.json`): נוצרים אוטומטית ע"י `analyze_tender.py`,
  אבל אפשר גם לערוך אותם ידנית אם החילוץ האוטומטי טעה במשהו - הם קבצי
  JSON רגילים לפי הסכימה המתועדת למעלה.
- **דוחות** (`reports/*.txt`): נשמרים עם חותמת זמן, לא נמחקים אוטומטית -
  אפשר לנקות מדי פעם.
