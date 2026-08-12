import sqlite3
import os

conn = sqlite3.connect("/home/AzzaPrivetKaka/people.db")
cursor = conn.cursor()
count = 0

for f in os.listdir("/home/AzzaPrivetKaka/"):
    if f.startswith("data") and f.endswith(".txt"):
        print("Читаю: " + f)
        for line in open("/home/AzzaPrivetKaka/" + f, encoding="utf-8", errors="ignore"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) >= 3:
                lastname = parts[1] if len(parts) > 1 else ""
                firstname = parts[2] if len(parts) > 2 else ""
                middlename = parts[3] if len(parts) > 3 else ""
                phone = parts[4] if len(parts) > 4 else ""
                city = parts[-1] if len(parts) > 1 else ""
                full_name = (lastname + " " + firstname + " " + middlename).strip()
                if full_name:
                    cursor.execute("INSERT INTO people (full_name, username, platform, phone, email, city, notes, added_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (full_name, "", "", phone, "", city, "", "admin"))
                    count += 1

conn.commit()
conn.close()
print("Добавлено " + str(count) + " записей.")

