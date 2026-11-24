# -*- mode: python ; coding: utf-8 -*-
"""meeting.spec — PyInstaller 설정 (단계 11, 2026-11-24).

빌드: build_exe.bat  (또는  uv run --with "pyinstaller>=6.10" pyinstaller meeting.spec --noconfirm)
결과: dist/meeting/meeting.exe  — 폴더째 복사해서 쓴다(onefile 로 묶지 않는다.
      onefile 은 켤 때마다 임시폴더에 풀어 느리고, 사내 백신이 자주 잡는다).

같이 넣는 것: 화면(templates·static)·프롬프트·스키마·시드 샘플.
넣지 않는 것: secret/.env(앱이 상위 폴더에서 찾는다)·데이터(<base>/meeting)·.claude/shi.json(PC 마다 다르다).
"""
from PyInstaller.utils.hooks import collect_submodules

datas = [
    ("app/templates", "app/templates"),
    ("app/static", "app/static"),
    ("app/llm/prompts", "app/llm/prompts"),
    ("schema", "schema"),
    ("data/samples", "data/samples"),
    ("design/tokens.css", "design"),
]

hiddenimports = (
    collect_submodules("app")
    + collect_submodules("config")
    + collect_submodules("modules")
    + ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
       "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]
)

a = Analysis(
    ["_launcher.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "pyinstaller"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="meeting",
          console=True, disable_windowed_traceback=False, icon=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="meeting")
