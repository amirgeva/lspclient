import json
import os
import threading
from typing import List


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


def clamp(n, min_val, max_val):
    return max(min_val, min(n, max_val))


class FileContent:
    def __init__(self, path: str):
        self._path = os.path.abspath(path)
        self._version = 1
        self._uri = uri(self._path)
        self._content: List[str] = []
        with open(self._path, 'r') as f:
            self._content = [line.rstrip() for line in f.readlines()]

    @property
    def uri(self):
        return self._uri

    @property
    def version(self):
        return self._version

    @property
    def content(self):
        return '\n'.join(self._content)

    def update_content_line(self, row: int, text: str):
        if 0 <= row < len(self._content):
            self._content[row] = text
            self._version += 1
            return True
        return False

    def get_rows_text(self, start: int, end: int):
        n = len(self._content)
        if n == 0:
            return []
        start = clamp(start, 0, n - 1)
        end = clamp(end, 0, n - 1)
        return self._content[start:(end + 1)]

    def update_content(self, value):
        if isinstance(value, str):
            self._content = value.split('\n')
        elif isinstance(value, list):
            self._content = value
        else:
            raise RuntimeError("Invalid content")
        self._version += 1


_files_lock = threading.Lock()
_last_id = 0
_files = {}


def generate_id() -> str:
    global _last_id
    _last_id += 1
    return str(_last_id)


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


# noinspection PyTypeChecker
class QueryMessage(Message):
    def __init__(self, method: str):
        super().__init__(method)
        self.message_id: str = generate_id()
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
    def __init__(self, path: str, rows: List[int]):
        super().__init__('textDocument/didChange')
        file: FileContent = get_file(path)
        self.params['textDocument'] = {
            'uri': file.uri,
            'version': file.version
        }
        details = {}
        if len(rows) == 0:
            details['text'] = file.content
        else:
            rows_text: List[str] = file.get_rows_text(rows[0], rows[-1])
            details['range'] = {
                'start': {'line': rows[0], 'character': 0},
                'end': {'line': rows[-1]+1, 'character': 0}
            }
            details['text'] = '\n'.join(rows_text)+'\n'
        self.params['contentChanges'] = [details]


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
    def __init__(self, path: str, prev_id: str):
        super().__init__(f'textDocument/semanticTokens/full{"/delta" if prev_id else ""}')
        file: FileContent = get_file(path)
        self.params['textDocument'] = {'uri': file.uri}
        if prev_id:
            self.params['previousResultId'] = prev_id
