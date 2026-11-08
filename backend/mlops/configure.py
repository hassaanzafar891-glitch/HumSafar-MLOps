"""Generate DVC declarations without executing or reading a held-out split."""
import json
import yaml
from backend.mlops.definitions import ROOT,pipeline_document,validate_layout


def main():
    document=pipeline_document()
    document['vars']=['params.yaml']
    (ROOT/'dvc.yaml').write_text(yaml.safe_dump(document,sort_keys=False),encoding='utf-8')
    (ROOT/'params.yaml').write_text(yaml.safe_dump({'runtime':{'python':'.venv/Scripts/python.exe'}},sort_keys=False),encoding='utf-8')
    print(json.dumps(validate_layout(document),indent=2))


if __name__=='__main__':main()
