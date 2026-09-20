from flask import Flask, render_template, request, redirect, session
import sqlite3
from datetime import date
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "taskflow-chave-secreta"

conexao = sqlite3.connect("taskflow.db", check_same_thread=False)
cursor = conexao.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tarefas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo TEXT NOT NULL,
    concluida INTEGER NOT NULL DEFAULT 0
)
""")

conexao.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    senha TEXT NOT NULL
)
""")

conexao.commit()

try:
    cursor.execute("ALTER TABLE tarefas ADD COLUMN prioridade TEXT DEFAULT 'Média'")
    conexao.commit()
except sqlite3.OperationalError:
    pass

try:
    cursor.execute("ALTER TABLE tarefas ADD COLUMN usuario_id INTEGER")
    conexao.commit()
except sqlite3.OperationalError:
    pass

@app.route("/login")
def login():
    return render_template("login.html")

@app.route("/entrar", methods=["POST"])
def entrar():
    email = request.form["email"]
    senha = request.form["senha"]

    cursor.execute(
        "SELECT id, nome, email, senha FROM usuarios WHERE email = ?",
        (email,)
    )
    usuario = cursor.fetchone()

    if usuario and check_password_hash(usuario[3], senha):
        session["usuario_id"] = usuario[0]
        session["usuario_nome"] = usuario[1]
        return redirect("/")

    return "E-mail ou senha incorretos"

@app.route("/cadastro")
def cadastro():
    return render_template("cadastro.html")

@app.route("/cadastrar", methods=["POST"])
def cadastrar():
    nome = request.form["nome"]
    email = request.form["email"]
    senha = request.form["senha"]

    senha_hash = generate_password_hash(senha)

    cursor.execute(
        "INSERT INTO usuarios (nome, email, senha) VALUES (?, ?, ?)",
        (nome, email, senha_hash)
    )
    conexao.commit()

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
            "FROM tarefas WHERE concluida = 0 AND usuario_id = ? " + ordem,
            (usuario_id,)
        )

    elif status == "concluida":
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas WHERE concluida = 1 AND usuario_id = ? " + ordem,
            (usuario_id,)
        )

    elif status == "atrasada":
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas WHERE concluida = 0 AND prazo != '' AND prazo < ? AND usuario_id = ? " + ordem,
            (date.today().isoformat(), usuario_id)
        )

    else:
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas WHERE usuario_id = ? " + ordem,
            (usuario_id,)
        )

    tarefas = cursor.fetchall()

    cursor.execute(
        "SELECT COUNT(*) FROM tarefas WHERE concluida = 0 AND usuario_id = ?",
        (usuario_id,)
    )
    total_pendentes = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tarefas WHERE concluida = 1 AND usuario_id = ?",
        (usuario_id,)
    )
    total_concluidas = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tarefas "
        "WHERE concluida = 0 AND prazo != '' AND prazo < ? AND usuario_id = ?",
        (date.today().isoformat(), usuario_id)
    )
    total_atrasadas = cursor.fetchone()[0]

    return render_template(
        "index.html",
        tarefas=tarefas,
        hoje=date.today().isoformat(),
        total_pendentes=total_pendentes,
        total_concluidas=total_concluidas,
        total_atrasadas=total_atrasadas
    )

try:
    cursor.execute("ALTER TABLE tarefas ADD COLUMN prazo TEXT")
    conexao.commit()
except sqlite3.OperationalError:
    pass


@app.route("/adicionar", methods=["POST"])
def adicionar():
    titulo = request.form["titulo"]
    prioridade = request.form["prioridade"]
    prazo = request.form["prazo"]
    cursor.execute(
    "INSERT INTO tarefas (titulo, concluida, prioridade, prazo, usuario_id) VALUES (?, ?, ?, ?, ?)",
    (titulo, 0, prioridade, prazo, session["usuario_id"])
    )

    conexao.commit()

    return redirect("/")


@app.route("/concluir/<int:id>")
def concluir(id):
    if "usuario_id" not in session:
        return redirect("/login")

    cursor.execute(
        "UPDATE tarefas SET concluida = 1 WHERE id = ? AND usuario_id = ?",
        (id, session["usuario_id"])
    )
    conexao.commit()

    return redirect("/")

@app.route("/reabrir/<int:id>")
def reabrir(id):
    if "usuario_id" not in session:
        return redirect("/login")

    cursor.execute(
        "UPDATE tarefas SET concluida = 0 WHERE id = ? AND usuario_id = ?",
        (id, session["usuario_id"])
    )
    conexao.commit()

    return redirect("/")

@app.route("/excluir/<int:id>")
def excluir(id):
    if "usuario_id" not in session:
        return redirect("/login")

    cursor.execute(
        "DELETE FROM tarefas WHERE id = ? AND usuario_id = ?",
        (id, session["usuario_id"])
    )
    conexao.commit()

    return redirect("/")

@app.route("/editar/<int:id>", methods=["POST"])
def editar(id):
    if "usuario_id" not in session:
        return redirect("/login")

    novo_titulo = request.form["titulo"]
    nova_prioridade = request.form["prioridade"]
    novo_prazo = request.form["prazo"]

    cursor.execute(
        """
        UPDATE tarefas
        SET titulo = ?, prioridade = ?, prazo = ?
        WHERE id = ? AND usuario_id = ?
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

    return redirect("/")


def adicionar_tarefa():

    if "usuario_id" not in session:
        return redirect("/login")

    titulo = input("Digite o nome da tarefa: ")

    cursor.execute(
        "INSERT INTO tarefas (titulo, concluida) VALUES (?, ?)",
        (titulo, 0)
    )

    conexao.commit()

    print("\nTarefa adicionada com sucesso!\n")


def listar_tarefas():
    cursor.execute("SELECT id, titulo, concluida FROM tarefas")
    tarefas = cursor.fetchall()

    if len(tarefas) == 0:
        print("\nNenhuma tarefa cadastrada.\n")
        return

    print("\n--- TAREFAS ---")

    for tarefa in tarefas:
        status = "Concluída" if tarefa[2] == 1 else "Pendente"
        print(f"{tarefa[0]}. {tarefa[1]} - {status}")

    print()


def concluir_tarefa():
    listar_tarefas()

    numero = input("Digite o número da tarefa que deseja concluir: ")

    cursor.execute(
        "UPDATE tarefas SET concluida = 1 WHERE id = ?",
        (numero,)
    )

    conexao.commit()

    print("\nTarefa concluída com sucesso!\n")

def excluir_tarefa():
    listar_tarefas()

    numero = input("Digite o número da tarefa que deseja excluir: ")

    cursor.execute(
        "DELETE FROM tarefas WHERE id = ?",
        (numero,)
    )

    conexao.commit()

    print("\nTarefa excluída com sucesso!\n")
def editar_tarefa():
    listar_tarefas()

    numero = input("Digite o número da tarefa que deseja editar: ")
    novo_titulo = input("Digite o novo nome da tarefa: ")

    cursor.execute(
        "UPDATE tarefas SET titulo = ? WHERE id = ?",
        (novo_titulo, numero)
    )

    conexao.commit()

    print("\nTarefa editada com sucesso!\n")


if __name__ == "__main__":
    app.run(debug=True)