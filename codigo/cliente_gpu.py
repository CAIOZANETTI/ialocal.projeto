"""Cliente da trava de GPU do ialocal.maestro — COPIE este arquivo para o repositório que usa a GPU (sem import do
maestro: a regra de independência vale para todos). Só a biblioteca padrão.

    from cliente_gpu import vez_da_gpu

    with vez_da_gpu('ialocal.revisor', '~/dados/ialocal.revisor/dados/gpu', prioridade=8, modelo='qwen3', tarefa='perguntas') as vez:
        for item in fila:
            if not vez.minha():      # o pedaço venceu e alguém mais importante espera: devolve e pede de novo depois
                break
            trabalhar(item)          # um pedaço curto: o dono espera no máximo isso

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
    sessao.fechar()
"""
import json
import os
import time
import uuid
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path

VEZ = Path.home() / 'dados' / 'ialocal.maestro' / 'dados' / 'gpu' / 'vez.json'


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
    def __init__(self, identificador, vez_arquivo, com_maestro, negada=False):
        self.id, self.vez_arquivo, self.com_maestro, self.negada = identificador, vez_arquivo, com_maestro, negada

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
        inicio = time.time()
        yield Vez(identificador, vez_arquivo, com_maestro, negada)
    finally:
        pedido.unlink(missing_ok=True)
    if negada:
        return  # não usou a GPU: nada a registrar em feitos
    fim = time.time()
    with open(pasta / 'feitos.jsonl', 'a') as saida:
        saida.write(json.dumps({'id': identificador, 'repo': repo, 'modelo': modelo, 'tarefa': tarefa, 'com_maestro': com_maestro,
                                'inicio': datetime.fromtimestamp(inicio).isoformat(timespec='seconds'),
                                'fim': datetime.fromtimestamp(fim).isoformat(timespec='seconds'),
                                'segundos': round(fim - inicio, 2)}, ensure_ascii=False) + '\n')


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

    def fechar(self):
        if self.pilha is not None:
            self.pilha.close()
        self.pilha = self.vez = self.modelo = None
