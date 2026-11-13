"""글꼴 서브셋 문자 목록 — KS X 1001 한글 2350자 + 저장소에 쓰인 모든 한글·기호 + 라틴."""
import sys
from pathlib import Path
repo, out = Path(sys.argv[1]), Path(sys.argv[2])
chars = set()
for hi in range(0xB0, 0xC9):
    for lo in range(0xA1, 0xFF):
        try:
            chars.add(bytes([hi, lo]).decode('euc-kr'))
        except UnicodeDecodeError:
            pass
for p in repo.rglob('*'):
    if p.is_file() and '.git' not in p.parts and p.suffix in {'.md', '.html', '.csv', '.json', '.txt', '.py', '.css'}:
        chars |= set(p.read_text(encoding='utf-8'))
ranges = [(0x20, 0xFF), (0x2000, 0x206F), (0x2190, 0x21FF), (0x2200, 0x22FF), (0x2460, 0x24FF),
          (0x2500, 0x25FF), (0x3000, 0x303F), (0x3131, 0x318E), (0xFF01, 0xFF5E)]
for a, b in ranges:
    chars |= {chr(c) for c in range(a, b + 1)}
chars = {c for c in chars if ord(c) >= 0x20}
out.write_text(''.join(sorted(chars)), encoding='utf-8')
print(len(chars), 'chars;', sum(1 for c in chars if 0xAC00 <= ord(c) <= 0xD7A3), 'hangul syllables')
