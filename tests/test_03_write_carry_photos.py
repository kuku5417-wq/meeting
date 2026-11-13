"""작성 흐름·이어받기·사진."""
import _smoke as sm


def test_write_flow(client, run):
    run(sm.t_write_flow, client)


def test_carry(client, run):
    run(sm.t_carry, client)


def test_photos(client, run):
    run(sm.t_photos, client)
