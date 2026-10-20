"""Словари pyhyphen — в том /models: каталог словарей pyhyphen заменяется симлинком.

pyhyphen хранит скачанные словари в appdirs.user_data_dir("pyhyphen")
(hyphen.dictools.DEFAULT_DICT_PATH, у root — /root/.local/share/pyhyphen). Этот каталог
становится симлинком на каталог из аргумента (по умолчанию /models/hyphen); сам каталог
создаёт entrypoint при старте контейнера, когда том уже подключён.
Использование: python link_hyphen_dir.py /models/hyphen
"""

import os
import shutil
import sys

from hyphen import dictools

target = sys.argv[1] if len(sys.argv) > 1 else "/models/hyphen"
link = dictools.DEFAULT_DICT_PATH

if os.path.islink(link):
    os.unlink(link)
elif os.path.isdir(link):
    shutil.rmtree(link)
os.makedirs(os.path.dirname(link), exist_ok=True)
os.symlink(target, link)
print(f"pyhyphen: словари {link} -> {target}")
