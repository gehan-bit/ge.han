# 원더바레 네이버 블로그 자동화 — 작업 안내

이 저장소는 구글 문서에 쓰인 원고를 네이버 블로그 글로 옮기는 파이프라인이다.
새 주제(다른 주차 탭, 다른 문서)를 요청받으면 아래 순서대로 진행한다. 코드 설명은 `README.md`.

## 원칙(요약) — 전문은 작성 지침 문서
- 작성 지침: https://claude.ai/artifact/8Ew8N8tTFfkmKcQ5QroT25 (Claude Docs. `Claude_Docs` 커넥터 `read` 로 읽는다. 웹 페치 금지)
- 원고 문서: https://docs.google.com/document/d/1bmL5foind18EKd5DyOkK2eWb9rzmNacNwyfwr9_odsg (탭 = 주차)
- 사진 폴더: https://drive.google.com/drive/folders/11_t6Pn9c1UelgVS_xXet4fdzxt0y6EE1 (하위 `원더바레_시설사진/지점별`)
- **글은 원고 그대로**. 단어를 바꾸지 않는다. 줄바꿈(한 줄 25~30자), 구분선, ※ 회색 글씨, 링크 카드, 태그 수만 손본다.
- 세로 사진은 5:4로 자르되 얼굴은 가운데 또는 위에서 1/3, 얼굴·로고가 잘리면 안 된다. 가로 사진은 원본 비율.
- 네이버에는 **임시저장까지만**. 발행(`--publish`)은 사용자가 확인하고 직접 지시했을 때만.
- 사용자 PC에서만 네이버 로그인·게시가 된다(클라우드 세션은 네이버 로그인 불가). 세션에서는 원고·사진 준비까지 하고, 게시 명령은 사용자에게 안내한다.

## 세션에서 글 한 편 준비하는 순서
1. 원고 JSON 받기: `Google_Docs.read_doc(documentId=…)` 결과(JSON)를 `workspace/doc.json` 에 저장한다
   (결과가 커서 파일로 저장되면 그 파일을 복사). 커넥터 결과의 `content` 래퍼는 파서가 알아서 벗긴다.
2. `python -m naver_blog tabs` 로 탭 이름 확인 → `python -m naver_blog build --tab <탭이름>`
   → `workspace/<탭>/post.json`, `post.txt`, `preview.html` 생성. "확인할 점" 목록을 읽는다.
3. 사진 고르기: `Google_Drive.search_files(query="parentId = '<폴더id>'")` 로 목록을 보고
   원고의 사진 자리 수만큼(보통 3~6장) 고른다. `workspace/used_photos.json` 에 이미 쓴 사진은 피한다.
   사진은 `Google_Drive.download_file_content` 로 받아 base64 디코드 → `workspace/<탭>/photos/raw/` 에 원래 파일명으로 저장.
   (큰 파일은 결과가 파일로 저장된다. 디코드 후 그 임시 파일은 지운다.)
   선택 순서는 `workspace/<탭>/photos.yaml` 의 `order` 에 적는다(`config/photos.example.yaml` 참고).
4. `python -m naver_blog crop --tab <탭>` → `photos/out/*.jpg`, `photos/review.jpg`.
   **review.jpg 를 반드시 눈으로 본다.** 얼굴·로고(벽 글자, 공·매트의 BARRE 로고 등)가 잘렸거나 ⚠ 표시가 있으면
   `photos.yaml` 의 `overrides` 에 `protect`/`top`/`anchor` 를 적고 crop 을 다시 돌린다.
5. `python -m naver_blog build --tab <탭>` 을 다시 실행해 사진을 자리에 넣고 `preview.html` 을 확인한다
   (가능하면 스크린샷을 찍어 본다). `used_photos.json` 에 쓴 사진을 기록한다.
6. 사용자에게 안내: 로컬에서 `python -m naver_blog login`(최초 1회) → `python -m naver_blog post --tab <탭>`
   → 네이버에서 임시저장 글 확인 → 태그·카테고리·장소 넣고 발행.
7. `workspace/` 는 커밋하지 않는다(.gitignore). 코드·설정 변경만 커밋한다.

## 셀렉터가 깨졌을 때
`post` 가 "요소를 찾지 못함" 경고를 내면 `config/selectors.yaml` 만 고친다. 네이버 스마트에디터 ONE 화면에서
해당 버튼의 class 를 확인해 후보 목록 맨 앞에 추가한다. 코드 수정은 필요 없다.

## 테스트
`python -m pytest -q tests` (파서·줄바꿈·크롭 계산). 포스터는 `tests/mock/editor.html` 로 동작 확인:
`python -m naver_blog post --tab <탭> --headless --editor-url file://$PWD/tests/mock/editor.html`
