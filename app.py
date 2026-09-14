tarefas = []


def adicionar_tarefa():
    titulo = input("Digite o nome da tarefa: ")

    tarefa = {
        "titulo": titulo,
        "concluida": False
    }

    tarefas.append(tarefa)

    print("\nTarefa adicionada com sucesso!\n")


def listar_tarefas():
    if len(tarefas) == 0:
        print("\nNenhuma tarefa cadastrada.\n")
        return

    print("\n--- TAREFAS ---")

    for indice, tarefa in enumerate(tarefas, start=1):
        status = "Concluída" if tarefa["concluida"] else "Pendente"

        print(f"{indice}. {tarefa['titulo']} - {status}")

    print()

def concluir_tarefa():
    if len(tarefas) == 0:
        print("\nNenhuma tarefa cadastrada.\n")
        return

    listar_tarefas()

    numero = int(input("Digite o número da tarefa que deseja concluir: "))

    if numero < 1 or numero > len(tarefas):
        print("\nTarefa inválida.\n")
        return

    tarefas[numero - 1]["concluida"] = True

    print("\nTarefa concluída com sucesso!\n")

while True:
    print("=== TASKFLOW ===")
    print("1 - Adicionar tarefa")
    print("2 - Listar tarefas")
    print("3 - Concluir tarefa")
    print("0 - Sair")

    opcao = input("Escolha uma opção: ")

    if opcao == "1":
        adicionar_tarefa()

    elif opcao == "2":
        listar_tarefas()

    elif opcao == "3":
        concluir_tarefa()

    elif opcao == "0":
        print("TaskFlow encerrado.")
        break

    else:
        print("\nOpção inválida.\n")