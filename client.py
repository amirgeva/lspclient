import subprocess as sp
import fcntl
import time
import shutil
import signal
import re
from io import TextIOWrapper, BufferedWriter
from queue import Queue
from typing import Dict, Tuple, Optional, IO, BinaryIO
from .binarylog import BinaryLog
from .message import *


def pretty(msg):
    return json.dumps(msg, indent=4, sort_keys=True)


def default_sigpipe():
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)


header_pattern = r'Content-Length: (\d+)\W'
msg_log: Optional[IO] = None  # open('msg.log', 'w')


def read_message(stream):
    header_data = stream.read(28)
    if header_data is None or len(header_data) == 0:
        return None
    m = re.match(header_pattern, header_data.decode('utf-8'))
    if not m:
        raise RuntimeError("Invalid packet")
    header_size = m.regs[0][1] + 3
    if msg_log:
        msg_log.write(f'header_size={header_size} ')
    data_size = int(m.groups()[0])
    orig_data_size = data_size
    if msg_log:
        msg_log.write(f'data_size={data_size}\n')
    accumulator = bytearray(header_data)
    if len(header_data) > header_size:
        data_size -= len(header_data) - header_size
    while data_size > 0:
        cur = stream.read(data_size)
        if msg_log:
            msg_log.write(f'read {len(cur)} bytes\n')
        accumulator.extend(cur)
        data_size -= len(cur)
    res = bytes(accumulator)
    if msg_log:
        notes = ''
        if len(res) != (header_size + orig_data_size):
            notes = '+++++++++++++++++++++++++++++'
        msg_log.write(
            f'Total message {len(res)} vs {header_size}+{orig_data_size} = {header_size + orig_data_size} {notes}\n')
        msg_log.flush()
    return res


class RPCClient:
    def __init__(self, enable_logging=False):
        self._process = sp.Popen(['clangd'], stdout=sp.PIPE, stdin=sp.PIPE,
                                 stderr=sp.PIPE)  # , preexec_fn=default_sigpipe)
        # self.process = sp.Popen(['ccls'], stdout=sp.PIPE, stdin=sp.PIPE, stderr=sp.PIPE)
        fcntl.fcntl(self._process.stdout.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
        fcntl.fcntl(self._process.stderr.fileno(), fcntl.F_SETFL, os.O_NONBLOCK)
        self._rpc_log: Optional[TextIOWrapper] = None
        self._bin_log:Optional[BinaryLog] = None
        if enable_logging:
            self._rpc_log = open('rpc.log', 'w')
            self._bin_log = BinaryLog('rpc_session.bin')
        self._buffer = bytearray()
        self._outgoing = Queue()
        self._terminating = False
        self._thread = threading.Thread(target=self.rpc_thread)
        self._thread.start()

    def add_log(self, out: bool, text: str):
        if self._rpc_log:
            out_prefix = '>>>' if out else '<<<'
            prefix = f'\n{out_prefix}  {time.time()}\n'
            self._rpc_log.write(prefix)
            self._rpc_log.write(text)
            self._rpc_log.write('\n')
            self._rpc_log.flush()

    def send_message(self, msg: Message):
        # self.add_log(True, pretty(msg.root))
        self._outgoing.put(msg)

    def shutdown(self):
        if not self._terminating:
            try:
                self._process.stdin.close()
                self._process.wait(3)
            except sp.TimeoutExpired:
                pass
            self._terminating = True
            self._thread.join()

    def rpc_thread(self):
        # fb = open('rpc_out.log', 'wb')
        fi : Optional[BinaryIO] = None
        if self._rpc_log:
            fi = open('rpc_in.log', 'wb')
        try:
            while not self._terminating:
                wait = True
                data = self._process.stderr.read(65536)
                if data:
                    self.add_log(False, data.decode('utf-8'))
                data = read_message(self._process.stdout)
                if data:
                    if fi:
                        fi.write(data)
                        fi.flush()
                    wait = False
                    if msg_log:
                        msg_log.write(f'Writing to bin log {len(data)} incoming bytes\n')
                    if self._bin_log:
                        self._bin_log.add(data, 0)
                    self._buffer.extend(data)
                    self.process_buffer()
                while not self._outgoing.empty():
                    wait = False
                    msg = self._outgoing.get()
                    if not self._terminating:
                        data = serialize(msg.root)
                        if msg_log:
                            msg_log.write(f'Writing to bin log {len(data)} outgoing bytes\n')
                        if self._bin_log:
                            self._bin_log.add(data, 1)
                        self._process.stdin.write(data)
                        self._process.stdin.flush()
                if wait:
                    time.sleep(0.01)
        except ValueError:
            pass

    def process_buffer(self):
        while True:
            pos = self._buffer.find(b'Content-Length: ')
            if pos < 0:
                break
            end_pos = self._buffer.find(b'\r\n\r\n', pos + 16)
            if end_pos < 0:
                break
            length = int(self._buffer[pos + 16:end_pos].decode('ascii'))
            if len(self._buffer) < (end_pos + 4 + length):
                break
            msg = self._buffer[end_pos + 4:end_pos + 4 + length]
            del self._buffer[:end_pos + 4 + length]
            text = msg.decode('utf-8')
            json_msg = json.loads(text)
            # self.add_log(False, pretty(json_msg))
            self.process_incoming(json_msg)

    def process_incoming(self, msg):
        raise RuntimeError("Not implemented")


class LSPClient(RPCClient):
    def __init__(self, root_folder, compile_commands_path: str = '', enable_logging=False):
        super().__init__(enable_logging)
        if compile_commands_path:
            shutil.copy(compile_commands_path, root_folder)
        self.capabilities = {}
        self.initialized = False
        msg = InitMessage(root_folder)
        self.transactions: Dict[str, callable] = {msg.message_id: self.init_response}
        self.send_message(msg)
        self.diagnostic_callback = None
        self._open_files = set()
        self._semantic_tokens: List[str] = []
        self._semantic_modifiers: List[str] = []
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

    def handle_capabilities(self):
        if 'semanticTokensProvider' in self.capabilities:
            semantic = self.capabilities.get('semanticTokensProvider')
            if 'legend' in semantic:
                legend = semantic.get('legend')
                self._semantic_modifiers = legend.get("tokenModifiers")
                self._semantic_tokens = legend.get("tokenTypes")

    def init_response(self, msg):
        self.capabilities = msg.get('result').get('capabilities')
        self.handle_capabilities()
        self.send_message(InitializedMessage())
        self.initialized = True

    def is_open_file(self, path):
        return path in self._open_files

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

    def modify_source_line(self, path: str, row: int, text: str):
        file = get_file(path)
        if file.update_content_line(row, text):
            self.send_message(DidChangeMessage(path, [row]))

    def modify_source_file(self, path: str, content: str):
        file = get_file(path)
        if file.update_content(content):
            self.send_message(DidChangeMessage(path, []))

    def request_completion(self, path: str, row: int, col: int, handler: callable):
        msg = CompletionMessage(path, row, col)
        self.transactions[msg.message_id] = handler
        self.send_message(msg)

    def request_coloring(self, path: str, prev_id: str, handler: callable):
        msg = ColoringMessage(path, prev_id)
        self.transactions[msg.message_id] = handler
        self.send_message(msg)

    def get_coloring_legend(self) -> Tuple[List[str], List[str]]:
        return self._semantic_tokens, self._semantic_modifiers

    def request_definition(self, path: str, row: int, col: int, handler: callable):
        msg = DefinitionMessage(path, row, col)
        self.transactions[msg.message_id] = handler
        self.send_message(msg)
