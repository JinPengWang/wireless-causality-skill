"""Inspect the invoked environment without installing or switching packages."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--expected-prefix');a=p.parse_args()
    if a.expected_prefix and Path(a.expected_prefix).resolve()!=Path(sys.prefix).resolve():
        p.error('Wrong interpreter prefix: '+sys.prefix)
    packages={}
    for name in ['numpy','pandas','scipy','openpyxl','matplotlib','tigramite']:
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]=None
    print(json.dumps({'executable':sys.executable,'prefix':sys.prefix,'python':sys.version,
                     'conda_environment':os.environ.get('CONDA_DEFAULT_ENV'),'packages':packages},indent=2))

if __name__=='__main__':main()
