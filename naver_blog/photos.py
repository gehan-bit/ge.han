"""사진 가져오기·고르기.

- 드라이브 폴더(하위 폴더 포함)의 이미지 목록을 만들고 내려받는다(구글 API).
- 클로드 세션에서는 커넥터로 받은 파일을 workspace/<글>/photos/raw 에 넣어도 된다.
- used_photos.json 장부로 글마다 어떤 사진을 썼는지 기록해 같은 사진을 다시 쓰지 않게 한다.
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable

IMAGE_MIMES = ("image/jpeg", "image/png", "image/heic", "image/webp")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass
class DriveFile:
    id: str
    name: str
    mime: str
    size: int
    folder: str          # 상위 폴더 이름(지점 폴더 등)
    modified: str = ""
    width: int | None = None
    height: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- 드라이브 ----------
def list_folder(drive, folder_id: str, folder_name: str = "", recursive: bool = True) -> list[DriveFile]:
    files: list[DriveFile] = []
    page_token = None
    while True:
        resp = (
            drive.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, imageMediaMetadata(width,height))",
                pageSize=200,
                pageToken=page_token,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        for f in resp.get("files", []):
            if f["mimeType"] == "application/vnd.google-apps.folder":
                if recursive:
                    files += list_folder(drive, f["id"], f["name"], recursive)
            elif f["mimeType"] in IMAGE_MIMES:
                meta = f.get("imageMediaMetadata") or {}
                files.append(
                    DriveFile(f["id"], f["name"], f["mimeType"], int(f.get("size") or 0), folder_name,
                              f.get("modifiedTime", ""), meta.get("width"), meta.get("height"))
                )
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def download(drive, file_id: str, dest: Path) -> Path:
    from googleapiclient.http import MediaIoBaseDownload

    dest.parent.mkdir(parents=True, exist_ok=True)
    req = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req, chunksize=8 * 1024 * 1024)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest.write_bytes(buf.getvalue())
    return dest


def save_index(files: Iterable[DriveFile], path: Path | str) -> None:
    Path(path).write_text(json.dumps([f.to_dict() for f in files], ensure_ascii=False, indent=2), encoding="utf-8")


def load_index(path: Path | str) -> list[DriveFile]:
    return [DriveFile(**d) for d in json.loads(Path(path).read_text(encoding="utf-8"))]


# ---------- 사용 장부 ----------
class Ledger:
    """어떤 사진(드라이브 id 또는 파일명)을 어느 글에 썼는지 기록."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.data: dict[str, list[str]] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))

    def used_in(self, key: str) -> list[str]:
        return self.data.get(key, [])

    def mark(self, keys: Iterable[str], post_slug: str) -> None:
        for k in keys:
            lst = self.data.setdefault(k, [])
            if post_slug not in lst:
                lst.append(post_slug)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")


def pick(files: list[DriveFile], n: int, ledger: Ledger | None, prefer_folders: Iterable[str] = (), exclude_folders: Iterable[str] = ()) -> list[DriveFile]:
    """아직 안 쓴 사진을 우선으로 n장 고른다. prefer_folders 에 든 폴더(지점) 사진을 먼저 본다."""
    prefer = [p for p in prefer_folders if p]
    exclude = [e for e in exclude_folders if e]
    cands = [f for f in files if not any(e in f.folder for e in exclude)]

    def key(f: DriveFile):
        used = len(ledger.used_in(f.id)) + len(ledger.used_in(f.name)) if ledger else 0
        pref = 0 if any(p in f.folder for p in prefer) else 1
        return (used, pref, f.name)

    return sorted(cands, key=key)[:n]


def local_images(folder: Path | str) -> list[Path]:
    folder = Path(folder)
    if not folder.exists():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTS and not p.name.startswith("."))
