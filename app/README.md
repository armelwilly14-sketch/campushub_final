# CampusHub Enhanced

## New features in this version
- Students and administrators can edit their profile and password from **Profile**.
- Student specialties and academic years can be typed and created when needed.
- Standard HND years are available: HND Year 1, HND Year 2, HND Year 3.
- Administrators can access the group Community and create posts/comments.
- Student-to-student private messaging remains available from student dashboards.
- Administrator-to-administrator chat is separated and protected.
- The administrator dashboard is divided into separate pages: Overview, Students, Teachers, Academic Content, Communication, Academic Setup, Administrator Chat and Settings.
- The app checks/creates the new messaging and community tables when it starts, which helps existing databases that were created from an older CampusHub version.

## Existing database
If you already have a CampusHub database, keep your data and run `upgrade.sql` once in phpMyAdmin. The application also performs a runtime schema check for the enhanced communication/community tables.

## Run
```bash
python -m pip install -r requirements.txt
python app.py
```
Then open `http://127.0.0.1:5000`.
