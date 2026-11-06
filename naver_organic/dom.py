"""페이지 안에서 한 번에 실행하는 DOM 읽기 스크립트(JS). 셀렉터는 config/organic_selectors.yaml 에서 받는다."""

_T = "const T=e=>((e&&(e.innerText||e.textContent))||'').trim().replace(/\\s+/g,' ');"

# 블록 목록: 컨테이너 직계 자식을 위에서부터 규칙에 맞춰 분류
BLOCKS_JS = _T + """
([containers, skipTags, rules, adMarkers, chipSels]) => {
  let root = null;
  for (const c of containers) { root = document.querySelector(c); if (root) break; }
  if (!root) return {root: null, blocks: []};
  // 셀렉터를 쉼표로 나눠 앞의 것부터 시도(순서 = 우선순위)
  const firstText = (el, sel) => { if (!sel) return ''; for (const one of sel.split(',')) { for (const e of el.querySelectorAll(one.trim())) { const t = T(e); if (t) return t; } } return ''; };
  const outermost = (arr) => arr.filter(it => !arr.some(o => o !== it && o.contains(it)));
  const out = [];
  for (const el of root.children) {
    if (skipTags.includes(el.tagName)) continue;
    if (el.getBoundingClientRect().height <= 0 && !el.querySelector('li, a')) continue;
    let rule = null;
    for (const r of rules) {
      if (r.self && !el.matches(r.self)) continue;
      if (r.has && !el.querySelector(r.has)) continue;
      rule = r; break;
    }
    if (!rule || rule.skip) continue;
    let title = rule.title_fixed || firstText(el, rule.title);
    let kind = rule.kind || '';
    if (rule.kind_attr) { const v = el.getAttribute(rule.kind_attr) || ''; kind = (rule.kind_map || {})[v] || rule.kind_default || kind || '기타'; }
    for (const [frag, k] of (rule.kind_by_title || [])) if (title.includes(frag)) kind = k;
    if (!kind) kind = '기타';
    if (kind === '기타' && !title) continue;
    const isAd = !!rule.ad || adMarkers.some(s => el.querySelector(s));
    const items = rule.item ? outermost([...el.querySelectorAll(rule.item)]) : [];
    const names = [];
    for (const it of items) {
      const nm = rule.item_name ? firstText(it, rule.item_name) : T(it).slice(0, 40);
      if (nm) names.push(nm.slice(0, 60));
    }
    const chips = [];
    const chipSelList = rule.chips ? [rule.chips] : (/연관|키워드|스마트블록/.test(kind) ? chipSels : []);
    for (const s of chipSelList) for (const a of el.querySelectorAll(s)) { const t = T(a); if (t && !chips.includes(t)) chips.push(t); }
    const css = (el.id ? '#' + el.id.slice(0, 24) + ' ' : '') + (el.className || '').toString().slice(0, 60);
    const last = out[out.length - 1];
    if (rule.merge && last && last.merge && last.kind === kind) { last.item_count += items.length; last.names.push(...names); continue; }
    out.push({title: title || '(제목 없음)', kind, css, is_ad: isAd, item_count: items.length, names, keywords: chips, merge: !!rule.merge});
  }
  return {root: root.tagName + '#' + root.id, blocks: out};
}
"""

# 플레이스 목록: root 안의 항목에서 업체명·광고 여부
PLACES_JS = _T + """
([rootSels, titleSel, itemSel, anchorSel, nameSel, adText, preferTitle]) => {
  let roots = [];
  for (const s of rootSels) { roots = [...document.querySelectorAll(s)]; if (roots.length) break; }
  if (!roots.length) return {root: null, items: []};
  let root = roots[0];
  if (roots.length > 1 && preferTitle) {
    const hit = roots.filter(r => T(r.querySelector(titleSel)).includes(preferTitle) && !T(r.querySelector(titleSel)).includes('프로그램'));
    if (hit.length) root = hit[0]; else root = roots[roots.length - 1];
  }
  const items = [];
  for (const li of root.querySelectorAll(itemSel)) {
    if (li.querySelector(itemSel)) continue;                 // 중첩된 바깥 li 는 건너뜀
    let a = null;
    for (const c of li.querySelectorAll(anchorSel)) { const t = T(c); if (t && !/더보기/.test(t)) { a = c; break; } }
    if (!a) continue;
    let name = '';
    for (const s of a.querySelectorAll(nameSel)) { const t = T(s); if (t) { name = t; break; } }
    if (!name) name = T(a);
    const ad = [...li.querySelectorAll('*')].some(e => e.children.length === 0 && T(e) === adText);
    const link = (a.getAttribute('href') || '').split('?')[0];
    items.push({name: name.slice(0, 80), is_ad: ad, link, text: T(li).slice(0, 120)});
  }
  return {root: T(root.querySelector(titleSel)) || root.id, items};
}
"""
