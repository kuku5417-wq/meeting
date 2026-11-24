"""결정 ⑦ 15-2~15-7 — 장마다 자유 편집(초안·자동 저장·검증·되돌리기) · 연결 개체 · 개체 추가 칩 · 파생·합치기 · 사실로 채택·흐름 · 한 명씩 편집."""
import _smoke as sm


def test_free(client, run):
    run(sm.t_free, client)


def test_free_link(client, run):
    run(sm.t_free_link, client)


def test_free_scope(client, run):
    run(sm.t_free_scope, client)


def test_free_merge(client, run):
    run(sm.t_free_merge, client)


def test_free_adopt(client, run):
    run(sm.t_free_adopt, client)


def test_edit_lock(client, run):
    run(sm.t_edit_lock, client)
