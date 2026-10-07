"""구글 Docs/Drive API 인증(설치형 앱 OAuth).

처음 한 번: GCP 콘솔에서 'OAuth 클라이언트 ID(데스크톱 앱)'를 만들어 client_secret.json을 .secrets/ 에 둔다.
그 뒤 `python -m naver_blog google-login` 을 실행하면 브라우저가 열리고, 토큰이 .secrets/token.json 에 저장된다.
클로드 코드 세션에서는 이 인증 없이 커넥터(Google Docs/Drive)로 같은 JSON·파일을 받아 workspace에 넣어도 된다.
"""
from __future__ import annotations

from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/documents.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def get_credentials(secrets_dir: Path | str = ".secrets", interactive: bool = True):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    secrets_dir = Path(secrets_dir)
    secrets_dir.mkdir(parents=True, exist_ok=True)
    token_path = secrets_dir / "token.json"
    client_path = secrets_dir / "client_secret.json"

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds
    if not interactive:
        raise RuntimeError("구글 토큰이 없거나 만료됐습니다. `python -m naver_blog google-login` 을 먼저 실행하세요.")
    if not client_path.exists():
        raise FileNotFoundError(
            f"{client_path} 가 없습니다. GCP 콘솔 → API 및 서비스 → 사용자 인증 정보 → OAuth 클라이언트 ID(데스크톱 앱) 를 만들어 JSON을 내려받아 두세요."
        )
    flow = InstalledAppFlow.from_client_secrets_file(str(client_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    return creds


def docs_service(creds):
    from googleapiclient.discovery import build

    return build("docs", "v1", credentials=creds, cache_discovery=False)


def drive_service(creds):
    from googleapiclient.discovery import build

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def fetch_document(doc_id: str, creds) -> dict:
    """탭 내용까지 포함해 문서 JSON을 받는다(커넥터 read_doc 결과와 같은 형태)."""
    svc = docs_service(creds)
    return svc.documents().get(documentId=doc_id, includeTabsContent=True).execute()
