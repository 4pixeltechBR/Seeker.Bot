"""Mensagens que o modelo recebe. O banco só guarda o que aparece no chat."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str
    content: str = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str = ""
    name: str = ""


TOOL_SPECS: list[dict] = [
    {
        "name": "list_dir",
        "description": "Lista uma pasta do PC: usuário, D: ou E:. Vazio lista a pasta de trabalho.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Caminho da pasta. Vazio usa a pasta de trabalho.",
                }
            },
        },
    },
    {
        "name": "read_file",
        "description": "Lê o texto de um arquivo no PC. Use o caminho completo que find_files devolveu.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Caminho do arquivo."}
            },
            "required": ["path"],
        },
    },
    {
        "name": "find_files",
        "description": "Procura arquivos pelo nome na pasta do usuário e nos discos D: e E:. Não lê o conteúdo.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Parte do nome do arquivo."},
                "path": {"type": "string", "description": "Pasta onde procurar. Vazio procura em todas as áreas permitidas."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "run_command",
        "description": "Pede autorização e roda no terminal PowerShell. A pasta atual permanece entre comandos.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "O comando exato, em uma linha.",
                }
            },
            "required": ["command"],
        },
    },
    {
        "name": "schedule_task",
        "description": "Agenda uma tarefa. when_text é o que a pessoa disse, em português, com dia e hora.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "O que fazer."},
                "when_text": {
                    "type": "string",
                    "description": "Quando. Ex.: amanhã às 9h, toda segunda às 8h, daqui a 20 minutos.",
                },
            },
            "required": ["title", "when_text"],
        },
    },
    {
        "name": "create_routine",
        "description": "Cria uma rotina que roda sozinha no horário, só com leitura e pesquisa. when_text é o horário em português.",
        "parameters": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "O que fazer quando chegar a hora."},
                "when_text": {
                    "type": "string",
                    "description": "Quando. Ex.: todo dia útil às 8h, toda segunda às 8h.",
                },
            },
            "required": ["instruction", "when_text"],
        },
    },
    {
        "name": "list_routines",
        "description": "Lista as rotinas ativas.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_routine",
        "description": "Cancela uma rotina ativa.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Código ou parte da ordem."}},
            "required": ["query"],
        },
    },
    {
        "name": "list_tasks",
        "description": "Lista as tarefas pendentes.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "name": "complete_task",
        "description": "Marca uma tarefa como feita. Em tarefa recorrente, agenda a próxima.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Código ou parte do nome."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "cancel_task",
        "description": "Cancela uma tarefa pendente.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Código ou parte do nome."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "snooze_task",
        "description": "Adia uma tarefa pendente.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "minutes": {"type": "integer", "description": "Quantos minutos adiar."},
            },
            "required": ["query", "minutes"],
        },
    },
    {
        "name": "quiet_hours",
        "description": "Define o intervalo em que lembretes esperam. Ex.: 22h às 7h. Vazio tira o silêncio.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Intervalo, ou 'nenhum' para desligar."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "remember",
        "description": "Guarda uma preferência estável da pessoa para as próximas conversas.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "O fato, em uma frase."}
            },
            "required": ["text"],
        },
    },
    {
        "name": "forget",
        "description": "Apaga memórias que contenham o texto.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
        },
    },
]


def to_openai(messages: list[Message], tools: list[dict] | None) -> dict:
    payload_messages = []
    for message in messages:
        if message.role == "tool":
            payload_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
            continue
        item: dict = {"role": message.role, "content": message.content or None}
        if message.tool_calls:
            item["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": _json(call.arguments),
                    },
                }
                for call in message.tool_calls
            ]
        payload_messages.append(item)
    body: dict = {"messages": payload_messages}
    if tools:
        body["tools"] = [
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["parameters"],
                },
            }
            for spec in tools
        ]
        body["tool_choice"] = "auto"
    return body


def to_gemini(messages: list[Message], tools: list[dict] | None) -> dict:
    system = [message.content for message in messages if message.role == "system"]
    contents: list[dict] = []
    for message in messages:
        if message.role == "system":
            continue
        if message.role == "tool":
            part = {
                "functionResponse": {
                    "name": message.name,
                    "response": {"result": message.content},
                }
            }
            if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][-1]:
                contents[-1]["parts"].append(part)
            else:
                contents.append({"role": "user", "parts": [part]})
            continue
        parts: list[dict] = []
        if message.content:
            parts.append({"text": message.content})
        for call in message.tool_calls or []:
            parts.append({"functionCall": {"name": call.name, "args": call.arguments}})
        if not parts:
            continue
        role = "model" if message.role == "assistant" else "user"
        contents.append({"role": role, "parts": parts})
    body: dict = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if tools:
        body["tools"] = [
            {
                "functionDeclarations": [
                    {
                        "name": spec["name"],
                        "description": spec["description"],
                        "parameters": spec["parameters"],
                    }
                    for spec in tools
                ]
            }
        ]
    return body


def _json(value: dict) -> str:
    import json

    return json.dumps(value, ensure_ascii=False)
