"""경로·토큰·주차·호선 정규화 — 앱 없이."""
import _smoke as sm


def test_paths(run):
    run(sm.t_paths)


def test_tokens(run):
    run(sm.t_tokens)


def test_weeks(run):
    run(sm.t_weeks)


def test_sn(run):
    run(sm.t_sn)
