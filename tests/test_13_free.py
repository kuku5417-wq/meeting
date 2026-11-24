"""결정 ⑦ 15-2~15-4 — 장마다 자유 편집(초안·자동 저장·검증·되돌리기) · 연결 개체 · 개체 추가 칩."""
import _smoke as sm


def test_free(client, run):
    run(sm.t_free, client)


def test_free_link(client, run):
    run(sm.t_free_link, client)


def test_free_scope(client, run):
    run(sm.t_free_scope, client)
