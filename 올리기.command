#!/bin/bash
# 맥용: 더블클릭하면 필요한 것을 설치하고, 네이버 로그인 창을 띄운 뒤, 글을 입력해 임시저장합니다.
cd "$(dirname "$0")"
echo "=== 원더바레 네이버 블로그 올리기 ==="
if ! command -v python3 >/dev/null 2>&1; then
  echo "파이썬이 없습니다. https://www.python.org/downloads/ 에서 설치한 뒤 다시 더블클릭해 주세요."
  read -p "엔터를 누르면 닫힙니다." _; exit 1
fi
if [ ! -f ".설치완료" ]; then
  echo "[1/3] 필요한 프로그램을 설치합니다 (처음 한 번, 몇 분 걸립니다)..."
  python3 -m pip install -q --user -r requirements.txt || { echo "설치 실패"; read -p "엔터를 누르면 닫힙니다." _; exit 1; }
  python3 -m playwright install chromium || { echo "브라우저 설치 실패"; read -p "엔터를 누르면 닫힙니다." _; exit 1; }
  touch ".설치완료"
fi
if [ ! -d ".naver-profile" ]; then
  echo "[2/3] 네이버 로그인 창을 엽니다. 로그인하면 자동으로 이어집니다."
  python3 -m naver_blog login || { read -p "엔터를 누르면 닫힙니다." _; exit 1; }
fi
echo
echo "올릴 글 폴더:"; ls drafts
read -p "[3/3] 올릴 글 이름을 입력하세요 (예: 1주차): " TAB
python3 -m naver_blog post --tab "${TAB:-1주차}" --keep-open
read -p "끝났습니다. 엔터를 누르면 닫힙니다." _
