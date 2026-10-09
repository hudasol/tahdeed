from pathlib import Path

import pytest

from tahdeed.gazetteer import Gazetteer
from tahdeed.resolve import Resolver

FIXTURE = Path(__file__).parent / "fixtures" / "mini.sqlite"


@pytest.fixture(scope="session")
def gaz():
    return Gazetteer.load(FIXTURE)


@pytest.fixture(scope="session")
def resolver(gaz):
    from tahdeed.calibrate import HeuristicRanker

    return Resolver(gaz, ranker=HeuristicRanker())
