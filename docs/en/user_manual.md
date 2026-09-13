# User Manual — BioVision Suite

Guide to using the facial biometric analysis platform, module by module.
Written for people who will operate the application day-to-day (registering
people, searching, analyzing video, reviewing statistics), not for developers
— see the *Developer Guide* for that.

---

## 1. Login

When opening the application, **username and password** are required. BioVision
Suite has no default accounts: the first time it runs, a wizard guides the
creation of the administrator account.

- After **5 failed attempts** (configurable), the account is temporarily
  locked for security.
- If the application remains **inactive** for a prolonged period, it
  automatically locks and asks to re-enter the password to continue (or log
  out).
- The **"Log out"** button, in the top-right corner, allows another person to
  log in with their own account without closing the application.

Which modules you see in the sidebar depends on your **role**:

| Role | Can View |
|---|---|
| Administrator | All modules, including Administration |
| Operator | Dashboard, Persons, Comparator, Search, Webcam, Video, Statistics |
| Viewer | Dashboard, Search, Statistics (read-only) |

---

## 2. Dashboard

Home screen with a general summary:

- **Registered persons**, **recognition events** (today and total),
  **average confidence**.
- **Recent activity**: latest recognitions, indicating whether there was a
  match or not, its source (webcam/video/image) and confidence.

---

## 3. Persons — Registration

This module is **exclusively for enrolling people**: the data record and its
photo dataset. It does not show the list of registered people (to search or
review existing records use the **Search** module).

1. Fill out the form on the left. **First Name** and **Last Name** are
   required (marked with `*`); the rest — alias, sex, age, company,
   department, position, contact, notes — is optional. Email is validated
   automatically.
2. Add the dataset photos. You can **drag and drop** photos onto the box on
   the right, click **"+ Add photos"** to select them from disk, or use
   **"Webcam"** to capture a photo on the spot (with the option to retry).
   The first photo will be marked as primary.
3. Click **"Save person"**. In the background the person is created and each
   photo is processed automatically: the main face is detected and its
   biometric vector (*embedding*) is extracted, showing progress.
4. When finished, **the form and dataset are cleared automatically** to
   register the next person. The summary indicates how many photos were
   processed; rejected ones (no face or insufficient quality) are listed with
   their reason. You can also click **"Clear"** at any time to discard
   unsaved data.

**Photo recommendations:** frontal face, good lighting, no obstructions. If a
photo has insufficient quality (blurry, too dark, or no detectable face), the
application rejects it and explains why.

---

## 4. Biometric Comparator

Compares two photos (Image A vs. Image B) and answers: *is it the same
person?*

1. Select Image A and Image B.
2. Click **"Compare faces"**.
3. The result shows: **similarity** (%), **cosine distance**, the **threshold**
   used, and the verdict ("Same person" / "Different persons").

Useful for spot verification (for example, comparing an ID photo against a
photo taken on the spot) without needing the person to be registered in the
database.

---

## 5. Smart Search

Two ways to search for already registered people:

- **By text**: name, alias, company, or email (partial search).
- **By photo**: upload an image and the system compares it against *all*
  registered people, returning the most similar ones sorted by match
  percentage. A checkmark icon next to the percentage indicates it exceeds the
  configured match threshold.

---

## 6. Live Webcam

Real-time facial recognition using the computer's camera.

1. Choose the camera (if more than one is connected).
2. Click **"Start"**. Each detected face is framed: **green** if it matches
   someone registered (with name and confidence %), **red** if not recognized.
3. **"Stop"** turns off the camera.

All processing happens on the local machine; no video leaves the application.
Each recognition is recorded in the general history.

> Before using this module on identifiable people, make sure you have an
> appropriate lawful basis (e.g., informed consent); see the biometric data
> note in `README.md`.

---

## 7. Video Analysis

Analyzes a complete video file (MP4, AVI, MOV, MKV) searching for known faces.

1. Drag the video, or use **"Select video"**.
2. Choose the **sampling level** (Detailed / Standard / Fast / Very fast): how
   frequently frames are analyzed.
3. Click **"Analyze video"**. Processing runs in the background (does not
   block the UI) showing a progress bar; long videos may take several minutes.
4. When finished, it appears in the **"Analyzed videos"** list with its
   status, date, and number of detections.
5. Click a completed video to see **details** (the preview occupies all
   available space and adapts to window size):
   - Detections table (frame, time, person, confidence, and status),
     **resizable** and with **minimum confidence filter**.
   - **Continuous playback** (▶/⏸) of the video.
   - Slider and **start/end** and **previous/next detection** buttons to jump
     between matches, with the face highlighted.
   - **Clickable chips per person**: click to jump to their first appearance.
6. **"Export"** offers **Excel** (summary sheet with KPIs + detections sheet
   with styling: headers, auto-filters, status highlighting) or **CSV**.

---

## 8. Statistics

View with key indicators and charts:

- Registered persons (cumulative over time).
- Recognition activity (filterable by 7/30/90/365 days).
- Confidence distribution of matches.
- Recognitions by source (webcam / video / image).
- Distribution of persons by company and by department.

From the same module you can **export results**:

| Button | What It Exports | Formats |
|---|---|---|
| Export persons | Complete record for each person | CSV, Excel, JSON |
| Export recognition events | Complete history | CSV, Excel, JSON |
| Export PDF report | KPIs + 5 main charts, ready to share | PDF |
| Back up database | Complete copy of the database | SQLite (.db) |

---

## 9. Administration

*(Visible only to the Administrator role.)*

### 9.1. Users
Create users, change their role, reset their password, activate or deactivate
their account, or delete them. You cannot deactivate or delete your own
currently logged-in account.

### 9.2. Roles and Permissions
Each role is a list of permissions (which modules can be viewed/used). You can
create new roles or edit permissions of existing ones by checking the
corresponding boxes. A role cannot be deleted while it has assigned users.

### 9.3. Backup / Restore / Cleanup
- **Backup**: generates a complete and consistent `.db` copy.
- **Restore**: replaces the current database with a selected backup.
  **Irreversible action** — the application closes upon completion to apply
  changes safely; it must be reopened manually.
- **Cleanup**: deletes all persons, photos, events, and analyzed videos
  (users and roles are preserved). Requires typing **DELETE** to confirm.

### 9.4. Secure Configuration
Allows saving sensitive values (for example, credentials that a future
integration module might use) **encrypted in the database**; they are never
stored in plaintext. A "View value" button allows retrieving them when needed.

### 9.5. Audit
Shows the application's audit log (registrations, deletions, logins, lockouts,
restores, etc.), with a free-text filter.

### 9.6. Facial Calibration
Diagnostics for "extended facial analysis" (glasses, mask, beard, mustache,
smile, eyes open): by sliding a threshold (0–1) you instantly see, person by
person, which attributes change and their raw confidence (hover over the cell).
The **Apply thresholds and save** button persists the new results in the
database. If you want to re-analyze primary photos (for example, old records
saved before this module), the **Re-analyze primary photos** button re-runs
the models on them.

---

## 10. Frequently Asked Questions

**Can I use the application without an Internet connection?**
Yes, except the first time it runs (download of the AI model package). After
that it works completely offline.

**Where is my data stored?**
Everything stays in the project's `data/` folder: the SQLite database, photos,
and video evidence. Nothing is sent to external servers.

**What happens if two people look very similar?**
The system shows the real similarity percentage; if it exceeds the configured
threshold (by default, cosine distance ≤ 0.45) it is marked as a probable
match, but the exact percentage always remains visible so the operator can
make the final decision.
