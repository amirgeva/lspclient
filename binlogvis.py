import re
import struct
import sys
import json
from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QMainWindow, QTextEdit, QDockWidget, QListWidget, QMessageBox

header_pattern = r'Content-Length: (\d+)\W\W\W\W'


def split_data(data: bytes) -> List[bytes]:
    res = []
    while len(data) > 0:
        s = data.decode('utf-8')
        m = re.match(header_pattern, s)
        if not m:
            raise RuntimeError("Invalid data")
        header_size = m.regs[0][1]
        data_size = int(m.groups()[0])
        if len(data) < (data_size + header_size):
            raise RuntimeError('Item size does not match header')
        res.append(data[0:(header_size + data_size)])
        data = data[(header_size + data_size):]
    return res


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(None)
        self.text = QTextEdit()
        self.setCentralWidget(self.text)
        dock = QDockWidget()
        self.item_list = QListWidget()
        dock.setWidget(self.item_list)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self.items = []
        self.item_list.currentItemChanged.connect(self.on_select)

    def load_items(self, path):
        with open(path, 'rb') as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(0, 0)
            pos = 0
            while pos < size:
                header = f.read(8)
                if len(header)!=8:
                    QMessageBox(self,'Error',"Failed to read header")
                direction, item_size = struct.unpack('II', header)
                print(f'{pos}: {item_size}')
                data = bytearray()
                left = item_size
                while left > 0:
                    cur = f.read(left)
                    data.extend(cur)
                    left -= len(cur)
                for item in split_data(data):
                    self.items.append((direction, item))
                pos += 8 + item_size
        self.update_list()

    def update_list(self):
        self.item_list.clear()
        index = 0
        for direction, item in self.items:
            dir_str = '>' if direction > 0 else '<'
            self.item_list.addItem(f'{dir_str} {index}')
            index += 1

    def on_select(self):
        index = self.item_list.currentRow()
        direction, data = self.items[index]
        s = data.decode('utf-8')
        m = re.match(header_pattern, s)
        if not m:
            QMessageBox.critical(self, 'Error', 'Invalid item header')
        else:
            header_size = m.regs[0][1]
            data_size = int(m.groups()[0])
            if len(data) != (data_size + header_size):
                self.text.setText(s)
                QMessageBox.critical(self, 'Error',
                                     f'Item size ({len(data)}) does not match header {data_size + header_size}')
            else:
                json_data = json.loads(s[header_size:])
                text = json.dumps(json_data, indent=4, sort_keys=True)
                self.text.setText(text)


def main():
    app = QApplication(sys.argv)
    mw = MainWindow()
    if len(sys.argv) > 1:
        mw.load_items(sys.argv[1])
    mw.show()
    app.exec_()


if __name__ == '__main__':
    main()
