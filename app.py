from flask import Flask, render_template, request, redirect, session
import psycopg2
import os
from dotenv import load_dotenv
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "chave-local-taskflow")

DATABASE_URL = os.environ.get("DATABASE_URL")

def conectar_postgres():
    return psycopg2.connect(DATABASE_URL)

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
def entrar():
    email = request.form["email"]
    senha = request.form["senha"]

    conexao = conectar_postgres()
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

@app.route("/cadastro")
def cadastro():
    return render_template("cadastro.html")

@app.route("/cadastrar", methods=["POST"])
def cadastrar():
    nome = request.form["nome"]
    email = request.form["email"]
    senha = request.form["senha"]

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

    cursor.execute(
        """
        INSERT INTO tarefas
        (titulo, concluida, prioridade, prazo, usuario_id)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (titulo, 0, prioridade, prazo, session["usuario_id"])
    )

    conexao.commit()
    cursor.close()
    conexao.close()

    return redirect("/")


@app.route("/concluir/<int:id>")
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

@app.route("/reabrir/<int:id>")
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

@app.route("/excluir/<int:id>")
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
    app.run(debug=True)