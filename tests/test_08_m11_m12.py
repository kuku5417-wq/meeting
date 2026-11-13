"""M11 취합·발행·PPT · M12 회의 진행·종결·지시."""
import _smoke as sm


def test_m11(client, run):
    run(sm.t_m11, client)


def test_m12(client, run):
    run(sm.t_m12, client)
