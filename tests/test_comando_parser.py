from app.services.comando_parser import Comando, identificar_comando


def test_comando_ajuda():
    assert identificar_comando("ajuda") == Comando.AJUDA
    assert identificar_comando("help") == Comando.AJUDA
    assert identificar_comando("?") == Comando.AJUDA
    assert identificar_comando("AJUDA") == Comando.AJUDA


def test_comando_historico():
    assert identificar_comando("historico") == Comando.HISTORICO
    assert identificar_comando("histórico") == Comando.HISTORICO
    assert identificar_comando("minhas visitas") == Comando.HISTORICO


def test_comando_fazendas():
    assert identificar_comando("fazendas") == Comando.FAZENDAS
    assert identificar_comando("minhas fazendas") == Comando.FAZENDAS


def test_comando_plano():
    assert identificar_comando("plano") == Comando.PLANO
    assert identificar_comando("meu plano") == Comando.PLANO


def test_comando_status():
    assert identificar_comando("status") == Comando.STATUS
    assert identificar_comando("minha conta") == Comando.STATUS


def test_saudacao():
    assert identificar_comando("oi") == Comando.SAUDACAO
    assert identificar_comando("bom dia") == Comando.SAUDACAO
    assert identificar_comando("boa tarde!") == Comando.SAUDACAO


def test_texto_longo_eh_visita():
    relato = (
        "Visitei hoje a Fazenda Bela Vista, talhão 3. "
        "Encontrei ferrugem com severidade média em uns "
        "15 hectares. Tem também broca no início, nível leve. "
        "Recomendo aplicar Cuprozeb 2kg por hectare."
    )
    assert identificar_comando(relato) == Comando.VISITA


def test_texto_curto_desconhecido():
    assert identificar_comando("blablabla") == Comando.DESCONHECIDO
    assert identificar_comando("teste") == Comando.DESCONHECIDO


def test_vazio():
    assert identificar_comando("") == Comando.DESCONHECIDO
    assert identificar_comando("   ") == Comando.DESCONHECIDO
