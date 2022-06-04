import struct


def flush_write(stream, data):
    pos = 0
    while pos < len(data):
        cur = stream.write(data[pos:])
        pos += cur
    stream.flush()


class BinaryLog:
    def __init__(self, filename: str):
        self._log_file = open(filename, 'wb')

    def add(self, data: bytes, tag: int):
        if self._log_file is not None:
            block = bytearray(8 + len(data))
            struct.pack_into('I', block, 0, tag)
            struct.pack_into('I', block, 4, len(data))
            block[8:] = data
            flush_write(self._log_file, block)

    def shutdown(self):
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None
