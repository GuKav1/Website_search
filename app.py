# -*- coding: utf-8 -*-
"""
Interface web do Prospector.
E so uma casca: quem faz o trabalho e o prospector.py (CLI), lancado como
processo separado. Assim a corrida sobrevive a um refresh da pagina e podes
fechar o browser sem matar a pesquisa.

    streamlit run app.py
"""
import os, sys, csv, json, time, signal, subprocess
from datetime import datetime

import streamlit as st
import pandas as pd

from prospector import NOMES, PAISES, DIR_OUT, BASE, MOTORES, MOTORES_DEFEITO

FICH_EXEC = os.path.join(DIR_OUT, "_execucao.json")
FICH_LOG = os.path.join(DIR_OUT, "_execucao.log")
FONTES_TODAS = ["busca", "crtsh", "crux", "sellers", "links", "mirrors", "commoncrawl"]
AJUDA_FONTES = {
    "busca": "DuckDuckGo + Bing, queries em 17 idiomas e footprints de CMS. Precisa de IP residencial.",
    "crtsh": "Certificate Transparency: todo o domínio com HTTPS deixa rasto público.",
    "crux": "Chrome UX Report: tráfego real medido pelo Chrome, por país.",
    "sellers": "sellers.json de 28 SSPs: publishers que já monetizam.",
    "links": "Grafo de links a partir das sementes.",
    "mirrors": "Gera ww1.marca.to, marca2.cc… e testa DNS. Encontra mirrors que não estão em índice nenhum.",
    "commoncrawl": "Hosts históricos sob cada domínio semente.",
}

st.set_page_config(page_title="Prospector", page_icon="🎯", layout="wide")


# --------------------------------------------------------------- estado
def execucao_atual():
    if not os.path.exists(FICH_EXEC):
        return None
    try:
        with open(FICH_EXEC, encoding="utf8") as f:
            e = json.load(f)
    except Exception:
        return None
    e["viva"] = processo_vivo(e["pid"])
    return e


def processo_vivo(pid):
    """Não basta `os.kill(pid, 0)`: um processo já terminado cujo pai não fez wait()
    fica zombie (<defunct>) e continua a aceitar sinais — a página ficaria presa em
    "a procurar" para sempre. Exigimos estado != Z e que seja mesmo o prospector
    (um PID é reutilizado pelo sistema)."""
    try:
        os.waitpid(pid, os.WNOHANG)      # colhe o filho se já acabou
    except Exception:
        pass
    try:
        r = subprocess.run(["ps", "-p", str(pid), "-o", "state=,command="],
                           capture_output=True, text=True, timeout=5)
    except Exception:
        return False
    linha = r.stdout.strip()
    if not linha or linha.split()[0].startswith("Z"):
        return False
    return "prospector.py" in linha


def arrancar(cmd, fich_txt, fich_csv):
    log = open(FICH_LOG, "wb")
    # na Streamlit Cloud as chaves vivem nos Secrets da app; passa-as ao processo
    # filho por ambiente (nunca por ficheiro, que iria parar ao repositorio)
    ambiente = dict(os.environ)
    for nome in ("SERPER_API_KEY", "GOOGLE_CSE_KEY", "GOOGLE_CSE_CX"):
        try:
            if nome in st.secrets:
                ambiente[nome] = str(st.secrets[nome])
        except Exception:
            pass
    p = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=BASE, env=ambiente)
    with open(FICH_EXEC, "w", encoding="utf8") as f:
        json.dump({"pid": p.pid, "cmd": cmd, "txt": fich_txt, "csv": fich_csv,
                   "inicio": time.time()}, f)


def parar(pid):
    try:
        os.kill(pid, signal.SIGTERM)
    except Exception:
        pass


def cauda_log(n=40):
    if not os.path.exists(FICH_LOG):
        return ""
    with open(FICH_LOG, encoding="utf8", errors="ignore") as f:
        linhas = [l for l in f.read().splitlines() if "Warning" not in l and "urllib3" not in l]
    return "\n".join(linhas[-n:])


# --------------------------------------------------------------- formulario
st.title("🎯 Prospector")
st.caption("Categoria + país + palavras-chave → lista de domínios para o robot de emails.")

exec_atual = execucao_atual()
a_correr = bool(exec_atual and exec_atual.get("viva"))

with st.form("procura"):
    c1, c2, c3 = st.columns([1, 1, 2])
    categoria = c1.selectbox("Categoria", ["(nenhuma)"] + sorted(NOMES.keys()))
    pais = c2.selectbox("País", sorted(PAISES.keys()), index=sorted(PAISES.keys()).index("PT"))
    keywords = c3.text_input("Palavras-chave (opcional, separadas por vírgula)",
                             placeholder="ver filmes online, assistir series")

    c4, c5 = st.columns([3, 1])
    fontes = c4.multiselect("Fontes", FONTES_TODAS, default=["busca", "crtsh", "links", "mirrors"],
                            help="\n\n".join(f"**{k}** — {v}" for k, v in AJUDA_FONTES.items()))
    maximo = c5.number_input("Máx. domínios", 50, 50000, 1000, step=50)

    ETIQUETA = {"fiavel": "✅", "instavel": "⚠️", "api": "🔑"}
    motores = st.multiselect(
        "Motores de busca (para a fonte «busca»)", list(MOTORES.keys()), default=MOTORES_DEFEITO,
        format_func=lambda m: f"{ETIQUETA[MOTORES[m]['estado']]} {m}",
        help="✅ devolve resultados de forma consistente · "
             "⚠️ responde às vezes, leva captcha com frequência · "
             "🔑 precisa de chave no config.json. "
             "O google.com normal não é possível: a página de resultados é só JavaScript, "
             "não há HTML para ler — daí o google-api. "
             "Os motores correm em paralelo e os bloqueados desligam-se sozinhos.")

    # sementes: ficheiros .txt que existam na pasta acima (a do robot)
    pasta_pai = os.path.dirname(BASE)
    try:
        txts = sorted(f for f in os.listdir(pasta_pai) if f.lower().endswith(".txt"))
    except Exception:
        txts = []
    c6, c7 = st.columns([2, 2])
    if txts:
        sementes = c6.multiselect("Sementes (para links / mirrors / commoncrawl)", txts,
                                  default=[f for f in txts if f.lower().startswith("alvos")][:1],
                                  help=f"Ficheiros .txt em {pasta_pai}")
    else:
        sementes = []
        c6.caption("Sementes: sem ficheiros locais — usa o upload aqui ao lado.")
    carregado = c6.file_uploader("Carregar sementes (.txt, 1 domínio por linha)",
                                 type=["txt", "csv"],
                                 help="Necessário na cloud, onde não há ficheiros locais.")
    validar = c7.checkbox("Validar (abrir cada site, dar score)", value=True)
    min_score = c7.slider("Score mínimo para entrar na lista", 0, 100, 40, disabled=not validar)

    with st.expander("Opções avançadas"):
        a1, a2, a3, a4 = st.columns(4)
        queries = a1.number_input("Queries de pesquisa", 0, 300, 40)
        paginas = a1.number_input("Páginas por query", 1, 10, 3)
        profundidade = a2.number_input("Níveis do grafo de links", 1, 4, 1)
        max_links = a2.number_input("Sites por nível", 20, 3000, 300)
        max_mirror = a3.number_input("Candidatos DNS (mirrors)", 1000, 300000, 40000, step=1000)
        mirror_tlds = a3.number_input("TLDs a testar (mirrors)", 5, 51, 22)
        workers = a4.number_input("Threads de validação", 5, 80, 25)
        max_api = a4.number_input("Travão de chamadas a API", 0, 5000, 90,
                                  help="Google: 100 pesquisas/dia grátis, cada página conta uma. "
                                       "Acima disso paga-se. Este travão impede a corrida de "
                                       "gastar mais do que o que autorizas.")
        nivel = a4.selectbox("Nível", ["host", "dominio"],
                             help="host mantém ww1.x.com separado de x.com")
        repetir = st.checkbox("Ignorar o histórico (voltar a testar domínios já vistos)")

    arrancou = st.form_submit_button("▶️  Procurar sites", disabled=a_correr,
                                     width="stretch", type="primary")

if arrancou:
    if not fontes:
        st.error("Escolhe pelo menos uma fonte.")
    elif categoria == "(nenhuma)" and not keywords.strip() and not sementes and carregado is None:
        st.error("Precisas de uma categoria, palavras-chave ou sementes.")
    else:
        carimbo = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = (categoria if categoria != "(nenhuma)" else "geral") + "-" + pais
        f_txt = os.path.join(DIR_OUT, f"alvos_{slug}_{carimbo}.txt")
        f_csv = os.path.join(DIR_OUT, f"detalhe_{slug}_{carimbo}.csv")
        cmd = [sys.executable, "-u", os.path.join(BASE, "prospector.py"),
               "--pais", pais, "--fontes", ",".join(fontes), "--max", str(maximo),
               "--out", f_txt, "--out-csv", f_csv, "--min-score", str(min_score),
               "--queries", str(queries), "--paginas", str(paginas),
               "--profundidade", str(profundidade), "--max-links-seed", str(max_links),
               "--max-mirror", str(max_mirror), "--mirror-tlds", str(mirror_tlds),
               "--workers", str(workers), "--nivel", nivel,
               "--motores", ",".join(motores) if motores else ",".join(MOTORES_DEFEITO),
               "--max-api", str(max_api)]
        if categoria != "(nenhuma)":
            cmd += ["--categoria", categoria]
        if keywords.strip():
            cmd += ["--keywords", keywords.strip()]
        caminhos_sementes = [os.path.join(pasta_pai, s) for s in sementes]
        if carregado is not None:
            destino = os.path.join(DIR_OUT, "_sementes_carregadas.txt")
            with open(destino, "wb") as f:
                f.write(carregado.getvalue())
            caminhos_sementes.append(destino)
        if caminhos_sementes:
            cmd += ["--seeds", ",".join(caminhos_sementes)]
        if validar:
            cmd += ["--validar"]
        if repetir:
            cmd += ["--repetir"]
        arrancar(cmd, f_txt, f_csv)
        st.rerun()

# --------------------------------------------------------------- execucao
exec_atual = execucao_atual()
if exec_atual:
    a_correr = exec_atual.get("viva")
    decorrido = int(time.time() - exec_atual["inicio"])
    st.divider()
    if a_correr:
        c1, c2 = st.columns([4, 1])
        c1.info(f"A procurar há {decorrido//60}m{decorrido%60}s — podes fechar o browser, "
                "a pesquisa continua.")
        if c2.button("⏹️  Parar", width="stretch"):
            parar(exec_atual["pid"])
            time.sleep(1)
            st.rerun()
    st.code(cauda_log(), language="text")
    if a_correr:
        time.sleep(3)
        st.rerun()

# --------------------------------------------------------------- resultados
st.divider()
st.subheader("Resultados")

# por data de escrita, nao por nome: os nomes nao ordenam de forma fiavel
listas = sorted((f for f in os.listdir(DIR_OUT) if f.startswith("alvos_") and f.endswith(".txt")),
                key=lambda f: os.path.getmtime(os.path.join(DIR_OUT, f)), reverse=True)
if not listas:
    st.caption("Ainda não há listas. Corre uma pesquisa acima.")
else:
    def _rotulo(f):
        quando = datetime.fromtimestamp(os.path.getmtime(os.path.join(DIR_OUT, f)))
        n = sum(1 for l in open(os.path.join(DIR_OUT, f), encoding="utf8") if l.strip())
        return f"{f}   ·   {n} domínios   ·   {quando:%d/%m %H:%M}"

    escolhida = st.selectbox("Lista", listas, format_func=_rotulo)
    cam_txt = os.path.join(DIR_OUT, escolhida)
    dominios = [l.strip() for l in open(cam_txt, encoding="utf8") if l.strip()]
    cam_csv = os.path.join(DIR_OUT, escolhida.replace("alvos_", "detalhe_").replace(".txt", ".csv"))

    c1, c2, c3 = st.columns([1, 1, 2])
    c1.metric("Domínios", len(dominios))
    c2.download_button("⬇️  .txt para o robot", "\n".join(dominios) + "\n",
                       file_name=escolhida, mime="text/plain", width="stretch")
    if os.path.exists(cam_csv):
        c3.download_button("⬇️  .csv com o detalhe", open(cam_csv, "rb").read(),
                           file_name=os.path.basename(cam_csv), mime="text/csv")
        try:
            df = pd.read_csv(cam_csv)
            if "score" in df.columns:
                df = df.sort_values("score", ascending=False)
            st.dataframe(df, width="stretch", hide_index=True, height=420)
        except Exception as e:
            st.caption(f"CSV ilegível: {e}")
    else:
        st.text("\n".join(dominios[:60]))
