"""지표·옛 회의·PPT 출력."""
import _smoke as sm


def test_metrics(client, run):
    run(sm.t_metrics, client)


def test_meeting(client, run):
    run(sm.t_meeting, client)


def test_export(client, run):
    run(sm.t_export, client)
