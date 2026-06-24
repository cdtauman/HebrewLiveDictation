<div dir="rtl">

# VoiceType — בטא WinUI (לא חתום, לבדיקה ידנית)

> **סטטוס:** ארטיפקט בדיקה **לא חתום**. זו **אינה** בטא ציבורית ואינה גרסה מאושרת.
> הבדיקה רצה מול ארטיפקט ה‑CI בשם `VoiceType-winui-beta-unsigned` בלבד.

גרסה זו מחליפה את אפליקציית ה‑PySide/Qt הישנה בקליפה חדשה ב‑**WinUI 3** עם מנוע
**Python** נפרד (sidecar) המחוברים דרך named‑pipe. העבודה בוצעה בתוכנית מבוקרת בת 20
שלבים שמטרתה לאחד את הטוב משלוש הגרסאות (PySide המקורית, מנוע ה‑v1.1 העשיר, וקליפת
ה‑WinUI) — בלי לאשר שחרור.

### מה יש בגרסה

- **הכתבה בעברית, הכנסה סופית בלבד** לחלון היעד (F8 / שלט צף). מילים חיות מוצגות ב‑HUD
  ובשלט בלבד — לא נכתבות ליעד.
- **שישה חדרים** (בית, הכתבה, מנוע, שליטה, היסטוריה, הגדרות) + אונבורדינג.
- **מנוע לא‑מקוון (Whisper)** — מומלץ לבטא; פרטי, אך "מוכן" רק לאחר הורדת מודל בחדר "מנוע".
- **Google STT V2** — הנתיב המוגן הוא `latest_long / eu / iw-IL / _`. **"בדיקת חיבור"
  מאמתת את נתיב ה‑Recognizer בלבד — היא אינה הוכחת הכתבה.**
- **Deepgram / Groq** — דורשים **מפתח של המשתמש** (נשמר ב‑Windows Credential Manager)
  ובדיקת חיבור. אין הוכחת תמלול אמיתי ללא מפתח.
- **Smart Auto / גיבוי לא‑מקוון** — ניסיוני; אינו ברירת המחדל. גיבוי לא‑מקוון זמין רק
  כשמותקן מודל מקומי.
- **השהיה/חידוש** ששומרים על מושב ההכתבה, **צלילי התחלה/עצירה**, **היסטוריה + ייצוא
  TXT/DOCX**, **מאגר מפתחות (keyring)**, **בודק עדכונים חתום (Ed25519)** — התקנה נשארת ידנית.
- **פרטיות:** מפתחות ב‑keyring בלבד; נתיבי הרשאות וטוקנים של ספקים מצונזרים בלוגים,
  בהודעות שגיאה ובאבחון.

### מה עדיין דורש הוכחה ידנית/חיצונית

- הכתבת Google מלאה מול הארטיפקט הארוז (R3).
- מטריצת ההכנסה המלאה ל‑Windows (Word, דפדפן, צ'אט, VS Code).
- תמלול אמיתי ב‑Deepgram וב‑Groq עם מפתח משתמש.
- חתימת Authenticode (דורשת תעודה) — הארטיפקט אינו חתום.

</div>

<div dir="ltr">

# VoiceType — WinUI beta (unsigned, manual-test)

> **Status: unsigned manual-test artifact. NOT a public beta and NOT an approved
> release.** Testing runs only against the CI artifact `VoiceType-winui-beta-unsigned`.

This replaces the legacy PySide/Qt app with a new **WinUI 3** shell and a separate
**Python** engine sidecar connected over a named pipe. The work was done in a
controlled 20-phase completion program that consolidates the best of the original
PySide app, the richer v1.1 engine, and the WinUI shell — without approving a release.

### What's in this build

- **Hebrew dictation, final-only insertion** into the target (F8 / floating Remote).
  Live words appear only in the HUD/Remote — never typed into the target.
- **Six rooms** (Home, Dictation, Engine, Controls, History, Settings) + onboarding.
- **Offline (Whisper)** — recommended for the beta; private, but only "ready" once a
  model is downloaded in the Engine room.
- **Google STT V2** — the regression-protected combo is `latest_long / eu / iw-IL / _`.
  **"Test Connection" verifies the recognizer path only — it is not dictation proof.**
- **Deepgram / Groq** — require **your** API key (stored in Windows Credential Manager)
  and Test Connection. No real-transcription proof without a user key.
- **Smart Auto / offline backup** — experimental; not the default. Offline backup is
  only available when a local model is installed.
- **Session-preserving pause/resume**, **start/stop tones**, **history + TXT/DOCX
  export**, **OS keyring** for cloud keys, **signed update check (Ed25519)** —
  installation stays manual.
- **Privacy:** keys in the OS keyring only; credential paths and provider/API tokens
  are redacted from logs, error messages, and diagnostics.

### Automated proof (at this writing)

- Python unit/integration suite passes.
- WinUI runtime self-test passes.
- Packaging and release audits pass.

Automated tests are **not** beta approval.

### Still requires manual/external proof

- Full packaged Google R3 dictation against the artifact.
- Full Windows insertion matrix (Word, browser, chat apps, VS Code).
- Real Deepgram and Groq transcription with a user key.
- Authenticode signing (needs a code-signing certificate) — this artifact is unsigned.

</div>
