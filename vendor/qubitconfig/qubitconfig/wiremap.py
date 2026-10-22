import json

class Wiremap:
    """
    Class containing wiremap definitions, to be
    loaded from json file (see examples/wiremap.json).
    Top level parameters are class attributes. LO frequencies
    (lofreq) strings are substituted according to LOs defined 
    in top level (e.g. lor, loq). 

    This should be a drop in replacement for wiremap.py in the
    qubic qchip configs
    """

    def __init__(self, cfg):
        """
        Parameters
        ----------
            cfg: either string or dict
                if string, path to wiremap json file
                else, wiremap dict loaded from json
        """
        if isinstance(cfg, str):
            with open(cfg) as f:
                cfg = json.load(f)

        replace_json_nones(cfg)
        
        for k, v in cfg.items():
            setattr(self, k, v)

        self._set_lofreq()

    def _set_lofreq(self):
        for k, v in self.lofreq.items():
            if isinstance(v, str) and hasattr(self, v):
                self.lofreq[k] = getattr(self, v)

def replace_json_nones(cfg):
    """
    Replace values in cfg dict that are (case insensitive) 'None' 
    strings with python NoneType; recurses through config in the 
    case of nested dicts. Note: input cfg will be MODIFIED

    Parameters
    ----------
        cfg : dict
    Returns
    -------
        dict : modified dictionary (note: original is also modified)
            
    """
    for k, v in cfg.items():
        if isinstance(v, str):
            if v.lower() == 'none':
                cfg[k] = None
        elif isinstance(v, dict):
            cfg[k] = replace_json_nones(v)

    return cfg
