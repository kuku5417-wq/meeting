"""기준정보 API·장비 허브·LLM 체인."""
import _smoke as sm


def test_masters_api(client, run):
    run(sm.t_masters_api, client)


def test_hub(client, run):
    run(sm.t_hub, client)


def test_llm(client, run):
    run(sm.t_llm_c, client)
