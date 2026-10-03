# CampusHub Enhanced

## New features in this version
- Students and administrators can edit their profile and password from **Profile**.
- Student specialties and academic years can be typed and created when needed.
- Standard HND years are available: HND Year 1, HND Year 2, HND Year 3.
- Administrators can access the group Community and create posts/comments.
- Student-to-student private messaging remains available from student dashboards.
- Administrator-to-administrator chat is separated and protected.
- Students can submit school-fee bank transfer details and an optional receipt for finance-office verification.
- Parents can request a teacher chat about their linked child. An administrator must approve it; each approved session lasts three hours, then expires and requires a new request.
- Students and their linked parents can submit or update one private rating per teacher; only administrators can view individual ratings and averages.
- Parent accounts can use the linked student's learning, fees, community, teacher request/chat, rating, and reporting features through the parent portal.
- Administrators can create and edit PDF timetables by specialty and year, and schedule hall distributions with morning/evening sessions and custom times.
- An AI assistant is available only to parents, teachers, and administrators. Configure `OPENAI_API_KEY` (and optionally `AI_MODEL` / `AI_API_URL`) in the app environment to enable responses.
- Students register with their unique school matricule. Parents can create a linked account using the student's matricule, then log in with that matricule and their own password to view the student's academic page and results in read-only mode.
- The administrator dashboard is divided into separate pages: Overview, Students, Teachers, Academic Content, Communication, Academic Setup, Administrator Chat and Settings.
- The app checks/creates the new messaging and community tables when it starts, which helps existing databases that were created from an older CampusHub version.

## Existing database
If you already have a CampusHub database, keep your data and run `upgrade.sql` once in phpMyAdmin. The application also performs runtime schema checks for ratings, parent-teacher chat, hall sessions, fee settings, and enhanced communication/community tables.
Existing student records will have no matricule after migration; students must register a new matricule through the school's database/admin process before a parent can link to the account.

## Bank-transfer fee page
In **Admin → School Fees**, save the official bank account and create a fee schedule. Parents can then submit bank transfer references and optional receipts for their linked student; finance staff must confirm each submission before it counts as paid. Environment variables `FEE_BANK_NAME`, `FEE_ACCOUNT_NAME`, `FEE_ACCOUNT_NUMBER`, `FEE_BANK_BRANCH`, and `FEE_CURRENCY` remain supported as a fallback. This is a bank-transfer reporting and verification workflow, not automated card/bank processing; a payment gateway and merchant credentials are needed for direct online charging.

## AI assistant
Set `MISTRAL_API_KEY` in the app's local `.env` to enable Mistral (default model `mistral-small-latest`), or set `OPENAI_API_KEY` to use OpenAI (default model `gpt-4o-mini`). `AI_PROVIDER`, `AI_MODEL`, and `AI_API_URL` can override provider, model, and compatible endpoint. Keep API keys private: do not commit `.env` or paste keys in source code. Access is limited server-side to parent, teacher, and administrator roles; students are denied even if they open the route directly.

## Run
```bash
python -m pip install -r requirements.txt
python app.py
```
Then open `http://127.0.0.1:5000`.
