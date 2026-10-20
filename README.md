# PANS Agora

A warm, minimalist, release-ready student forum built with **Python & Django 5.2 LTS** — designed like a calm, student-friendly Reddit for PANS courses, study help, and campus life.

## Features

- **Accounts & Authentication**: Registration with honeypot protection, login via username or email, password change (`/settings/password/`), password reset via email, and account deletion.
- **Rich Student Profiles**: Custom display name, field & year of study, bio, custom **avatar** and **profile banner** (plus 5 curated gradient banner themes when no image is uploaded), with live client-side preview.
- **Friends System**: Send, accept, decline, cancel, and remove friend requests (`/friends/` and directly on `/u/<username>/`), with a live header badge for pending requests.
- **Communities & Threads**: Browse or create communities (`c/study-help`, `c/computer-science`, etc.), join/leave communities to curate a personal feed, create threads, and sort by **Hot**, **New**, or **Top**.
- **Nested Discussions & Voting**: Multi-level nested comment trees, OP badges, AJAX upvoting/downvoting (with full no-JS fallback), soft-deleted comments to preserve thread structure, user reports, and moderator tools (pin/lock/delete).
- **Hardened & Release-Ready**:
  - **Argon2** password hashing (`argon2-cffi`)
  - Uploaded avatars and banners are validated, resized, stripped of EXIF/GPS metadata, and re-encoded as clean **WebP** images via Pillow (`MAX_IMAGE_PIXELS` cap against decompression bombs)
  - Strict **Content-Security-Policy** (no `unsafe-inline`), `Permissions-Policy`, CSRF protection, open-redirect protection (`url_has_allowed_host_and_scheme`), HSTS, and fixed-window rate limiting on auth, posting, voting, and friend requests.

## Quickstart (Local Development)

```powershell
# 1. Create and activate virtual environment (already set up in .venv)
python -m venv .venv
.\.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run migrations, create cache table, and seed communities
python manage.py migrate
python manage.py createcachetable
python manage.py seed_communities

# 4. (Optional) Create an admin/moderator account
python manage.py createsuperuser

# 5. Start the development server
python manage.py runserver
```

Then open **http://127.0.0.1:8000/** in your browser.

## Running Tests & Security Audit

```powershell
python manage.py test
```
