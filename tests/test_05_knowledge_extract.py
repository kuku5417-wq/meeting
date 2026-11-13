"""지식창고·메모 AI 정리·미등록 표기·대시보드."""
import _smoke as sm


def test_knowledge(client, run):
    run(sm.t_knowledge, client)


def test_save_and_extract(client, run):
    run(sm.t_save_and_extract, client)


def test_unregistered(client, run):
    run(sm.t_unregistered, client)


def test_dashboard_report(client, run):
    run(sm.t_dashboard_report, client)
