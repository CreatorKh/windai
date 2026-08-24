import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import DATA_DIR            # noqa: E402
from app.features import build_features    # noqa: E402
from app.loaders import Dataset, label_of  # noqa: E402
from app.scorecard import Scorecard        # noqa: E402


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return Dataset(DATA_DIR)


@pytest.fixture(scope="session")
def train_rows(dataset):
    apps = dataset.train()
    rows = [build_features(a, dataset.profile(a["applicant_id"])) for a in apps]
    labels = [label_of(a) for a in apps]
    return rows, labels


@pytest.fixture(scope="session")
def trained(train_rows) -> Scorecard:
    rows, labels = train_rows
    return Scorecard.fit(rows, labels, version="test", l2=3.0)
