# FaceScan — User Manual

Usage guide for the facial biometric analysis platform, module by module.
Written for people who will operate the application day to day (registering
people, searching, analyzing video, reviewing statistics), not for
developers — for that there is the *Developer Guide*.

---

## 1. Signing in

When you open the application you are asked for a **username and
password**. FaceScan has no default accounts: the first time it runs, a
wizard walks you through creating the administrator account.

- After **5 failed attempts** (configurable), the account is temporarily
  locked for security.
- If the application stays **idle** for a long time, it locks automatically
  and asks you to re-enter your password to continue (or to sign out).
- The **"Sign out"** button, at the top-right corner, lets another person
  sign in with their own account without closing the application.

Which modules you see in the sidebar depends on your **role**:

| Role | Can see |
|---|---|
| Administrator | All modules, including Administration |
| Operator | Dashboard, People, Comparator, Search, Webcam, Video, Statistics |
| Viewer | Dashboard, Search, Statistics (read-only) |

---

## 2. Dashboard

Home screen with a general summary:

- **Registered people**, **recognition events** (today and total),
  **average confidence**.
- **Recent activity**: latest recognitions, showing whether there was a
  match or not, its source (webcam/video/image) and the confidence.

---

## 3. People — registration

This module is used **exclusively to enroll people**: the data record and
its photo dataset. It does not show the list of registered people (use the
**Search** module to find or review existing records).

1. Fill in the form on the left. **First name** and **Last name** are
   required (marked with `*`); the rest — alias, sex, age, company,
   department, job title, contact, notes — is optional. The email is
   validated automatically.
2. Add the dataset photos. You can **drag and drop** photos onto the box on
   the right, press **"+ Add photos"** to pick them from disk, or use
   **"Webcam"** to capture one on the spot (with a retry option). The first
   photo is marked as the primary one.
3. Press **"Save person"**. The person is created in the background and each
   photo is processed automatically: the main face is detected and its
   biometric vector (*embedding*) is extracted, showing progress.
4. When finished, **the form and dataset are cleared automatically** so you
   can register the next person. The summary shows how many photos were
   processed; rejected ones (no face or insufficient quality) are listed
   with their reason. You can also press **"Clear"** at any time to discard
   the unsaved data.

**Photo recommendations:** frontal face, good lighting, no obstructions. If
a photo has insufficient quality (blurry, very dark, or no detectable
face), the application rejects it and explains why.

---

## 4. Biometric comparator

Compares two photos (Image A vs. Image B) and answers: *is it the same
person?*

1. Select Image A and Image B.
2. Press **"Compare faces"**.
3. The result shows: **similarity** (%), **cosine distance**, the
   **threshold** used, and the verdict ("Same person" / "Different
   people").

Useful for one-off verification (for example, comparing an ID photo against
one taken on the spot) without needing the person registered in the
database.

---

## 5. Smart search

Two ways to find already-registered people:

- **By text**: name, alias, company or email (partial match).
- **By photo**: upload an image and the system compares it against *all*
  registered people, returning the most similar ones ordered by match
  percentage. A checkmark icon next to the percentage indicates that it
  exceeds the configured match threshold.

---

## 6. Live webcam

Real-time facial recognition using the device camera.

1. Choose the camera (if more than one is connected).
2. Press **"Start"**. Each detected face is framed: **green** if it matches
   a registered person (with their name and confidence %), **red** if it is
   not recognized.
3. **"Stop"** turns the camera off.

All processing happens on the device itself; no video leaves the
application. Every recognition is recorded in the general history.

> Before using this module on identifiable people, make sure you have an
> appropriate legal basis (e.g. informed consent); see the note about
> biometric data in the `README.md`.

---

## 7. Video analysis

Analyzes a complete video file (MP4, AVI, MOV, MKV) looking for known
faces.

1. Drag the video in, or use **"Select video"**.
2. Choose the **sampling level** (Detailed / Standard / Fast / Very fast):
   how often frames are analyzed.
3. Press **"Analyze video"**. Processing runs in the background (it does not
   block the interface) showing a progress bar; long videos can take several
   minutes.
4. When done, it appears in the **"Analyzed videos"** list with its status,
   date and number of detections.
5. Click a completed video to see the **detail** (the preview fills all the
   available space and adapts to the window size):
   - Detections table (frame, time, person, confidence and status),
     **resizable** and with a **minimum-confidence filter**.
   - **Continuous playback** (▶/⏸) of the video.
   - Slider and **start/end** and **previous/next detection** buttons to
     jump between matches, with the face highlighted.
   - **Clickable per-person chips**: click to jump to their first
     appearance.
6. **"Export"** offers **Excel** (summary sheet with KPIs + detections sheet
   with formatting: headers, automatic filters, highlighting by status) or
   **CSV**.

---

## 8. Statistics

View with key indicators and charts:

- Registered people (cumulative over time).
- Recognition activity (filterable by 7/30/90/365 days).
- Confidence distribution of matches.
- Recognitions by source (webcam / video / image).
- Distribution of people by company and by department.

From the same module you can **export results**:

| Button | Exports | Formats |
|---|---|---|
| Export people | Full record of each person | CSV, Excel, JSON |
| Export recognition events | Complete history | CSV, Excel, JSON |
| Export PDF report | KPIs + the 5 main charts, ready to share | PDF |
| Back up database | Full copy of the database | SQLite (.db) |

---

## 9. Administration

*(Only visible to the Administrator role.)*

### 9.1. Users
Create users, change their role, reset their password, activate or
deactivate their account, or delete them. It is not possible to deactivate
or delete the account you are currently signed in with.

### 9.2. Roles and permissions
Each role is a list of permissions (which modules can be seen/used). You
can create new roles or edit the permissions of existing ones by ticking
the corresponding checkboxes. A role cannot be deleted while it still has
users assigned.

### 9.3. Backup / Restore / Cleanup
- **Backup**: generates a complete, consistent `.db` copy.
- **Restore**: replaces the current database with a selected backup.
  **Irreversible action** — the application closes when it finishes to apply
  the changes safely; you must reopen it manually.
- **Cleanup**: deletes all people, photos, events and analyzed videos (users
  and roles are kept). You must type **DELETE** to confirm.

### 9.4. Secure configuration
Lets you store sensitive values (for example, credentials that some
integration module may use in the future) **encrypted in the database**;
they are never stored in plain text. A "View value" button lets you retrieve
them when needed.

### 9.5. Audit
Shows the application audit log (registrations, deletions, sign-ins,
lockouts, restores, etc.), with a free-text filter.

### 9.6. Facial calibration
Diagnosis of "extended facial analysis" (glasses, mask, beard, mustache,
smile, open eyes): by sliding a threshold (0–1) you instantly see, person
by person, which attributes change and their raw confidence (hover over the
cell). The **Apply thresholds and save** button persists the new results in
the database. If you want to re-analyze the primary photos (for example,
old records saved before this module), the **Re-analyze primary photos**
button runs the models over them again.

---

## 10. FAQ

**Can I use the application without an Internet connection?**
Yes. If you installed the **full** version (with facial models), it works
100 % offline from the first launch. In the **compact** installation, the
first time facial recognition is used the AI model package is downloaded
(requires Internet only once).

**Where is my data stored?**
In the installed version, everything stays in the `%LOCALAPPDATA%\FaceScan`
folder on your computer: the SQLite database, photographs, video evidence
and audit logs. Nothing is sent to external servers.

**What happens if two people look very similar?**
The system shows the real similarity percentage; if it exceeds the
configured threshold (by default, cosine distance ≤ 0.45) it is flagged as
a probable match, but the exact percentage is always visible so the person
operating the system can make the final decision.