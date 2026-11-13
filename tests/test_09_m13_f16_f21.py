"""M13 가져오기 · F16 지표 · F21 일정 경보."""
import _smoke as sm


def test_m13(client, run):
    run(sm.t_m13, client)


def test_f16_f21(client, run):
    run(sm.t_f16_f21, client)
