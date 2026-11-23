# Agent Workshop

אפליקציה שבונה אפליקציות בעזרת ארבעה סוכני AI, עם אישור אנושי בכל שלב:

- **Planner** – הופך רעיון לתוכנית מפורטת, ועונה על שאלות או מעדכן אותה.
- **Builder** – כותב את קבצי הפרויקט לפי התוכנית שאושרה.
- **Tester** – סוקר את הקוד (סקירה סטטית, בלי הרצה) ומחזיר ממצאים לפי חומרה.
- **Polisher** – משפר UI/UX בלי לשנות פונקציונליות.

הקבצים נשמרים בדפדפן (`localStorage`) ואפשר להוריד אותם כ-ZIP.

## ארכיטקטורה

- `public/index.html` – כל הממשק (HTML/CSS/JS, בלי build).
- `api/index.py` – FastAPI עם נקודת קצה אחת: `POST /api/agent`.
- `api/_gemini_client.py` – כל הגישה ל-Gemini. המפתח נקרא רק ממשתנה הסביבה `GEMINI_API_KEY`.

### מדיניות מודלים: איכות קודם

1. מודלי Flash מלאים, מהטוב ביותר: `gemini-3.8-flash` ← `3.7` ← `3.6` ← `3.5` ← `gemini-3-flash-preview`.
2. רק אחריהם Flash-Lite: `gemini-3.5-flash-lite` ← `gemini-3.1-flash-lite`.

- מכסה יומית נגמרה, עומס, 404 או אין תשובה בזמן – עוברים למודל הבא.
- מגבלה לדקה – ממתינים פעם אחת (עד 60 שניות) ומנסים שוב את אותו מודל.
- כל מעבר נרשם ב-Agent Activity.
- אפשר לשנות את הסדר דרך משתנה הסביבה `GEMINI_MODEL` (רשימה מופרדת בפסיקים).

## הרצה מקומית (Windows)

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env
uvicorn api.index:app --reload
```

פותחים את http://localhost:8000.

מפתח חינמי: https://aistudio.google.com/apikey (בלי billing).

## פריסה ב-Vercel

1. מייבאים את הריפו ב-Vercel (Add New → Project).
2. מוסיפים משתנה סביבה `GEMINI_API_KEY`.
3. `vercel.json` מגדיר `maxDuration: 300` (המקסימום בתוכנית Hobby).

## מפת דרכים

- **Streaming והמשכיות ל-Builder** – הפלט מוזרם לדפדפן, כל קובץ שהושלם נשמר, וכשהזמן נגמר נפתחת קריאת המשך עם מה שנכתב ומה שנשאר. בנוסף, זיהוי מודל תקוע לפי הזמן עד הטוקן הראשון.
- **בחירת מודל בממשק** – Auto (הטוב ביותר) / Fast (Flash-Lite) / מודל מסוים, ובחירה בין המתנה למעבר מודל כשהשרת עמוס.
- **שמירה בענן והזדהות** – התחלה במכשיר אחד והמשך במכשיר אחר עם אותו חשבון (פתרון חינמי).

## היסטוריה

האפליקציה נבנתה במקור כ-Claude Artifact. הגרסה המקורית נמצאת ב-`previous versions/`.
