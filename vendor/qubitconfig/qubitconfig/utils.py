import os
import json
from qubitconfig.wiremap import Wiremap
from qubitconfig.qchip import QChip

def load_chip(cal_repo_path, chip_name, qubit_cfg_file=None):
    """
    similar to envset but without env vars :)
    Also does not instantiate chassis object
    Copied from qubic repo. TODO: remove from qubic repo and refactor
    """
    chipcal_path = os.path.join(cal_repo_path, chip_name)
    with open(os.path.join(chipcal_path, 'instrument_cfg.json')) as f:
        toplevel_cfg = json.load(f)

    if qubit_cfg_file is None:
        qubit_cfg_file = toplevel_cfg['default_qubit_cfg']
    if not os.path.isabs(qubit_cfg_file):
        qubit_cfg_file = os.path.join(chipcal_path, qubit_cfg_file) 
    qchip = QChip(qubit_cfg_file)

    wiremap = Wiremap(os.path.abspath(os.path.join(chipcal_path, toplevel_cfg['wiremap'])))

    ip = toplevel_cfg['ip']

    instrument_cfg = {'wiremap': wiremap, 'ip': ip, 'chipcal_path': chipcal_path}
    
    if 'ctrl_system' in toplevel_cfg:
        instrument_cfg['ctrl_system'] = toplevel_cfg['ctrl_system']


    return qchip, instrument_cfg, qubit_cfg_file
