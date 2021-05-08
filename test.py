#!/usr/bin/env python3
import os
import time

import client


def print_diags(msg):
    print("DIAG")
    print(msg)


def print_completion(msg):
    print(f"COMPLETION")
    res = msg.get('result')
    labels = []
    for item in res.get('items'):
        labels.append(item.get('filterText'))
    print(labels)


def test():
    root_folder = os.path.join(os.getcwd(), 'test')
    lsp = client.LSPClient(root_folder)
    lsp.set_diagnostic_callback(print_diags)
    main_path = os.path.join(root_folder, 'main.cpp')
    lsp.open_source_file(main_path)
    mod = open(os.path.join(root_folder, 'cmain.cpp')).read()
    lsp.modify_source_file(main_path, mod)
    time.sleep(1)
    lsp.request_completion(main_path, 32, 3, print_completion)
    input()
    lsp.close_source_file(main_path)
    time.sleep(0.1)
    lsp.shutdown()


def main():
    test()


if __name__ == '__main__':
    main()
