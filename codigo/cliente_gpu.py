"""Cliente da trava de GPU do ialocal.maestro — COPIE este arquivo para o repositório que usa a GPU (sem import do
maestro: a regra de independência vale para todos). Só a biblioteca padrão.

    from cliente_gpu import vez_da_gpu

    with vez_da_gpu('ialocal.revisor', '~/dados/ialocal.revisor/dados/gpu', prioridade=8, modelo='qwen3', tarefa='perguntas') as vez:
        for item in fila:
            if not vez.minha():      # o pedaço venceu e alguém mais importante espera: devolve e pede de novo depois
                break
            resposta = trabalhar(item)          # um pedaço curto: o dono espera no máximo isso
            vez.contar('perguntas')             # o trabalho útil feito nesta vez (opcional): páginas, fotos, pranchas…
            vez.tokens(resposta['prompt_eval_count'], resposta['eval_count'])   # os tokens que o Ollama devolve (opcional)
        vez.anotar(contexto=8192, quantizacao='q4_K_M')                         # o que vale para a vez inteira (opcional)

O SINAL DE VIDA (maestro 0v66, o vigia de progresso): `vez.avancei(item)` a cada passo que avança de verdade — uma
fatia lida, uma resposta do modelo, uma página — com o item em curso (o documento, a prancha). Quem chama avancei uma
vez passa a ser vigiado: se a vez fica mais de progresso_max_s (politica.json, 16 min) sem avanço, o maestro encerra o
processo, libera a GPU e registra o item em travados.jsonl (04/10: uma rodada ficou 11 h presa no Apple Vision com a
vez e a fila inteira esperou; 16 min = acima do timeout de 900 s das chamadas ao Ollama em todos os repositórios, então
um avancei por resposta de modelo basta). Quem nunca chama avancei não é vigiado (só o aviso de vez presa). O item que já travou
`travamentos(repo, item)` vezes o repositório pode pôr em quarentena (pular) — a regra é: mais uma tentativa, depois
quarentena. `cliente_gpu.avancei(item)` (do módulo) marca a vez em curso deste processo, sem passar a Vez adiante.

    with vez_da_gpu(...) as vez:
        for documento in fila:
            if travamentos('ialocal.projeto', documento['id']) >= 2:
                continue                        # quarentena: travou duas vezes
            vez.avancei(documento['id'])        # o item em curso
            for fatia in fatias:
                ler(fatia)
                avancei()                       # de qualquer lugar do código: a vez deste processo avançou

O trabalho útil (desde o maestro 0v64, fase C2 da capacidade) vai para o feitos.jsonl junto com o tempo: `unidades`
({'paginas': 12, 'fotos': 3}), `tokens_entrada`, `tokens_saida` e o que foi anotado. Só sai o que foi declarado: quem
não conta nada grava o feito como antes. Unidades no plural e sem acento, as mesmas em todos: paginas, fotos,
pranchas, documentos, perguntas. É o que deixa o maestro dizer páginas por hora e R$ por 1.000 páginas, em vez de só
segundos de GPU.

O que ele faz:
- escreve o pedido em <gpu_pasta>/pedidos/<id>.json (na pasta do próprio repositório) e espera o vez.json do maestro
  apontar esse id;
- FALHA ABERTA: se o vez.json não existe ou não é renovado há mais de `espera_maestro_s`, segue sem a trava
  (`vez.com_maestro` fica False) — o maestro nunca é pré-requisito para trabalhar;
- ao sair, apaga o pedido e acrescenta o uso em <gpu_pasta>/feitos.jsonl (o maestro soma para o painel).

Para uma fila de tarefas em que só algumas usam a GPU (o ciclo do extrator), a SessaoGpu segura a vez entre tarefas de
GPU seguidas e devolve quando vem tarefa sem GPU, quando o modelo muda ou quando a vez pede devolução:

    sessao = SessaoGpu('ialocal.extrator', '~/dados/orquestrador/gpu', prioridade=5)
    for tarefa in fila:
        sessao.antes(usa_gpu(tarefa), modelo=tarefa['executor'])
        executar(tarefa)
        sessao.contar('paginas', tarefa['paginas'])   # opcional: vai para o feito da vez em curso
    sessao.fechar()
"""
import json
import os
import threading
import time
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path

VEZ = Path.home() / 'dados' / 'ialocal.maestro' / 'dados' / 'gpu' / 'vez.json'
ATUAL = None  # a Vez em curso deste processo (avancei() do módulo marca nela)
TRAVA_DO_PEDIDO = threading.Lock()  # as threads do mesmo processo (as perguntas em paralelo do extrator) gravam uma por vez


def _agora():
    return datetime.now().replace(microsecond=0)


def _ler(arquivo):
    try:
        return json.loads(Path(arquivo).read_text())
    except (OSError, ValueError):
        return {}


def _gravar(arquivo, conteudo):
    temporario = arquivo.with_name(f'.{arquivo.name}.{os.getpid()}')
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False))
    temporario.replace(arquivo)


def maestro_vivo(vez_arquivo, espera_maestro_s, momento=None):
    """O maestro renovou o vez.json há no máximo espera_maestro_s?"""
    em = _ler(vez_arquivo).get('em')
    try:
        return em is not None and ((momento or _agora()) - datetime.fromisoformat(em[:19])).total_seconds() <= espera_maestro_s
    except ValueError:
        return False


def _vivo(pid):
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # existe, de outro usuário
        return True
    except (TypeError, ValueError):  # pedido sem pid: não há quem o renove
        return False
    return True


def _limpar_mortos(pasta):
    """Tira da própria pasta o pedido de processo que já morreu (morto à força, o finally não roda — no mini, 29/09, os
    pedidos órfãos do ciclo ficavam no disco e o maestro os descartava a cada ciclo). Só a pasta do próprio repositório."""
    for arquivo in (pasta / 'pedidos').glob('*.json'):
        if not _vivo(_ler(arquivo).get('pid')):
            arquivo.unlink(missing_ok=True)


class Vez:
    def __init__(self, identificador, vez_arquivo, com_maestro, negada=False, pedido=None):
        self.id, self.vez_arquivo, self.com_maestro, self.negada = identificador, vez_arquivo, com_maestro, negada
        self.unidades, self.entrada, self.saida, self.notas = {}, 0, 0, {}
        self.pedido, self.item, self.avancos = pedido, None, 0

    def avancei(self, item=None):
        """O sinal de vida: o trabalho avançou agora (e, com item, o item em curso mudou). Grava no pedido, que o
        maestro lê a cada ciclo; o primeiro avancei liga o vigia para esta vez."""
        with TRAVA_DO_PEDIDO:
            if item is not None:
                self.item = str(item)[:200]
            self.avancos += 1
            try:  # o sinal de vida nunca derruba o trabalho: sem gravar, o vigia só vê o avanço anterior
                if self.pedido is not None and self.pedido.exists():
                    _gravar(self.pedido, {**_ler(self.pedido), 'vigia': True, 'avanco_em': _agora().isoformat(), 'item': self.item,
                                          'avancos': self.avancos})
            except OSError:
                pass

    def contar(self, unidade, n=1):
        """+n da unidade de trabalho útil feita nesta vez ('paginas', 'fotos', 'pranchas', 'documentos', 'perguntas')."""
        self.unidades[unidade] = self.unidades.get(unidade, 0) + n

    def tokens(self, entrada=0, saida=0):
        """Os tokens de uma chamada ao modelo (no Ollama: prompt_eval_count e eval_count da resposta)."""
        self.entrada += entrada or 0
        self.saida += saida or 0

    def anotar(self, **campos):
        """O que vale para a vez inteira: contexto (tokens), quantizacao ('q4_K_M', '4bit')."""
        self.notas.update(campos)

    def medidas(self):
        """O trabalho útil declarado, para o feitos.jsonl; vazio se nada foi declarado (o feito sai como antes)."""
        medidas = {'unidades': dict(self.unidades)} if self.unidades else {}
        if self.entrada or self.saida:
            medidas |= {'tokens_entrada': self.entrada, 'tokens_saida': self.saida}
        return medidas | self.notas

    def minha(self):
        """Ainda posso continuar? Negada (esperou além de espera_max_s), nunca; sem maestro, sempre; com ele, até a vez
        pedir `devolver` (ou deixar de ser minha)."""
        if self.negada:
            return False
        if not self.com_maestro:
            return True
        vez = _ler(self.vez_arquivo).get('vez') or {}
        return vez.get('id') == self.id and not vez.get('devolver')


@contextmanager
def vez_da_gpu(repo, gpu_pasta, prioridade, modelo=None, tarefa=None, espera_maestro_s=30, vez_arquivo=None, intervalo_s=1.0,
               espera_max_s=None):
    """A vez da GPU (veja o topo). espera_max_s: quem é de fundo e não pode esperar para sempre (a bancada do extrator,
    atrás da extração) desiste depois disso — a Vez volta `negada` (com o maestro de pé, sem a vez: não use a GPU)."""
    pasta = Path(os.path.expanduser(gpu_pasta))
    (pasta / 'pedidos').mkdir(parents=True, exist_ok=True)
    _limpar_mortos(pasta)
    vez_arquivo = Path(vez_arquivo) if vez_arquivo else VEZ
    identificador = f"{repo}.{_agora().strftime('%Y%m%d%H%M%S')}.{uuid.uuid4().hex[:6]}"
    pedido = pasta / 'pedidos' / f'{identificador}.json'
    _gravar(pedido, {'id': identificador, 'repo': repo, 'prioridade': prioridade, 'modelo': modelo, 'tarefa': tarefa,
                     'desde': _agora().isoformat(), 'pid': os.getpid()})
    com_maestro, negada, limite = False, False, time.time() + espera_max_s if espera_max_s else None
    try:
        while maestro_vivo(vez_arquivo, espera_maestro_s):
            if ((_ler(vez_arquivo).get('vez') or {}).get('id')) == identificador:
                com_maestro = True
                break
            if limite is not None and time.time() > limite:
                com_maestro = negada = True
                break
            time.sleep(intervalo_s)
        global ATUAL
        inicio = time.time()
        vez = ATUAL = Vez(identificador, vez_arquivo, com_maestro, negada, pedido)
        yield vez
    finally:
        ATUAL = None
        pedido.unlink(missing_ok=True)
    if negada:
        return  # não usou a GPU: nada a registrar em feitos
    fim = time.time()
    with open(pasta / 'feitos.jsonl', 'a') as saida:
        saida.write(json.dumps({**vez.medidas(), 'id': identificador, 'repo': repo, 'modelo': modelo, 'tarefa': tarefa, 'com_maestro': com_maestro,
                                'inicio': datetime.fromtimestamp(inicio).isoformat(timespec='seconds'),
                                'fim': datetime.fromtimestamp(fim).isoformat(timespec='seconds'),
                                'segundos': round(fim - inicio, 2)}, ensure_ascii=False) + '\n')


def avancei(item=None):
    """O sinal de vida da vez em curso deste processo, de qualquer lugar do código (sem vez, nada)."""
    if ATUAL is not None:
        ATUAL.avancei(item)


def travamentos(repo, item, vez_arquivo=None):
    """Quantas vezes o maestro encerrou este repositório parado neste item (travados.jsonl, ao lado do vez.json)."""
    arquivo = (Path(vez_arquivo) if vez_arquivo else VEZ).with_name('travados.jsonl')
    try:
        linhas = arquivo.read_text().splitlines()
    except OSError:
        return 0
    contados = 0
    for linha in linhas:
        try:
            registro = json.loads(linha)
        except ValueError:
            continue
        contados += registro.get('repo') == repo and registro.get('item') == str(item)[:200]
    return contados


class SessaoGpu:
    """A vez segurada entre tarefas seguidas de GPU: pedir a vez a cada tarefa custaria um ciclo do maestro por tarefa."""
    def __init__(self, repo, gpu_pasta, prioridade, espera_maestro_s=30, vez_arquivo=None, espera_max_s=None):
        self.repo, self.gpu_pasta, self.prioridade = repo, gpu_pasta, prioridade
        self.espera_maestro_s, self.vez_arquivo, self.espera_max_s = espera_maestro_s, vez_arquivo, espera_max_s
        self.pilha = self.vez = self.modelo = None

    def antes(self, usa_gpu, modelo=None, tarefa=None):
        """Chamar antes de cada tarefa: devolve a vez se a tarefa não usa GPU, se o modelo mudou ou se a vez pede
        devolução; pede a vez (e espera por ela) se a tarefa usa GPU e a vez não está com esta sessão."""
        if self.vez is not None and (not usa_gpu or modelo != self.modelo or not self.vez.minha()):
            self.fechar()
        if usa_gpu and self.vez is None:
            self.pilha = ExitStack()
            self.vez = self.pilha.enter_context(vez_da_gpu(self.repo, self.gpu_pasta, self.prioridade, modelo, tarefa,
                                                           self.espera_maestro_s, self.vez_arquivo, espera_max_s=self.espera_max_s))
            self.modelo = modelo
            if self.vez.negada:  # esperou demais: devolve o pedido já; a próxima tarefa de GPU pede de novo
                negada = self.vez
                self.fechar()
                return negada
        return self.vez

    def contar(self, unidade, n=1):
        """+n da unidade na vez em curso; sem vez (a tarefa não usou a GPU), não conta: o feito é só da GPU."""
        if self.vez is not None:
            self.vez.contar(unidade, n)

    def tokens(self, entrada=0, saida=0):
        if self.vez is not None:
            self.vez.tokens(entrada, saida)

    def fechar(self):
        if self.pilha is not None:
            self.pilha.close()
        self.pilha = self.vez = self.modelo = None
