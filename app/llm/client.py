"""app/llm/client.py — 옛 이름 호환 래퍼. **정본은 `modules/llm_client.py`** 다.

단계 2-b(2026-11-24)에서 내용을 `modules/llm_client.py`(shi 전환 지점)로 옮겼다.
`from app.llm import client as llm` 로 부르는 곳이 5 파일(`routers/run`·`routers/write`·`services/answer`·
`services/extract`·`services/meeting`)이라 한꺼번에 고치지 않고 이름만 넘긴다.
**새 코드는 `modules.llm_client` 를 직접 쓴다.** 이 파일은 계획 단계 11 에서 지운다.

`PROVIDERS`(dict)·`settings`·`jsonschema` 는 **같은 객체**를 넘긴다 — 시험이 공급자를 끼워 넣거나
체인을 바꾸는 방식(`_smoke.t_llm`)이 그대로 동작해야 한다.
"""
from __future__ import annotations

from modules.llm_client import (  # noqa: F401 — 옛 이름 재노출
    LABELS,
    MOCK_DIR,
    MOCK_FILES,
    PROVIDERS,
    LLMResult,
    ProviderError,
    cfg,
    complete_json,
    jsonschema,
    parse_json_text,
    settings,
)
