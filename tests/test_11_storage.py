"""결정 ① — NAS 위 SQLite 하나: 저널·대기·매일 백업·무결성."""
import _smoke as sm


def test_storage(client, run):
    run(sm.t_storage, client)
