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
# 글은 번호로 고른다(터미널 한글 입력 오류를 피하기 위해)
POSTS=()
for d in drafts/*/ workspace/*/; do
  [ -f "$d/post.json" ] && POSTS+=("$(basename "$d")")
done
if [ ${#POSTS[@]} -eq 0 ]; then
  echo "올릴 글이 없습니다 (drafts 폴더가 비어 있음)."; read -p "엔터를 누르면 닫힙니다." _; exit 1
fi
echo "[3/3] 올릴 글을 번호로 고르세요:"
i=1; for p in "${POSTS[@]}"; do echo "  $i) $p"; i=$((i+1)); done
read -p "번호 입력 (그냥 엔터 = 1): " NUM
NUM=${NUM:-1}
TAB="${POSTS[$((NUM-1))]}"
if [ -z "$TAB" ]; then echo "잘못된 번호입니다."; read -p "엔터를 누르면 닫힙니다." _; exit 1; fi
echo "→ '$TAB' 을(를) 올립니다. 브라우저를 건드리지 말고 기다려 주세요."
python3 -m naver_blog post --tab "$TAB" --keep-open
read -p "끝났습니다. 엔터를 누르면 닫힙니다." _
