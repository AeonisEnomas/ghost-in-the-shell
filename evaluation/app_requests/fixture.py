"""The folder every app-test request is run in.

A small, made-up home directory with a project folder inside it: notes, logs,
spreadsheets, Python files, photos, archives. Every file has fixed content,
and its age is set relative to the moment the folder is built, so "changed in
the last 24 hours" means the same files on any day and any machine.
"""

import gzip
import hashlib
import io
import os
import tarfile
from pathlib import Path

HOME = "/home/sam"
CWD = f"{HOME}/project"

HOUR, DAY = 3600, 86400
DEFAULT_AGE = 90 * DAY
# Ages that differ from the default. Recent files are spaced apart so "newest" has one answer.
AGES = {
    "project/notes.txt": 110 * 60,
    "project/src/main.py": 130 * 60,
    "project/logs/today.log": 150 * 60,
    "project/draft.tmp": 3 * HOUR,
    "project/data/sales_2024.csv": 4 * HOUR,
    "project/README.md": 3 * DAY,
    "project/budget.csv": 3 * DAY,
    "project/tests/test_main.py": 3 * DAY,
    "project/error.log": 400 * DAY,
    "project/old_notes.bak": 400 * DAY,
    "project/logs/jan.log": 400 * DAY,
    "project/logs/feb.log": 380 * DAY,
    "project/archive/old_project.tar.gz": 400 * DAY,
    "project/archive/notes_2022.txt.gz": 400 * DAY,
}
EXECUTABLE = {"project/deploy.sh", "project/build/a.out"}
EMPTY_DIRS = ["project/empty_dir", "Pictures"]


def blob(name: str, size: int, magic: bytes = b"") -> bytes:
    """Fixed pseudo-random bytes, standing in for a photo, video or document."""
    out, counter = bytearray(magic), 0
    while len(out) < size:
        out += hashlib.sha256(f"{name}:{counter}".encode()).digest()
        counter += 1
    return bytes(out[:size])


def lines(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def access_log() -> str:
    hits = [
        ("10.0.0.5", "/index.html", 200, 2048), ("10.0.0.8", "/about", 200, 1024),
        ("10.0.0.5", "/api/items", 200, 4096), ("192.168.1.20", "/missing", 404, 512),
        ("10.0.0.5", "/login", 200, 733), ("172.16.0.3", "/api/items", 500, 918),
        ("10.0.0.12", "/index.html", 200, 2048), ("10.0.0.5", "/about", 200, 1024),
        ("10.0.0.8", "/old-page", 404, 512), ("10.0.0.5", "/api/items", 500, 918),
        ("192.168.1.20", "/index.html", 200, 2048), ("10.0.0.8", "/login", 200, 733),
        ("10.0.0.5", "/favicon.ico", 404, 512), ("172.16.0.3", "/index.html", 200, 2048),
        ("10.0.0.12", "/api/items", 200, 4096), ("10.0.0.5", "/index.html", 200, 2048),
        ("10.0.0.8", "/api/items", 500, 918), ("192.168.1.20", "/about", 200, 1024),
        ("10.0.0.5", "/docs", 404, 512), ("10.0.0.12", "/login", 200, 733),
        ("172.16.0.3", "/about", 200, 1024), ("10.0.0.8", "/index.html", 200, 2048),
        ("192.168.1.20", "/api/items", 500, 918), ("10.0.0.5", "/robots.txt", 404, 512),
    ]
    return lines(*(
        f'{ip} - - [12/Oct/2026:10:{15 + i}:{(i * 7) % 60:02d} +0000] "GET {path} HTTP/1.1" {status} {size}'
        for i, (ip, path, status, size) in enumerate(hits)
    ))


def app_log() -> str:
    events = [
        ("INFO", "Server started on port 8080"), ("INFO", "Loaded 14 routes"),
        ("INFO", "Connected to the database"), ("WARNING", "Cache is almost full"),
        ("INFO", "Request handled in 12 ms"), ("ERROR", "Database connection lost"),
        ("INFO", "Reconnected to the database"), ("INFO", "Request handled in 9 ms"),
        ("WARNING", "Slow query took 2 seconds"), ("INFO", "Request handled in 15 ms"),
        ("ERROR", "Timeout while reading upload"), ("INFO", "Request handled in 11 ms"),
        ("INFO", "User amira signed in"), ("INFO", "Request handled in 8 ms"),
        ("ERROR", "Could not write to disk"), ("WARNING", "Disk space below 10 percent"),
        ("INFO", "Old sessions cleaned up"), ("INFO", "Request handled in 10 ms"),
        ("INFO", "User tomas signed in"), ("ERROR", "Payment service did not answer"),
        ("INFO", "Request handled in 13 ms"), ("INFO", "Nightly report sent"),
        ("WARNING", "Certificate expires in 20 days"), ("INFO", "Request handled in 7 ms"),
        ("ERROR", "Invalid token for user tomas"), ("INFO", "User tomas signed out"),
        ("INFO", "Request handled in 14 ms"), ("ERROR", "Mail server refused the message"),
        ("INFO", "Backup finished"), ("INFO", "Server shutting down"),
    ]
    return lines(*(f"2026-10-12 09:{i:02d}:{(i * 13) % 60:02d} {level} {text}"
                   for i, (level, text) in enumerate(events)))


def tar_gz(members: dict[str, str]) -> bytes:
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name, text in members.items():
            data = text.encode()
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(data), 1_600_000_000, 0o644
            tar.addfile(info, io.BytesIO(data))
    return gzip.compress(raw.getvalue(), mtime=0)


NOTES = [
    "Shopping list is in todo.txt",
    "TODO: call the bank about the card",
    "Meeting with Priya at 3pm on Friday",
    "todo: renew passport before June",
    "Ideas for the garden: tomatoes, basil",
    "The wifi code is on the fridge",
    "Book train tickets for the weekend",
    "TODO: send the report to Omar",
    "Remember to water the plants",
    "Dentist appointment next month",
]

FILES: dict[str, str | bytes] = {
    # --- top of the project folder
    "project/README.md": "# Project\n\nA small demo project.\n\n## Usage\n\nRun `python run.py`.\n\n"
                         "See docs/guide.md for details.\n",
    "project/notes.txt": lines(*NOTES),
    "project/old_notes.bak": lines(NOTES[0], NOTES[2], NOTES[4], NOTES[5], "Call the plumber", NOTES[8]),
    "project/todo.txt": lines("milk", "eggs", "bread", "milk", "apples", "coffee", "eggs", "rice"),
    "project/numbers.txt": lines("42", "7", "19", "103", "5", "88", "61", "250", "13", "34"),
    "project/budget.csv": lines(
        "name,department,amount", "Aisha,engineering,5200", "Bruno,sales,3100", "Chen,marketing,2750",
        "Dalia,sales,3400", "Emeka,engineering,4800", "Farah,support,2300", "Goran,sales,2950",
        "Hana,marketing,2600", "Imran,support,2450", "Julia,engineering,5100"),
    "project/contacts.csv": lines(
        "name,email,city", "Aisha,aisha@example.com,Lagos", "Bruno,bruno@example.org,Porto",
        "Chen,chen@example.net,Taipei", "Dalia,dalia@example.com,Cairo",
        "Emeka,emeka@example.org,Abuja", "Farah,farah@example.net,Karachi"),
    "project/access.log": access_log(),
    "project/app.log": app_log(),
    "project/error.log": lines(
        "2025-09-01 02:00:11 ERROR Disk full", "2025-09-01 02:00:12 ERROR Backup aborted",
        "2025-09-02 02:00:10 INFO Backup finished", "2025-09-03 02:00:10 INFO Backup finished",
        "2025-09-04 02:00:13 ERROR Backup aborted"),
    "project/backup.sh": "#!/bin/bash\ntar -czf backup.tar.gz data\n",
    "project/deploy.sh": '#!/bin/bash\necho "Deploying version 1.4.2"\necho "Done"\n',
    "project/run.py": "import subprocess\n\nsubprocess.run(['python', 'src/main.py'])\n",
    "project/.env": "DB_PASSWORD=change-me\nDEBUG=false\n",
    "project/.gitignore": "__pycache__/\n*.tmp\nbuild/\n",
    "project/config.bak": "DEBUG = True\n",
    "project/draft.tmp": "First draft of the newsletter.\n",
    "project/cache.tmp": "cached=1\n",
    "project/empty.txt": "",
    "project/placeholder.dat": "",
    "project/my file.txt": "A file with a space in its name.\n",
    "project/report.pdf": blob("report.pdf", 180_000, b"%PDF-1.4\n"),
    # --- source code
    "project/src/__init__.py": "",
    "project/src/main.py": (
        "# Entry point for the demo project\nimport os\nimport sys\n\nfrom utils import greet\n\n\n"
        "def main():\n    # TODO: handle errors\n"
        '    name = sys.argv[1] if len(sys.argv) > 1 else "world"\n'
        "    print(greet(name))\n    print(os.getcwd())\n\n\n"
        'if __name__ == "__main__":\n    main()\n'),
    "project/src/utils.py": (
        'def greet(name):\n    return f"Hello, {name}!"\n\n\n'
        "def shout(text):\n    return text.upper()\n"),
    "project/src/config.py": (
        "import os\n\nDEBUG = False\n"
        'database_url = os.environ.get("DATABASE_URL", "sqlite:///demo.db")\n'
        'password = os.environ.get("DB_PASSWORD", "")\n'),
    "project/src/helpers/__init__.py": "",
    "project/src/helpers/strings.py": (
        'def slugify(text):\n    return text.lower().replace(" ", "-")\n\n\n'
        "def title_case(text):\n    return text.title()\n"),
    "project/tests/test_main.py": "import main\n\n\ndef test_main_runs():\n    main.main()\n",
    "project/tests/test_utils.py": (
        "import utils\n\n\ndef test_greet():\n"
        '    assert utils.greet("Ada") == "Hello, Ada!"\n'),
    # --- documents and media
    "project/docs/guide.md": "# Guide\n\nSet the database password in the .env file.\n\nThen run the app.\n",
    "project/docs/api.md": "# API\n\nGET /api/items returns the list of items.\n",
    "project/docs/guide.md.bak": "# Guide\n\nOld version of the guide.\n",
    "project/docs/images/logo.png": blob("logo.png", 2_000, b"\x89PNG\r\n\x1a\n"),
    "project/docs/images/diagram.png": blob("diagram.png", 300_000, b"\x89PNG\r\n\x1a\n"),
    "project/photos/beach.jpg": blob("beach.jpg", 40_000, b"\xff\xd8\xff\xe0"),
    "project/photos/sunset.jpg": blob("sunset.jpg", 55_000, b"\xff\xd8\xff\xe0"),
    "project/photos/IMG_001.JPG": blob("IMG_001.JPG", 70_000, b"\xff\xd8\xff\xe0"),
    "project/photos/portrait.png": blob("portrait.png", 30_000, b"\x89PNG\r\n\x1a\n"),
    # --- data
    "project/data/sales_2023.csv": lines("month,units", "jan,120", "feb,135", "mar,150"),
    "project/data/sales_2024.csv": lines("month,units", "jan,140", "feb,155", "mar,171"),
    "project/data/raw/dump.json": "".join(
        f'{{"id": {i}, "label": "item-{i}", "value": {i * 37 % 1000}}}\n' for i in range(28_000)),
    "project/data/raw/video.mp4": blob("video.mp4", 5_000_000),
    # --- logs, archives, leftovers
    "project/logs/jan.log": lines("2026-01-05 INFO Backup finished", "2026-01-19 INFO Backup finished"),
    "project/logs/feb.log": lines("2026-02-02 INFO Backup finished", "2026-02-16 INFO Backup finished"),
    "project/logs/mar.log": lines("2026-03-02 INFO Backup finished", "2026-03-16 WARNING Backup was slow"),
    "project/logs/today.log": lines(
        "08:00:01 INFO Service started", "08:15:42 INFO Sync finished", "09:02:10 ERROR Sync failed",
        "09:05:33 INFO Sync retried", "09:05:59 INFO Sync finished"),
    "project/archive/old_project.tar.gz": tar_gz({
        "old_project/README.txt": "An older project, kept for reference.\n",
        "old_project/main.c": "int main(void) { return 0; }\n"}),
    "project/archive/notes_2022.txt.gz": gzip.compress(b"Notes from 2022.\nNothing urgent.\n", mtime=0),
    "project/build/a.out": blob("a.out", 8_000, b"\x7fELF"),
    "project/build/output.o": blob("output.o", 4_000, b"\x7fELF"),
    "project/tmp/scratch.txt": "scratch\n",
    "project/tmp/old_output.txt": "result: 42\n",
    # --- the rest of the home folder
    "Documents/resume.docx": blob("resume.docx", 20_000, b"PK\x03\x04"),
    "Documents/taxes/2023.pdf": blob("2023.pdf", 60_000, b"%PDF-1.4\n"),
    "Downloads/installer.deb": blob("installer.deb", 50_000),
    "Downloads/song.mp3": blob("song.mp3", 90_000, b"ID3"),
    "Downloads/photo.jpg": blob("photo.jpg", 35_000, b"\xff\xd8\xff\xe0"),
}


def build(root: Path, now: float) -> None:
    """Create the folder under `root` (which becomes "/" in the sandbox)."""
    home = root / HOME.lstrip("/")
    for rel, content in FILES.items():
        path = home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        path.chmod(0o755 if rel in EXECUTABLE else 0o644)
    for rel in EMPTY_DIRS:
        (home / rel).mkdir(parents=True)
    (root / "tmp").mkdir(mode=0o777)

    # Ages last, deepest paths first, because creating a file changes its folder's time.
    for path in sorted(home.rglob("*"), key=lambda p: -len(p.parts)):
        age = AGES.get(str(path.relative_to(home)), DEFAULT_AGE)
        os.utime(path, (now - age, now - age))
    for folder in (home, home.parent):
        os.utime(folder, (now - DEFAULT_AGE, now - DEFAULT_AGE))
