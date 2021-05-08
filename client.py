import subprocess as sp
import fcntl
import time
from queue import Queue
from typing import Dict

from message import *


class RPCClient:
    def __init__(self):
        self.process = sp.Popen(['clangd-11'], stdout=sp.PIPE, stdin=sp.PIPE)
        fcntl.fcntl(self.process.stdout.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
        self.buffer = bytearray()
        self.outgoing = Queue()
        self.incoming = Queue()
        self.terminating = False
        self.thread = threading.Thread(target=self.rpc_thread)

    def send_message(self, msg: Message):
        self.outgoing.put(msg)

    def shutdown(self):
        if not self.terminating:
            self.terminating = True
            self.thread.join()

    def rpc_thread(self):
        while not self.terminating:
            wait = True
            data = self.process.stdout.read(65536)
            if data:
                wait = False
                self.buffer.extend(data)
                self.process_buffer()
            while not self.outgoing.empty():
                wait = False
                msg = self.outgoing.get()
                self.process.stdin.write(serialize(msg))
            if wait:
                time.sleep(0.01)

    def process_buffer(self):
        while True:
            pos = self.buffer.find(b'Content-Length: ')
            if pos < 0:
                break
            end_pos = self.buffer.find(b'\r\n\r\n', pos + 16)
            if end_pos < 0:
                break
            length = int(self.buffer[pos + 16:end_pos].decode('ascii'))
            if len(self.buffer) < (end_pos + 4 + length):
                break
            msg = self.buffer[end_pos + 4:end_pos + 4 + length]
            del self.buffer[:end_pos + 4 + length]
            text = msg.decode('utf-8')
            self.incoming.put(json.loads(text))

    def process_incoming(self):
        raise RuntimeError("Not implemented")


class LSPClient(RPCClient):
    def __init__(self, root_folder):
        super().__init__()
        self.capabilities = {}
        msg = InitMessage(root_folder)
        self.transactions: Dict[int, callable] = {msg.message_id: self.init_response}
        self.send_message(msg)
        self.diagnostic_callback = None

    def set_diagnostic_callback(self, callback: callable):
        self.diagnostic_callback = callback

    def process_incoming(self):
        while not self.incoming.empty():
            msg = self.incoming.get()
            if 'id' in msg:
                message_id = msg.get('id')
                if message_id in self.transactions:
                    handler = self.transactions.get(message_id)
                    del self.transactions[message_id]
                    handler(msg)
            else:
                self.generic_handler(msg)

    def generic_handler(self, msg):
        if 'method' in msg:
            method = msg.get('method')
            if method == 'textDocument/publishDiagnostics' and self.diagnostic_callback is not None:
                self.diagnostic_callback(msg.get('params'))

    def init_response(self, msg):
        self.capabilities = msg.get('result').get('capabilities')
        self.send_message(InitializedMessage())

    def open_source_file(self, path):
        file = get_file(path)
        self.send_message(DidOpenMessage(path))
        return file

    def close_source_file(self, path):
        self.send_message(DidCloseMessage(path))

    def modify_source_file(self, path, content):
        file = get_file(path)
        file.update_content(content)
        self.send_message(DidChangeMessage(path))

    def request_completion(self, path: str, row: int, col: int, handler: callable):
        msg = CompletionMessage(path, row, col)
        self.transactions[msg.message_id] = handler
        self.send_message(msg)
