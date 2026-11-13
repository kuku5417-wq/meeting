# 로컬 글꼴

시안(`design/mockups`)은 Google Fonts 를 불러온다. 사내망에서는 외부 CDN 이 막힐 수 있어서,
앱은 같은 글꼴을 이 폴더에서 직접 서빙한다(2026-10-20 결정).

| 파일 | 원본 (google/fonts 저장소 `ofl/`) | 굵기 | 라이선스 |
|---|---|---|---|
| `MeetingSansKR-*.woff2` | `ibmplexsanskr/IBMPlexSansKR-{Regular,Medium,SemiBold}.ttf` | 400·500·600 | `OFL-IBMPlexSansKR.txt` |
| `MeetingMono-*.woff2` | `ibmplexmono/IBMPlexMono-{Regular,Medium}.ttf` | 400·500 | `OFL-IBMPlexMono.txt` |

## 원본과 다른 점 (OFL 수정본)

- **서브셋**: 한글은 KS X 1001 상용 2,350자 + 이 저장소에 쓰인 모든 글자 + 라틴·기호만 남겼다
  (원본 약 18MB → 1.3MB). 목록에 없는 글자는 브라우저가 다음 글꼴(맑은 고딕)로 대신 그린다.
- **이름 변경**: IBM Plex 는 OFL 예약 이름 "Plex" 가 있어 수정본에 그 이름을 쓸 수 없다.
  그래서 name 테이블을 `Meeting Sans KR` / `Meeting Mono` 로 바꿨다.

## 다시 만들 때

글자가 빠져 보이면(새 문구에 드문 한글이 들어간 경우) 아래 순서로 다시 만든다.

```
python _font_chars.py . chars_kr.txt                      # 서브셋 글자 목록
uvx --from "fonttools[woff]" pyftsubset <원본.ttf> --text-file=chars_kr.txt --flavor=woff2 --layout-features="*" --output-file=<출력.woff2>
```

Mono 는 `--unicodes="U+0020-00FF,U+2000-206F,U+2190-21FF,U+2212"`.
Plex 계열은 서브셋 뒤에 name 테이블을 다시 `Meeting …` 으로 바꿔야 한다(fontTools `name` 테이블 ID 1·3·4·6·16·17).
