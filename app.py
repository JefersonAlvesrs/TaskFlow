from flask import Flask, render_template, request, redirect
import sqlite3
from datetime import date

app = Flask(__name__)

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

try:
    cursor.execute("ALTER TABLE tarefas ADD COLUMN prioridade TEXT DEFAULT 'Média'")
    conexao.commit()
except sqlite3.OperationalError:
    pass


@app.route("/")
def home():
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
            "FROM tarefas WHERE concluida = 0 " + ordem
        )
    elif status == "concluida":
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas WHERE concluida = 1 " + ordem
        )

    elif status == "atrasada":
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas WHERE concluida = 0 AND prazo != '' AND prazo < ? " + ordem,
            (date.today().isoformat(),)
        )
    
    else:
        cursor.execute(
            "SELECT id, titulo, concluida, prioridade, prazo "
            "FROM tarefas " + ordem
        )

    tarefas = cursor.fetchall()

    cursor.execute("SELECT COUNT(*) FROM tarefas WHERE concluida = 0")
    total_pendentes = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM tarefas WHERE concluida = 1")
    total_concluidas = cursor.fetchone()[0]

    cursor.execute(
        "SELECT COUNT(*) FROM tarefas WHERE concluida = 0 AND prazo != '' AND prazo < ?",
        (date.today().isoformat(),)
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
    "INSERT INTO tarefas (titulo, concluida, prioridade, prazo) VALUES (?, ?, ?, ?)",
    (titulo, 0, prioridade, prazo)
)

    conexao.commit()

    return redirect("/")


@app.route("/concluir/<int:id>")
def concluir(id):
    cursor.execute(
        "UPDATE tarefas SET concluida = 1 WHERE id = ?",
        (id,)
    )

    conexao.commit()

    return redirect("/")

@app.route("/reabrir/<int:id>")
def reabrir(id):
    cursor.execute(
        "UPDATE tarefas SET concluida = 0 WHERE id = ?",
        (id,)
    )

    conexao.commit()

    return redirect("/")

@app.route("/excluir/<int:id>")
def excluir(id):
    cursor.execute(
        "DELETE FROM tarefas WHERE id = ?",
        (id,)
    )

    conexao.commit()

    return redirect("/")

@app.route("/editar/<int:id>", methods=["POST"])
def editar(id):
    novo_titulo = request.form["titulo"]
    nova_prioridade = request.form["prioridade"]
    novo_prazo = request.form["prazo"]

    cursor.execute(
        "UPDATE tarefas SET titulo = ?, prioridade = ?, prazo = ? WHERE id = ?",
        (novo_titulo, nova_prioridade, novo_prazo, id)
    )

    conexao.commit()

    return redirect("/")

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


def adicionar_tarefa():
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