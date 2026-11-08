"""Reuse existing scripts; explicit opt-in is required BEFORE any rebuild."""
import argparse
import os
import tempfile

from backend.mlops.definitions import ROOT,STAGES


def execute(stage):
    if stage not in STAGES:raise ValueError('Unknown stage')
    if os.environ.get('HUMSAFAR_ALLOW_PIPELINE_EXECUTION')!='1':
        raise RuntimeError('Rebuild blocked: review the plan, back up data, and explicitly set HUMSAFAR_ALLOW_PIPELINE_EXECUTION=1. No stage was executed.')
    temp=ROOT/'.local/tmp';temp.mkdir(parents=True,exist_ok=True)
    os.environ['TMP']=os.environ['TEMP']=str(temp)
    tempfile.tempdir=str(temp)
    if stage=='prepare':
        from backend.prepare_hawaii import prepare
        prepare() # Producer creates splits; consumers NEVER read test.csv.
    elif stage=='baselines':
        from backend.train_baselines import run
        run()
    elif stage=='mf':
        from backend.train_matrix_factorization import run
        run()
    elif stage=='bpr':
        from backend.train_bpr import run
        run()
    elif stage=='groups':
        from backend.evaluate_group_consensus import run
        run()
    elif stage=='catalog':
        from backend.build_catalog import build
        build()
    if stage in ['baselines','mf','bpr','groups']:
        from backend.mlops.tracking import track_existing
        track_existing(origin='executed_pipeline_stage',only=stage)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage',choices=list(STAGES))
    execute(parser.parse_args().stage)
