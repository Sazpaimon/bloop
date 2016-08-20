import boto3
import pytest

from unittest.mock import Mock
from bloop import Engine, BaseModel
from bloop.session import SessionWrapper


@pytest.fixture
def session():
    return Mock(spec=SessionWrapper)


@pytest.fixture
def engine(session):
    _engine = Engine(session=Mock(spec=boto3.Session))
    # Immediately replace that session wrapper
    _engine.session = session
    _engine.bind(base=BaseModel)
    return _engine