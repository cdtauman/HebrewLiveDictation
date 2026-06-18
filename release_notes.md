<div dir="rtl">

# 🚀 Hebrew Live Dictation v1.1.0

שדרוג גדול שהופך את המנוע ל**אגנוסטי לספק** ומבוסס‑בנצ'מארק, עם שמירה מלאה על השילוב העמוק עם Windows. ברירת המחדל נשארת Google STT V2 / Chirp 3, וכל היכולות החדשות כבויות כברירת מחדל ונשלטות מההגדרות.

### ✨ מה חדש
* **חמישה מצבי מנוע:** Smart Auto (בחירה אוטומטית), עברית מיטבית בזמן אמת (Deepgram), מצב לא‑מקוון/פרטי (Whisper מקומי), ענן הזול ביותר (Groq), ו‑AutoFallback מענן למקומי.
* **תמלול לא‑מקוון:** Whisper מקומי (faster‑whisper) עם הורדת מודל לפי דרישה, בדיקת זיכרון, ואינדיקציית מצב/נתיב בעמוד "מנוע".
* **אחסון מאובטח של מפתחות:** מפתחות Deepgram/Groq נשמרים ב‑Windows Credential Manager (לא בקובץ הגדרות), עם כפתור "בדיקה".
* **היסטוריה וייצוא:** שמירת תמלולים וייצוא ל‑TXT ול‑Word (DOCX) עם כיווניות RTL נכונה.
* **חוויית משתמש:** צלילי התחלה/סיום, סרגל צף וכפתור הפעלה מהירה (ללא גניבת פוקוס), ומקש השהיה/חידוש.
* **עדכון אוטומטי חתום:** בדיקת מניפסט חתום (Ed25519) מ‑GitHub עם אימות חתימה לפני כל עדכון.
* **בנצ'מארק WER** להשוואת ספקים, ובדיקות אוטומטיות מורחבות (206 בדיקות).

נשמר ללא פגיעה: הזרקת טקסט (Word COM, UI Automation, SendInput, לוח גזירה), מעקב יעד, חבילות פקודות, עריכת הכתבה, פרטיות בלוגים, ו‑CI. רכיב ה‑TSF/IME נשאר ניסיוני וכבוי.

---

</div>

<div dir="ltr">

# 🚀 Hebrew Live Dictation v1.1.0

A major upgrade that makes the engine **provider-agnostic** and benchmark-driven while fully preserving the deep Windows integration. Google STT V2 / Chirp 3 stays the default; everything new is off by default and controlled from Settings.

### ✨ What's new
* **Five engine modes:** Smart Auto (automatic provider selection), Best Hebrew realtime (Deepgram), Offline/private (local Whisper), Cheapest cloud (Groq), and AutoFallback (cloud → local on failure).
* **Offline transcription:** local Whisper (faster-whisper) with on-demand model download, RAM preflight, and status/path indicators on the new **Engine** page.
* **Secure credentials:** Deepgram/Groq API keys are stored in the Windows Credential Manager (never in settings), with a "Test" button.
* **History & export:** transcript history with TXT and RTL-correct **DOCX** export.
* **UX:** start/stop audio tones, a draggable floating toolbar + idle quick-start button (no focus stealing), and a pause/resume hotkey.
* **Signed auto-updater:** verifies an Ed25519 signature over the GitHub release manifest before trusting any update.
* **WER benchmark** harness for provider comparison and an expanded test suite (206 tests).

Preserved intact: text injection (Word COM, UI Automation, Unicode SendInput, clipboard), target tracking, command packs, session editing, privacy logging, and CI. TSF/IME remains experimental and disabled by default.

</div>
