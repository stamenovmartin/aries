#!/usr/bin/env python3
"""R1b labels for the new NL2Bash sample: R1's labelling and adjudication code (thesis-r1-real-data/label.py,
adjudicate.py) unchanged, pointed at the R1b sample and at this folder's labels/.

    label_r1b.py label A|B      ->  labels/nl2bash-A.json, labels/nl2bash-B.json
    label_r1b.py adjudicate     ->  labels/nl2bash-agreement.json, labels/nl2bash-final.json

CLINC150 needs no new labels: its gold labels are R1's frozen per-intent labels (labels/clinc-final.json in R1)."""
import sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'thesis-r1-real-data'))
import common  # noqa: E402
import label as L  # noqa: E402
import adjudicate as A  # noqa: E402

LOCAL = common.DATA / 'r1b'
for module in (L, A):
    module.HERE, module.LOCAL = HERE, LOCAL

if __name__ == '__main__':
    (HERE / 'labels').mkdir(exist_ok=True)
    if sys.argv[1] == 'label':
        L.main('nl2bash', sys.argv[2])
    elif sys.argv[1] == 'adjudicate':
        A.main('nl2bash')
    else:
        raise SystemExit(__doc__)
