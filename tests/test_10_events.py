"""결정 ⑦ — 이슈 변경 기록(block_event)."""
import _smoke as sm


def test_events(client, run):
    run(sm.t_events, client)
