"""설정·중앙 parquet(pjtlist·milestone)."""
import _smoke as sm


def test_settings(client, run):
    run(sm.t_settings, client)


def test_central(client, run):
    run(sm.t_central, client)
