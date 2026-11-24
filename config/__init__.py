"""config/ — shi 전환 지점 둘(`paths.py` 경로, `settings.py` 망·비밀·프록시).

파일 이름이 `config.py` 가 아니라 **패키지**인 이유: 공통지침 — `import config` 가 형제 앱의
`config/` 패키지와 충돌한다. 이 앱은 자기 폴더를 `sys.path` 맨 앞에 두므로(`app/settings.py`,
`_smoke.py`) 여기 것이 먼저 잡힌다.
"""
