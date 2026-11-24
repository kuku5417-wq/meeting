"""path_config.py — 옛 이름 호환 래퍼. **정본은 `config/paths.py`** 다.

단계 2-a(2026-11-24)에서 내용을 `config/paths.py`(shi 전환 지점)로 옮겼다.
`path_config` 를 import 하는 곳이 13 파일(`app/` 8 · `scripts/` 3 · `check_env.py` · `_smoke.py` 5군데)이라
한꺼번에 고치지 않고 이름만 넘긴다. **새 코드는 `config.paths` 를 직접 쓴다.**
이 파일은 계획 단계 11(실행 파일·정리)에서 지운다.

여기에는 로직을 두지 않는다 — 고칠 것은 `config/paths.py` 에서 고친다.
"""
from __future__ import annotations

from config.paths import (  # noqa: F401 — 옛 이름 재노출
    BASE_DIR,
    CODE_DIR,
    DATA_LOCAL,
    DATA_SUBDIR,
    DB_NAME,
    SECRET_ENV,
    central_parquet,
    data_dir_choice,
    db_path,
    get_backup_dir,
    get_central_parquet_dir,
    get_data_dir,
    get_env_label,
    get_export_dir,
    get_import_dir,
    get_photo_dir,
    invalidate_cache,
    is_internal,
    is_network_path,
    read_secret,
)
