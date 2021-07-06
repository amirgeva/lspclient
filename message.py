import json
import os
import threading


def serialize(root: dict):
    text = json.dumps(root, separators=(',', ':'))
    payload = bytes(text, 'ascii')
    packet = bytearray()
    n = len(payload)
    packet.extend(bytes(f'Content-Length: {n}\r\n\r\n', 'ascii'))
    packet.extend(payload)
    return bytes(packet)


def uri(path):
    return f'file://{os.path.abspath(path)}'


class FileContent:
    def __init__(self, path: str):
        self.path = os.path.abspath(path)
        self.version = 1
        self.uri = uri(self.path)
        with open(self.path, 'r') as f:
            self.content = f.read()

    def update_content(self, content):
        self.content = content
        self.version += 1


_files_lock = threading.Lock()
_last_id = 0
_files = {}


def generate_id() -> int:
    global _last_id
    _last_id += 1
    return _last_id


def get_file(path: str):
    with _files_lock:
        if path in _files:
            return _files.get(path)
        file = FileContent(path)
        _files[path] = file
        return file


class Message:
    def __init__(self, method: str):
        self.root = {'jsonrpc': '2.0', 'method': method}
        self.params = {}
        self.root['params'] = self.params


class QueryMessage(Message):
    def __init__(self, method: str):
        super().__init__(method)
        self.message_id: int = generate_id()
        self.root['id'] = self.message_id


class InitMessage(QueryMessage):
    def __init__(self, root_folder):
        super().__init__('initialize')
        self.params['rootUri'] = uri(root_folder)
        self.params['processId'] = os.getpid()
        self.params["capabilities"] = {
            "textDocument": {"completion": {"completionItem": {"documentationFormat": ["plaintext"]}}}}


class InitializedMessage(Message):
    def __init__(self):
        super().__init__('initialized')


class DidOpenMessage(Message):
    def __init__(self, path: str):
        super().__init__('textDocument/didOpen')
        file: FileContent = get_file(path)
        doc = {'uri': file.uri,
               'languageId': 'cpp',
               'version': file.version,
               'text': file.content
               }
        self.params['textDocument'] = doc


class DidCloseMessage(Message):
    def __init__(self, path: str):
        super().__init__('textDocument/didClose')
        file: FileContent = get_file(path)
        self.params['textDocument'] = {'uri': file.uri}


class DidChangeMessage(Message):
    def __init__(self, path: str):
        super().__init__('textDocument/didChange')
        file: FileContent = get_file(path)
        self.params['textDocument'] = {
            'uri': file.uri,
            'version': file.version
        }
        self.params['contentChanges'] = [
            {'text': file.content}
        ]


class PositionalMessage(QueryMessage):
    def __init__(self, method: str, path: str, row: int, col: int):
        super().__init__(method)
        file: FileContent = get_file(path)
        self.params['textDocument'] = {'uri': file.uri}
        self.params['position'] = {'line': row, 'character': col}


class CompletionMessage(PositionalMessage):
    def __init__(self, path: str, row: int, col: int):
        super().__init__('textDocument/completion', path, row, col)


class SignatureHelpMessage(PositionalMessage):
    def __init__(self, path: str, row: int, col: int):
        super().__init__('textDocument/signatureHelp', path, row, col)


class DefinitionMessage(PositionalMessage):
    def __init__(self, path: str, row: int, col: int):
        super().__init__('textDocument/definition', path, row, col)


class ColoringMessage(QueryMessage):
    def __init__(self, path: str):
        super().__init__('textDocument/semanticTokens/full')
        file: FileContent = get_file(path)
        self.params['textDocument'] = {'uri': file.uri}
