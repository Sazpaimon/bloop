import arrow
import decimal
import pytest
import uuid

from bloop import types

from test_models import DocumentType


def symmetric_test(typedef, *pairs):
    """ Test any number of load/dump pairs for a symmetric `Type` instance """
    for (loaded, dumped) in pairs:
        assert typedef.dynamo_load(dumped, context={}) == loaded
        assert typedef.dynamo_dump(loaded, context={}) == dumped


def test_load_dump_best_effort():
    """can_* are not called when trying to load values"""

    class MyType(types.Type):
        backing_type = "FOO"
        python_type = float

    typedef = MyType()
    assert "not_a_float" == typedef._load({"NOT_FOO": "not_a_float"}, context={})
    assert {"FOO": "not_a_float"} == typedef._dump("not_a_float", context={})


def test_string():
    typedef = types.String()
    symmetric_test(typedef, ("foo", "foo"))


def test_uuid():
    typedef = types.UUID()
    uuid_obj = uuid.uuid4()
    uuid_str = str(uuid_obj)
    symmetric_test(typedef, (uuid_obj, uuid_str))


def test_datetime():
    typedef = types.DateTime()

    tz = "Europe/Paris"
    now = arrow.now()

    # Not a symmetric type
    assert typedef.dynamo_load(now.isoformat(), context={}) == now
    assert typedef.dynamo_dump(now, context={}) == now.to("utc").isoformat()

    assert now == typedef.dynamo_load(now.to(tz).isoformat(), context={})
    assert now.to("utc").isoformat() == typedef.dynamo_dump(now.to(tz), context={})

    # Should load values in the given timezone.
    # Because arrow objects compare equal regardless of timezone, we
    # isoformat each to compare the rendered strings (which preserve tz).
    local_typedef = types.DateTime(timezone=tz)
    loaded_as_string = local_typedef.dynamo_load(now.isoformat(), context={}).isoformat()
    now_with_tz_as_string = now.to(tz).isoformat()
    assert loaded_as_string == now_with_tz_as_string


def test_float():
    typedef = types.Float()
    d = decimal.Decimal
    symmetric_test(typedef, (1.5, "1.5"), (d(4)/d(3), "1.333333333333333333333333333"))


@pytest.mark.parametrize(
    "value, raises",
    [
        (decimal.Decimal(4/3), decimal.Inexact),
        (decimal.Decimal(10) ** 900, decimal.Overflow),
        (decimal.Decimal(0.9) ** 9000, decimal.Underflow),
        ("Infinity", TypeError),
        (decimal.Decimal("NaN"), TypeError)])
def test_float_errors(value, raises):
    with pytest.raises(raises):
        types.Float().dynamo_dump(value, context={})


def test_integer():
    """Integer is a thin wrapper over Float that exposes non-decimal objects"""
    typedef = types.Integer()
    symmetric_test(typedef, (4, "4"))

    assert typedef.dynamo_dump(4.5, context={}) == "4"
    assert typedef.dynamo_load("4", context={}) == 4

    # Corrupted data is truncated
    assert typedef.dynamo_load("4.5", context={}) == 4


def test_binary():
    typedef = types.Binary()
    symmetric_test(typedef, (b"123", "MTIz"), (bytes(1), "AA=="))


@pytest.mark.parametrize(
    "set_type, loaded, dumped", [
        (types.String, set(["Hello", "World"]), set(["Hello", "World"])),
        (types.Float, set([4.5, 3]), set(["4.5", "3"])),
        (types.Integer, set([0, -1, 1]), set(["0", "-1", "1"])),
        (types.Binary, set([b"123", b"456"]), set(["MTIz", "NDU2"]))], ids=str)
def test_sets(set_type, loaded, dumped):
    typedef = types.Set(set_type)
    assert typedef.dynamo_load(dumped, context={}) == loaded
    # Unordered compare
    assert set(typedef.dynamo_dump(loaded, context={})) == dumped


def test_set_type_instance():
    """Set can take an instance of a Type as well as a Type subclass"""
    type_instance = types.String()
    instance_set = types.Set(type_instance)
    assert instance_set.typedef is type_instance

    type_subclass = types.String
    subclass_set = types.Set(type_subclass)
    assert isinstance(subclass_set.typedef, type_subclass)


def test_set_illegal_backing_type():
    """The backing type for a set MUST be one of S/N/B, not BOOL"""
    for typedef in [types.Boolean, types.Set(types.Integer)]:
        with pytest.raises(TypeError) as excinfo:
            types.Set(typedef)
        assert "Set's typedef must be backed by" in str(excinfo.value)


@pytest.mark.parametrize("value", [1, True, object(), bool, "str", False, None, 0, set(), ""], ids=repr)
def test_bool(value):
    """Boolean will never store/load as empty - bool(None) is False"""
    typedef = types.Boolean()
    assert typedef.dynamo_dump(value, context={}) is bool(value)
    assert typedef.dynamo_load(value, context={}) is bool(value)


def test_list():
    typedef = types.List(types.UUID)
    loaded = [uuid.uuid4() for _ in range(5)]
    expected = [{"S": str(id)} for id in loaded]

    dumped = typedef.dynamo_dump(loaded, context={})
    assert dumped == expected
    assert typedef.dynamo_load(dumped, context={}) == loaded


@pytest.mark.parametrize("typedef", [types.List, types.Set, types.TypedMap])
def test_required_subtypes(typedef):
    """Typed containers require an inner type"""
    with pytest.raises(TypeError):
        typedef()


def test_load_dump_none():
    """Loading or dumping None returns None"""
    typedef = types.String()
    assert typedef._dump(None, context={}) == {"S": None}
    assert typedef._load({"S": None}, context={}) is None


def test_map_dump():
    """Map handles nested maps and custom types"""
    uid = uuid.uuid4()
    now = arrow.now().to('utc')
    loaded = {
        'Rating': 0.5,
        'Stock': 3,
        'Description': {
            'Heading': "Head text",
            'Body': "Body text",
            'Specifications': None
        },
        'Id': uid,
        'Updated': now
    }
    expected = {
        'Rating': {'N': '0.5'},
        'Stock': {'N': '3'},
        'Description': {
            'M': {
                'Heading': {'S': 'Head text'},
                'Body': {'S': 'Body text'}}},
        'Id': {'S': str(uid)},
        'Updated': {'S': now.isoformat()}
    }
    dumped = DocumentType.dynamo_dump(loaded, context={})
    assert dumped == expected


def test_map_load():
    """Map handles nested maps and custom types"""
    uid = uuid.uuid4()
    dumped = {
        'Rating': {'N': '0.5'},
        'Stock': {'N': '3'},
        'Description': {
            'M': {
                'Heading': {'S': 'Head text'},
                'Body': {'S': 'Body text'}}},
        'Id': {'S': str(uid)}
    }
    expected = {
        'Rating': 0.5,
        'Stock': 3,
        'Description': {
            'Heading': "Head text",
            'Body': "Body text",
            'Specifications': None
        },
        'Id': uid,
        'Updated': None
    }
    loaded = DocumentType.dynamo_load(dumped, context={})
    assert loaded == expected


def test_typedmap():
    """TypedMap handles arbitary keys and values"""
    typedef = types.TypedMap(types.DateTime)

    now = arrow.now().to('utc')
    later = now.replace(seconds=30)
    loaded = {
        'now': now,
        'later': later
    }
    dumped = {
        'now': {'S': now.isoformat()},
        'later': {'S': later.isoformat()}
    }
    assert typedef.dynamo_dump(loaded, context={}) == dumped
    assert typedef.dynamo_load(dumped, context={}) == loaded
