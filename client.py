import subprocess as sp
import fcntl
import time
import shutil
from queue import Queue
from typing import Dict
from .message import *


class RPCClient:
    def __init__(self):
        self.process = sp.Popen(['clangd-11'], stdout=sp.PIPE, stdin=sp.PIPE, stderr=sp.PIPE)
        fcntl.fcntl(self.process.stdout.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
        self.incoming_log = open('incoming.log', 'wb')
        self.outgoing_log = open('outgoing.log', 'wb')
        self.buffer = bytearray()
        self.outgoing = Queue()
        self.terminating = False
        self.thread = threading.Thread(target=self.rpc_thread)
        self.thread.start()

    def send_message(self, msg: Message):
        self.outgoing.put(msg)

    def shutdown(self):
        if not self.terminating:
            self.process.stdin.close()
            self.process.wait(3)
            self.terminating = True
            self.thread.join()

    def rpc_thread(self):
        while not self.terminating:
            wait = True
            data = self.process.stdout.read(65536)
            if data:
                self.incoming_log.write(data)
                self.incoming_log.flush()
                wait = False
                self.buffer.extend(data)
                self.process_buffer()
            while not self.outgoing.empty():
                wait = False
                msg = self.outgoing.get()
                if not self.terminating:
                    data = serialize(msg.root)
                    self.outgoing_log.write(data)
                    self.outgoing_log.flush()
                    self.process.stdin.write(data)
                    self.process.stdin.flush()
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
            self.process_incoming(json.loads(text))

    def process_incoming(self, msg):
        raise RuntimeError("Not implemented")


class LSPClient(RPCClient):
    def __init__(self, root_folder, compile_commands_path: str = ''):
        super().__init__()
        if compile_commands_path:
            shutil.copy(compile_commands_path, root_folder)
        self.capabilities = {}
        self.initialized = False
        msg = InitMessage(root_folder)
        self.transactions: Dict[int, callable] = {msg.message_id: self.init_response}
        self.send_message(msg)
        self.diagnostic_callback = None
        self._open_files=set()
        wait_count = 0
        while not self.initialized:
            wait_count += 1
            time.sleep(0.1)
            if wait_count > 20:
                raise RuntimeError("Failed to initialize")

    def set_diagnostic_callback(self, callback: callable):
        self.diagnostic_callback = callback

    def process_incoming(self, msg):
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
        self.initialized = True

    def open_source_file(self, path):
        if path not in self._open_files:
            self._open_files.add(path)
            file = get_file(path)
            self.send_message(DidOpenMessage(path))
            return file
        return None

    def close_source_file(self, path):
        if path in self._open_files:
            self._open_files.remove(path)
            self.send_message(DidCloseMessage(path))

    def modify_source_file(self, path, content):
        file = get_file(path)
        file.update_content(content)
        self.send_message(DidChangeMessage(path))

    def request_completion(self, path: str, row: int, col: int, handler: callable):
        msg = CompletionMessage(path, row, col)
        self.transactions[msg.message_id] = handler
        self.send_message(msg)
