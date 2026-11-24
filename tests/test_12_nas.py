"""단계 5 — NAS 접속 전환 지점(연결 화면·쓰기 차단·3회 한도·비번 미보관)."""
import _smoke as sm


def test_nas(client, run):
    run(sm.t_nas, client)
