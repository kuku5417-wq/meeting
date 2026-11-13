"""앱 공통 — 표 생성·화면 탭·기준정보 시드·글꼴 (뒤 파일들이 이 데이터를 쓴다)."""
import _smoke as sm


def test_base(client, run):
    run(sm.t_base, client)
