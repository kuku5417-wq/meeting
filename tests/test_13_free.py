"""결정 ⑦ 15-2 — 장마다 자유 편집(초안·자동 저장·검증·형태 바꾸기 되돌리기)."""
import _smoke as sm


def test_free(client, run):
    run(sm.t_free, client)
