"""Descriptor-relative operations: no symlink traversal during the actual syscall."""
import os
from pathlib import Path


def open_nofollow(path, flags, mode=0o600):
    path = Path(path).absolute()
    directory = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        return os.open(path.name, flags | os.O_NOFOLLOW, mode, dir_fd=directory)
    finally:
        os.close(directory)
