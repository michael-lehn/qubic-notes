from importlib import metadata
try:
    __version__ = metadata.version('lbl-qubic')
except metadata.PackageNotFoundError:
    __version__ = None
