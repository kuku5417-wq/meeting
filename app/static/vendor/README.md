# vendor — 외부 라이브러리 사본

사내망은 CDN 이 막힐 수 있어 화면이 쓰는 라이브러리를 파일로 둔다(CLAUDE.md §3). 런타임 CDN 폴백은 없다.

| 파일 | 버전 | 출처 | sha256 | 라이선스 |
|---|---|---|---|---|
| `konva.min.js` | 9.3.6 | https://cdn.jsdelivr.net/npm/konva@9.3.6/konva.min.js (2026-10-20 받음) | `7fb114bc4ce6626366cc1e2ca091275079ac70ab6ce652105e5a42a5923e1b95` | MIT (`LICENSE-konva.txt`) |

버전을 올릴 때는 이 표와 `_smoke.py` 의 vendor 검사를 함께 고친다.
