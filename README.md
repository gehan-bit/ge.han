# 원더바레 네이버 블로그 자동화

구글 문서에 쓰여 있는 원고를 **네이버 블로그 작성 원칙**에 맞춰 옮기고, 드라이브 사진을 **5:4로 다듬어** 넣은 뒤,
네이버 스마트에디터에 자동으로 입력해 **임시저장**까지 해 주는 도구입니다. 발행은 사람이 확인하고 누릅니다.

```
구글 문서(탭=주차) ──→ post.json / preview.html ──┐
드라이브 사진 ──→ 5:4 크롭(얼굴·로고 보호) ──→ review.jpg ──┴─→ 스마트에디터 입력 → 임시저장 → (확인 후) 발행
```

- 원고: [고은] 원더바레 오카방 포스팅 (구글 문서, 탭마다 한 편)
- 사진: 원더바레 아카이브 드라이브 폴더(지점별 `원더바레_시설사진` 포함)
- 지침: 원더바레 행사 블로그 작성 원칙｜네이버 (Claude Docs)

## 무엇을 자동으로 하나

| 단계 | 하는 일 | 지침 근거 |
| --- | --- | --- |
| 원고 읽기 | `[제목]`, `[태그]`, 소제목, 본문, ※ 문구, 표, 사진 자리를 구조로 읽음 | 글은 원고 그대로 |
| 서식 | 긴 줄만 뜻이 나뉘는 곳(문장 끝 > 쉼표 > 띄어쓰기)에서 25~30자로 줄바꿈. 따옴표·괄호 안은 자르지 않음 | 한 줄 25~30자 |
| 구조 | 소제목 앞 구분선, 소제목 큰 글씨·굵게, ※ 문구 작은 회색, 맨 아래 공식 채널 링크 카드, 공감·댓글 한 줄 | 줄바꿈과 서식 / 링크와 태그 |
| 태그 | 원고 태그 유지, 10개 미만이면 보충, 15개 초과는 자름 | 태그 10~15개 |
| 사진 | 가로 사진은 원본 비율. 세로 사진은 5:4로, 얼굴이 위에서 1/3(또는 가운데)에 오게. 얼굴·로고(보호 영역)는 잘리지 않게 | 사진 비율 |
| 확인 | `preview.html`(모바일 느낌 미리보기), `review.jpg`(크롭 전후 비교), 체크리스트 중 기계로 볼 수 있는 항목 | 발행 전 체크리스트 |
| 게시 | 스마트에디터 ONE에 제목·본문·사진 입력 후 **임시저장**. `--publish` 를 줄 때만 발행 | 임시저장 후 확인 |

자동으로 **하지 않는** 것: 문장 고치기, 장소(지도) 첨부, 카테고리 선택(발행 때), 사진 속 사람의 게시 동의 확인.

## 설치 (처음 한 번)

Python 3.11 이상.

```bash
pip install -r requirements.txt
python -m playwright install chromium      # 네이버 입력용 브라우저
```

구글 문서·드라이브를 스크립트가 직접 읽게 하려면(선택):
1. [Google Cloud 콘솔](https://console.cloud.google.com/) → API 및 서비스 → **Google Docs API, Google Drive API** 사용 설정
2. 사용자 인증 정보 → OAuth 클라이언트 ID → **데스크톱 앱** → JSON 다운로드 → `.secrets/client_secret.json` 으로 저장
3. `python -m naver_blog google-login` (브라우저가 열리면 허용)

클로드 코드 세션에서 작업할 때는 이 인증 없이 커넥터로 원고와 사진을 받아 `workspace/` 에 넣습니다(`CLAUDE.md` 참고).

## 글 한 편 만들기

```bash
# 1) 원고 받기 (구글 API를 쓸 때. 세션에서는 커넥터로 받아 workspace/doc.json 에 저장)
python -m naver_blog fetch-doc
python -m naver_blog tabs                      # 탭(주차) 목록

# 2) 사진 고르고 받기 — 아직 안 쓴 사진을 사진 자리 수만큼
python -m naver_blog photos pull --tab 1주차
#    또는 workspace/1주차/photos/raw/ 에 직접 복사

# 3) 사진 다듬기 → workspace/1주차/photos/review.jpg 를 꼭 눈으로 확인
python -m naver_blog crop --tab 1주차

# 4) 원고 → 네이버 형식 + 미리보기
python -m naver_blog build --tab 1주차         # workspace/1주차/preview.html, post.txt

# (3+4 한 번에) python -m naver_blog run --tab 1주차

# 5) 네이버 로그인(최초 1회, 창이 열립니다) → 입력 + 임시저장
python -m naver_blog login
python -m naver_blog post --tab 1주차          # --dry-run: 할 일 목록만 / --publish: 발행까지
```

끝나면 `workspace/1주차/editor_result.png` 에 에디터 화면이 저장되고, 발행 때 넣을 태그 목록이 출력됩니다.
네이버에서 임시저장 글을 열어 확인하고 **카테고리·태그·장소**를 넣고 발행하세요.

## 사진이 마음에 안 들 때 — `workspace/<글>/photos.yaml`

```yaml
order:                       # 사진 자리 순서(파일명)
  - "DSC05423.jpg"
  - "DSC00215 복사본.jpg"
overrides:
  "DSC05642.jpg":
    protect: [[0.2, 0.0, 0.4, 0.2]]   # 잘리면 안 되는 영역 [x, y, w, h] (0~1 비율) — 로고, 글자 등
    anchor: "center"                   # 얼굴 위치: third(기본) | center
  "리츄엣1.jpg":
    top: 0.10                          # 자를 위치를 직접 지정
  "다른사진.jpg":
    focus_y: 0.35                      # 얼굴 대신 이 지점을 기준으로
    skip_crop: true                    # 세로 사진이지만 자르지 않음
```

`review.jpg` 에서 초록 상자 = 검출한 얼굴, 파랑 = 보호 영역, 빨강 = 자르는 범위(가로선 = 위에서 1/3). ⚠ 는 자동 판단이 불확실한 사진입니다.

## 설정 — `config/settings.yaml`

블로그 아이디, 원고 문서·사진 폴더 ID, 줄 길이, 소제목·※ 글자 크기, 맨 아래 링크, 태그 보충 후보 등.
제목에 "아카데미/강사/교육/채용/큐잉/수업"이 들어가면 홈페이지 대신 아카데미 사이트 링크를 넣습니다.

## 네이버 화면이 바뀌어 입력이 안 될 때 — `config/selectors.yaml`

`post` 가 "요소를 찾지 못함" 경고를 내면 스마트에디터에서 해당 버튼의 class 를 확인해 그 항목 목록 맨 앞에 추가하면 됩니다.
코드는 고치지 않아도 됩니다. 로그인은 사람이 직접 하며 브라우저 세션은 `.naver-profile/` 에 남습니다(저장소에 올라가지 않음).

## 폴더

```
naver_blog/      파이프라인 코드 (gdoc 파서, naver_format 서식, crop 사진, poster 에디터 입력, cli)
config/          settings.yaml(설정) · selectors.yaml(에디터 셀렉터) · photos.example.yaml
models/          얼굴 검출 모델 (OpenCV YuNet, Apache-2.0)
tests/           단위 테스트, 모의 에디터(tests/mock/editor.html)
workspace/       작업물(원고 JSON, 사진, 미리보기) — git 에 올리지 않음
```

테스트: `python -m pytest -q tests`

## 알아둘 점

- 네이버 블로그는 글쓰기 API가 없어 브라우저 자동 입력을 씁니다. 네이버 로그인은 사용자 PC에서 직접 해야 하며, 클라우드 세션에서는 할 수 없습니다.
- 스마트에디터 입력은 모의 에디터로 동작을 확인했지만, 실제 네이버 화면에서는 셀렉터 조정이 필요할 수 있습니다. 첫 실행은 `--keep-open` 으로 화면을 보면서 하세요.
- 표는 스마트에디터 표 대신 글줄(`항목 | 내용`)로 들어갑니다. 필요하면 에디터에서 표로 바꿔 주세요.
- 가공한 사진은 EXIF(촬영 정보·위치)를 지우고 가로 최대 1600px JPEG로 저장합니다.
