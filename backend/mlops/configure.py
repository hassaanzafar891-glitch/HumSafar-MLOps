"""Generate declarations only; preserve an existing interpreter override."""
import json
import yaml
from backend.mlops.definitions import ROOT,pipeline_document,validate_layout


def main():
    document=pipeline_document()
    document['vars']=['params.yaml']
    (ROOT/'dvc.yaml').write_text(yaml.safe_dump(document,sort_keys=False),encoding='utf-8')
    if not (ROOT/'params.yaml').exists():
        (ROOT/'params.yaml').write_text(yaml.safe_dump({'runtime':{'python':'python'}},sort_keys=False),encoding='utf-8')
    print(json.dumps(validate_layout(document),indent=2))


if __name__=='__main__':main()
