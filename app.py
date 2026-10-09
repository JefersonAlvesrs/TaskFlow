from flask import Flask, render_template, request, redirect, session, g, has_request_context
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from threading import Lock
from werkzeug.middleware.proxy_fix import ProxyFix
import time
import os
from dotenv import load_dotenv
from datetime import date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from flask import url_for
import json
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

load_dotenv()
app = Flask(__name__)
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,
    x_proto=1
)

app.secret_key = os.environ["SECRET_KEY"]
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30)
)

@app.before_request
def controlar_sessao():
    if "usuario_id" in session:
        session.permanent = True
        session.modified = True

csrf = CSRFProtect(app)
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://"
)

@app.errorhandler(429)
def limite_excedido(erro):
    mensagem = "Muitas tentativas. Aguarde e tente novamente mais tarde."

    if request.path == "/solicitar-recuperacao":
        return render_template(
            "esqueci_senha.html",
            mensagem=mensagem
        ), 429

    return render_template(
        "login.html",
        erro=mensagem
    ), 429

DATABASE_URL = os.environ.get("DATABASE_URL")

def enviar_email(destinatario, assunto, mensagem):
    """Envia e-mail transacional pela API HTTPS da Brevo (compatível com Render)."""
    chave_api = os.environ.get("BREVO_API_KEY")
    if not chave_api:
        raise RuntimeError("BREVO_API_KEY não configurada")

    dados = {
        "sender": {"name": "TaskFlow", "email": "jefersoncjg@gmail.com"},
        "to": [{"email": destinatario}],
        "subject": assunto,
        "textContent": mensagem,
    }
    requisicao = Request(
        "https://api.brevo.com/v3/smtp/email",
        data=json.dumps(dados).encode("utf-8"),
        headers={
            "accept": "application/json",
            "content-type": "application/json",
            "api-key": chave_api,
        },
        method="POST",
    )
    try:
        with urlopen(requisicao, timeout=15) as resposta:
            if resposta.status not in (200, 201, 202):
                raise RuntimeError(f"Brevo retornou HTTP {resposta.status}")
    except HTTPError as erro:
        # Não registrar corpo da resposta para evitar exposição de dados.
        raise RuntimeError(f"Falha no envio pela Brevo (HTTP {erro.code})") from erro
    except URLError as erro:
        raise RuntimeError("Não foi possível conectar à API da Brevo") from erro

def gerar_token_recuperacao(email):
    conexao = conectar_postgres()
    cursor = conexao.cursor()

    cursor.execute(
        "SELECT senha FROM usuarios WHERE LOWER(email) = %s",
        (email,)
    )
    usuario = cursor.fetchone()

    cursor.close()
    conexao.close()

    if not usuario:
        return None

    serializer = URLSafeTimedSerializer(app.secret_key)

    import hashlib

    identificador = hashlib.sha256(
        usuario[0].encode("utf-8")
    ).hexdigest()

    return serializer.dumps(
        [email, identificador],
        salt="recuperacao-senha"
    )


def verificar_token_recuperacao(token):
    serializer = URLSafeTimedSerializer(app.secret_key)

    try:
        email, identificador_anterior = serializer.loads(
            token,
            salt="recuperacao-senha",
            max_age=1800
        )

        conexao = conectar_postgres()
        cursor = conexao.cursor()

        cursor.execute(
            "SELECT senha FROM usuarios WHERE LOWER(email) = %s",
            (email,)
        )
        usuario = cursor.fetchone()

        cursor.close()
        conexao.close()

        if usuario:
            import hashlib

            identificador_atual = hashlib.sha256(
                usuario[0].encode("utf-8")
            ).hexdigest()

            if identificador_atual == identificador_anterior:
                return email

    except (SignatureExpired, BadSignature, ValueError, TypeError):
        pass

    return None

# O pool é criado apenas no primeiro acesso ao banco, por processo do servidor.
_pool_postgres = None
_pool_lock = Lock()


def obter_pool_postgres():
    global _pool_postgres
    if _pool_postgres is None:
        with _pool_lock:
            if _pool_postgres is None:
                _pool_postgres = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=5,
                    dsn=DATABASE_URL,
                )
    return _pool_postgres


class ConexaoReutilizavel:
    """Mantém a interface psycopg2; close() devolve a conexão ao pool."""

    def __init__(self, conexao, pool):
        self._conexao = conexao
        self._pool = pool
        self._fechada = False

    def __getattr__(self, nome):
        return getattr(self._conexao, nome)

    def close(self):
        if self._fechada:
            return
        self._fechada = True
        try:
            # Finaliza SELECTs e qualquer transação não confirmada.
            self._conexao.rollback()
        except Exception:
            # Não reutiliza uma conexão cujo estado pode estar inválido.
            self._pool.putconn(self._conexao, close=True)
            raise
        else:
            self._pool.putconn(self._conexao)
        finally:
            if has_request_context():
                abertas = getattr(g, "conexoes_postgres", None)
                if abertas is not None:
                    abertas.discard(self)


def conectar_postgres():
    inicio = time.perf_counter()
    pool = obter_pool_postgres()
    conexao = ConexaoReutilizavel(pool.getconn(), pool)
    tempo = time.perf_counter() - inicio
    print(f"Tempo para obter conexão PostgreSQL: {tempo:.3f} segundos", flush=True)

    if has_request_context():
        if not hasattr(g, "conexoes_postgres"):
            g.conexoes_postgres = set()
        g.conexoes_postgres.add(conexao)
    return conexao


@app.teardown_request
def devolver_conexoes_pendentes(erro):
    # Também devolve conexões quando uma rota falha antes do close().
    for conexao in list(getattr(g, "conexoes_postgres", ())):
        try:
            conexao.close()
        except Exception:
            app.logger.exception("Erro ao devolver conexão PostgreSQL ao pool")


def criar_tabelas_postgres():
    conexao_pg = conectar_postgres()
    cursor_pg = conexao_pg.cursor()

    cursor_pg.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL
        )
    """)

    cursor_pg.execute("""
        CREATE TABLE IF NOT EXISTS tarefas (
            id SERIAL PRIMARY KEY,
            titulo TEXT NOT NULL,
            concluida INTEGER NOT NULL DEFAULT 0,
            prioridade TEXT DEFAULT 'Média',
            prazo TEXT,
            usuario_id INTEGER REFERENCES usuarios(id)
        )
    """)

    conexao_pg.commit()
    cursor_pg.close()
    conexao_pg.close()


@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/entrar", methods=["POST"])
@limiter.limit("5 per minute")
def entrar():
    email = request.form["email"].strip().lower()
    senha = request.form["senha"]

    conexao = conectar_postgres()
    import time
    inicio_consulta = time.perf_counter()
    cursor = conexao.cursor()

    cursor.execute(
        "SELECT id, nome, email, senha FROM usuarios WHERE email = %s",
        (email,)
    )
    usuario = cursor.fetchone()

    cursor.close()
    conexao.close()

    if usuario and check_password_hash(usuario[3], senha):
        session["usuario_id"] = usuario[0]
        session["usuario_nome"] = usuario[1]
        return redirect("/")

    return render_template(
        "login.html",
        erro="E-mail ou senha incorretos."
    )

@app.route("/esqueci-senha")
def esqueci_senha():
    return render_template("esqueci_senha.html")


@app.route("/solicitar-recuperacao", methods=["POST"])
@limiter.limit("3 per hour")
def solicitar_recuperacao():
    email = request.form["email"].strip().lower()

    conexao = conectar_postgres()
    cursor = conexao.cursor()

    cursor.execute(
        "SELECT id FROM usuarios WHERE LOWER(email) = %s",
        (email,)
    )
    usuario = cursor.fetchone()

    cursor.close()
    conexao.close()

    mensagem = "Se o e-mail estiver cadastrado, você receberá um link de recuperação."

    if usuario:
        token = gerar_token_recuperacao(email)
        link = url_for("redefinir_senha", token=token, _external=True)

        try:
            enviar_email(
                email,
                "Recuperação de senha - TaskFlow",
                f"Olá!\n\n"
                f"Para redefinir sua senha, acesse:\n{link}\n\n"
                f"Este link expira em 30 minutos.\n\n"
                f"Se você não solicitou a recuperação, ignore este e-mail."
            )
        except Exception:
            app.logger.exception("Erro ao enviar e-mail de recuperação")

    return render_template(
        "esqueci_senha.html",
        mensagem=mensagem
    )

@app.route("/redefinir-senha/<token>", methods=["GET", "POST"])
def redefinir_senha(token):
    email = verificar_token_recuperacao(token)

    if not email:
        return render_template(
            "esqueci_senha.html",
            mensagem="Este link é inválido ou expirou. Solicite uma nova recuperação."
        ), 400

    if request.method == "POST":
        senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar_senha", "")

        if len(senha) < 8:
            return render_template(
                "redefinir_senha.html",
                erro="A senha deve ter pelo menos 8 caracteres."
            )

        if senha != confirmar:
            return render_template(
                "redefinir_senha.html",
                erro="As senhas não coincidem."
            )

        conexao = conectar_postgres()
        cursor = conexao.cursor()

        cursor.execute(
            "UPDATE usuarios SET senha = %s WHERE LOWER(email) = %s",
            (generate_password_hash(senha), email)
        )

        conexao.commit()
        cursor.close()
        conexao.close()

        session.clear()
        return redirect("/login")

    return render_template("redefinir_senha.html")

@app.route("/cadastro")
def cadastro():
    return render_template("cadastro.html")

@app.route("/cadastrar", methods=["POST"])
def cadastrar():
    nome = request.form["nome"]
    email = request.form["email"].strip().lower()
    senha = request.form["senha"]

    if len(senha) < 8:
        return render_template(
            "cadastro.html",
            erro="A senha deve ter pelo menos 8 caracteres."
        )

    conexao = conectar_postgres()
    cursor = conexao.cursor()

    cursor.execute(
        "SELECT id FROM usuarios WHERE email = %s",
        (email,)
    )

    usuario_existente = cursor.fetchone()

    if usuario_existente:
        cursor.close()
        conexao.close()

        return render_template(
            "cadastro.html",
            erro="Este e-mail já está cadastrado."
        )

    senha_hash = generate_password_hash(senha)

    cursor.execute(
        "INSERT INTO usuarios (nome, email, senha) VALUES (%s, %s, %s) RETURNING id",
        (nome, email, senha_hash)
    )

    usuario_id = cursor.fetchone()[0]

    conexao.commit()
    cursor.close()
    conexao.close()

    session["usuario_id"] = usuario_id
    session["usuario_nome"] = nome

    return redirect("/")

@app.route("/sair")
def sair():
    session.clear()
    return redirect("/login")

@app.route("/")
def home():
    if "usuario_id" not in session:
        return redirect("/login")

    usuario_id = session["usuario_id"]
    status = request.args.get("status")

    conexao = conectar_postgres()
    cursor = conexao.cursor()

    ordem = """
        ORDER BY CASE prioridade
            WHEN 'Alta' THEN 1
            WHEN 'Média' THEN 2
            WHEN 'Baixa' THEN 3
            ELSE 4
        END
    """

    if status == "pendente":
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas "
            "WHERE concluida = 0 "
            "AND (prazo = '' OR prazo IS NULL OR prazo >= %s) "
            "AND usuario_id = %s " + ordem,
            (date.today().isoformat(), usuario_id)
        )

    elif status == "concluida":
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas WHERE concluida = 1 AND usuario_id = %s " + ordem,
            (usuario_id,)
        )

    elif status == "atrasada":
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas "
            "WHERE concluida = 0 AND prazo != '' AND prazo < %s "
            "AND usuario_id = %s " + ordem,
            (date.today().isoformat(), usuario_id)
        )

    else:
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas WHERE usuario_id = %s " + ordem,
            (usuario_id,)
        )

    tarefas = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM tarefas "
        "WHERE concluida = 0 "
        "AND (prazo = '' OR prazo IS NULL OR prazo >= %s) "
        "AND usuario_id = %s",
        (date.today().isoformat(), usuario_id)
    )
    total_pendentes = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tarefas "
        "WHERE concluida = 1 AND usuario_id = %s",
        (usuario_id,)
    )
    total_concluidas = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tarefas "
        "WHERE concluida = 0 AND prazo != '' "
        "AND prazo < %s AND usuario_id = %s",
        (date.today().isoformat(), usuario_id)
    )
    total_atrasadas = cursor.fetchone()[0]

    cursor.close()
    conexao.close()

    return render_template(
        "index.html",
        tarefas=tarefas,
        hoje=date.today().isoformat(),
        total_pendentes=total_pendentes,
        total_concluidas=total_concluidas,
        total_atrasadas=total_atrasadas
    )

@app.route("/adicionar", methods=["POST"])
def adicionar():
    if "usuario_id" not in session:
        return redirect("/login")

    titulo = request.form["titulo"].strip()

    if not titulo:
        return redirect("/")

    prioridade = request.form["prioridade"]

    if prioridade not in ["Baixa", "Média", "Alta"]:
        prioridade = "Média"

    prazo = request.form["prazo"]
    conexao = conectar_postgres()
    cursor = conexao.cursor()

    import time
    inicio_consulta = time.perf_counter()

    cursor.execute(
        """
        INSERT INTO tarefas
        (titulo, concluida, prioridade, prazo, usuario_id)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (titulo, 0, prioridade, prazo, session["usuario_id"])
    )

    conexao.commit()
    print(f"Tempo do INSERT + COMMIT: {time.perf_counter() - inicio_consulta:.3f} segundos", flush=True)

    cursor.close()
    conexao.close()

    return redirect("/")


@app.route("/concluir/<int:id>", methods=["POST"])
def concluir(id):
    if "usuario_id" not in session:
        return redirect("/login")

    conexao = conectar_postgres()
    cursor = conexao.cursor()

    cursor.execute(
        "UPDATE tarefas SET concluida = 1 WHERE id = %s AND usuario_id = %s",
        (id, session["usuario_id"])
    )

    conexao.commit()
    cursor.close()
    conexao.close()

    return redirect("/")

@app.route("/reabrir/<int:id>", methods=["POST"])
def reabrir(id):
    if "usuario_id" not in session:
        return redirect("/login")

    conexao = conectar_postgres()
    cursor = conexao.cursor()

    cursor.execute(
        "UPDATE tarefas SET concluida = 0 WHERE id = %s AND usuario_id = %s",
        (id, session["usuario_id"])
    )

    conexao.commit()
    cursor.close()
    conexao.close()

    return redirect("/")

@app.route("/excluir/<int:id>", methods=["POST"])
def excluir(id):
    if "usuario_id" not in session:
        return redirect("/login")

    conexao = conectar_postgres()
    cursor = conexao.cursor()

    cursor.execute(
        "DELETE FROM tarefas WHERE id = %s AND usuario_id = %s",
        (id, session["usuario_id"])
    )

    conexao.commit()
    cursor.close()
    conexao.close()

    return redirect("/")

@app.route("/editar/<int:id>", methods=["POST"])
def editar(id):
    if "usuario_id" not in session:
        return redirect("/login")

    novo_titulo = request.form["titulo"].strip()
    nova_prioridade = request.form["prioridade"]
    novo_prazo = request.form["prazo"]

    if not novo_titulo:
        return redirect("/")

    if nova_prioridade not in ["Baixa", "Média", "Alta"]:
        nova_prioridade = "Média"

    conexao = conectar_postgres()
    cursor = conexao.cursor()

    cursor.execute(
        """
        UPDATE tarefas
        SET titulo = %s, prioridade = %s, prazo = %s
        WHERE id = %s AND usuario_id = %s
        """,
        (
            novo_titulo,
            nova_prioridade,
            novo_prazo,
            id,
            session["usuario_id"]
        )
    )

    conexao.commit()
    cursor.close()
    conexao.close()

    return redirect("/")

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")