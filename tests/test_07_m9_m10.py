"""M9 이슈 원장 · M10 회의·스튜디오."""
import _smoke as sm


def test_m9(client, run):
    run(sm.t_m9, client)


def test_m10(client, run):
    run(sm.t_m10, client)
