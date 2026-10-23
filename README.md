# PANS Agora

A student discussion forum and messaging platform built with **Python & Django 5.2 LTS**.

## Overview

- **Accounts & Authentication**: Username or email authentication, Argon2 password hashing, honeypot registration, email password reset, and account deletion.
- **Profiles & Avatars**: Display names, study fields, bios, and image uploading for avatars and banners with interactive cropping and WebP re-encoding.
- **Messaging & Group Chats**: Direct messaging between students, message requests for non-friends, and multi-user group chats with real-time live sync and media attachments.
- **Communities & Moderation**: Course and interest communities, thread creation, nested comment trees, voting, reporting, and moderation controls (pin, lock, ghost, ban).
- **Interface**: Responsive mobile layout with slide-over drawer, floating quick-chat dock, and zero external CDN script dependencies. Strict Content Security Policy compliant.

## Development Setup

```powershell
# 1. Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run database migrations and seed default communities
python manage.py migrate
python manage.py createcachetable
python manage.py seed_communities

# 4. Start the local server
python manage.py runserver
```

Open **http://127.0.0.1:8000/** in your browser.

## Running Tests

```powershell
python manage.py test
```
