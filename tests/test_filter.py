import bloop.filter
import pytest

from test_models import ComplexModel


@pytest.fixture
def query(engine):
    return bloop.filter.Filter(
        engine=engine, mode="query", model=ComplexModel, index=ComplexModel.by_email, strict=False,
        prefetch=3, consistent=True, forward=False, limit=4, key=(ComplexModel.name == "foo"),
        filter=(ComplexModel.email.contains("@")), select={ComplexModel.date})


def test_copy(query):
    # Use non-defaults so we don't get false positives on missing attributes
    same = query.copy()
    attrs = [
        "engine", "mode", "model", "index", "strict",
        "_prefetch", "_consistent", "_forward", "_limit", "_key", "_filter", "_select"]
    assert all(map(lambda a: (getattr(query, a) == getattr(same, a)), attrs))


# TODO test Filter.key
# TODO test Filter.select

def test_filter_not_condition(query):
    with pytest.raises(ValueError) as excinfo:
        query.filter("should be a condition")
    assert str(excinfo.value) == "Filter must be a condition or None"


def test_filter_none(query):
    """None is allowed, for clearing an existing filter"""
    assert query._filter is not None
    query.filter(None)
    assert query._filter is None


def test_filter_compound(query):
    new_condition = (ComplexModel.not_projected == "foo") & (ComplexModel.name.is_not(None))
    query.filter(new_condition)
    assert query._filter is new_condition


def test_consistent_gsi_raises(query):
    """Can't use consistent queries on a GSI"""
    query.index = ComplexModel.by_email

    with pytest.raises(ValueError) as excinfo:
        query.consistent(True)
    assert str(excinfo.value) == "Can't use ConsistentRead with a GlobalSecondaryIndex"

    with pytest.raises(ValueError):
        query.consistent(False)


def test_consistent(query):
    query.index = None
    new_value = not query._consistent
    query.consistent(new_value)
    assert query._consistent == new_value


def test_forward_scan(query):
    """Can't set forward on a scan"""
    query.mode = "scan"

    with pytest.raises(ValueError) as excinfo:
        query.forward(True)
    assert str(excinfo.value) == "Can't set ScanIndexForward for scan operations, only queries"

    with pytest.raises(ValueError):
        query.forward(False)


def test_forward(query):
    query.mode = "query"
    new_value = not query._forward
    query.forward(new_value)
    assert query._forward == new_value


@pytest.mark.parametrize("limit", [-5, None, object()])
def test_illegal_limit(query, limit):
    with pytest.raises(ValueError) as excinfo:
        query.limit(limit)
    assert str(excinfo.value) == "Limit must be a non-negative int"


@pytest.mark.parametrize("limit", [0, 3])
def test_limit(query, limit):
    query.limit(limit)
    assert query._limit == limit


@pytest.mark.parametrize("prefetch", [-5, None, object()])
def test_illegal_prefetch(query, prefetch):
    with pytest.raises(ValueError) as excinfo:
        query.prefetch(prefetch)
    assert str(excinfo.value) == "Prefetch must be a non-negative int"


@pytest.mark.parametrize("prefetch", [0, 3])
def test_prefetch(query, prefetch):
    query.prefetch(prefetch)
    assert query._prefetch == prefetch


# TODO test Filter.one
# TODO test Filter.first

def test_build_gsi_consistent_read(query):
    """Queries on a GSI can't be consistent"""
    query.index = ComplexModel.by_email
    # Can't use builder function - assume it was provided at __init__
    query._consistent = True
    prepared_request = query.build().prepared_request
    assert "ConsistentRead" not in prepared_request


def test_build_lsi_consistent_read(query):
    query.index = ComplexModel.by_joined
    # Can't use builder function - assume it was provided at __init__
    query.consistent(False)
    prepared_request = query.build().prepared_request
    assert prepared_request["ConsistentRead"] is False


def test_build_no_limit(query):
    query.limit(0)
    prepared_request = query.build().prepared_request
    assert "Limit" not in prepared_request


def test_build_limit(query):
    query.limit(4)
    prepared_request = query.build().prepared_request
    assert prepared_request["Limit"] == 4


def test_build_scan_forward(query):
    query.mode = "scan"
    # Can't have a key condition on scan
    query.key(None)

    prepared_request = query.build().prepared_request
    assert "ScanIndexForward" not in prepared_request


def test_build_query_forward(query):
    query.forward(False)
    prepared_request = query.build().prepared_request
    assert prepared_request["ScanIndexForward"] is False


def test_build_table_name(query):
    """TableName is always set"""
    # On an index...
    query.mode = "query"
    query.index = ComplexModel.by_email
    prepared_request = query.build().prepared_request
    assert prepared_request["TableName"] == ComplexModel.Meta.table_name

    # On the table...
    query.index = None
    prepared_request = query.build().prepared_request
    assert prepared_request["TableName"] == ComplexModel.Meta.table_name

    # On scan...
    query.mode = "scan"
    # Can't have a key condition on scan
    query.key(None)

    prepared_request = query.build().prepared_request
    assert prepared_request["TableName"] == ComplexModel.Meta.table_name


def test_build_no_index_name(query):
    """IndexName isn't set on table queries"""
    query.index = None
    prepared_request = query.build().prepared_request
    assert "IndexName" not in prepared_request


def test_build_index_name(query):
    query.index = ComplexModel.by_joined
    prepared_request = query.build().prepared_request
    assert prepared_request["IndexName"] == "by_joined"


def test_build_filter(query):
    condition = ComplexModel.email.contains("@")
    query.filter(condition)
    prepared_request = query.build().prepared_request
    # Filters are rendered first, so these name and value ids are stable
    assert prepared_request["FilterExpression"] == "(contains(#n0, :v1))"
    assert prepared_request["ExpressionAttributeNames"]["#n0"] == "email"
    assert prepared_request["ExpressionAttributeValues"][":v1"] == {"S": "@"}


def test_build_no_filter(query):
    query.filter(None)
    prepared_request = query.build().prepared_request
    assert "FilterExpression" not in prepared_request


def test_build_select_columns(query):
    query.select({ComplexModel.date})
    prepared_request = query.build().prepared_request
    assert prepared_request["Select"] == "SPECIFIC_ATTRIBUTES"
    assert prepared_request["ExpressionAttributeNames"]["#n2"] == "date"
    assert prepared_request["ProjectionExpression"] == "#n2"


def test_build_select_all(query):
    query.index = None
    query.select("all")
    prepared_request = query.build().prepared_request
    assert prepared_request["Select"] == "ALL_ATTRIBUTES"
    assert "ProjectionExpression" not in prepared_request


def test_build_select_projected(query):
    query.index = ComplexModel.by_email
    query.select("projected")
    prepared_request = query.build().prepared_request
    assert prepared_request["Select"] == "ALL_PROJECTED_ATTRIBUTES"
    assert "ProjectionExpression" not in prepared_request


def test_build_select_count(query):
    query.select("count")
    prepared_request = query.build().prepared_request
    assert prepared_request["Select"] == "COUNT"
    assert "ProjectionExpression" not in prepared_request


def test_build_query_no_key(query):
    # Bypass any validation on the key condition
    query.mode = "query"
    query._key = None

    with pytest.raises(ValueError) as excinfo:
        query.build()
    assert str(excinfo.value) == "Query must specify at least a hash key condition"


def test_build_query_key(query):
    query.mode = "query"
    query.key(ComplexModel.name == "foo")

    prepared_request = query.build().prepared_request
    assert prepared_request["KeyConditionExpression"] == "(#n3 = :v4)"
    assert prepared_request["ExpressionAttributeNames"]["#n3"] == "name"
    assert prepared_request["ExpressionAttributeValues"][":v4"] == {"S": "foo"}


def test_build_scan_no_key(query):
    query.mode = "scan"
    query.key(None)

    prepared_request = query.build().prepared_request
    assert "KeyConditionExpression" not in prepared_request


def test_build_scan_key(query):
    # Bypass any validation on the key condition
    query.mode = "scan"
    query._key = ComplexModel.name == "foo"

    with pytest.raises(ValueError) as excinfo:
        query.build()
    assert str(excinfo.value) == "Scan cannot have a key condition"


# TODO test FilterIterator.__iter__
# TODO test FilterIterator.count
# TODO test FilterIterator.scanned_count
# TODO test FilterIterator.reset

# import bloop
# import bloop.tracking
# import pytest
# import uuid
#
# from test_models import ComplexModel, User
#
#
# def test_hash_only_key(engine):
#     """ key calls for a model with no range key """
#
#     class Visit(bloop.new_base()):
#         hash = bloop.Column(bloop.String, hash_key=True)
#         non_key = bloop.Column(bloop.Integer)
#     engine.bind(base=Visit)
#     q = engine.query(Visit)
#
#     valid = [
#         # Basic equality
#         Visit.hash == "==",
#         # And with single argument
#         bloop.condition.And(Visit.hash == "And(==)")
#     ]
#
#     for condition in valid:
#         q.key(condition)
#
#     invalid = [
#         None,
#         bloop.condition.And(),
#
#         # Non-equality comparisons
#         Visit.hash < "<",
#         Visit.hash <= "<=",
#         Visit.hash > ">",
#         Visit.hash >= ">=",
#         Visit.hash != "!=",
#         # Non-equality in an And
#         bloop.condition.And(Visit.hash != "And(!=)"),
#
#         # Non-and groupings
#         bloop.condition.Not(Visit.hash == "Not(==)"),
#         bloop.condition.Or(Visit.hash == "Or(==)"),
#
#         # Non-comparison operators
#         Visit.hash.is_(None),
#         Visit.hash.is_not(None),
#         Visit.hash.between("between", "between"),
#         Visit.hash.in_(["in", "in"]),
#         Visit.hash.begins_with("begins_with"),
#         Visit.hash.contains("contains"),
#
#         # Path on hash
#         Visit.hash[0] == "path[0]",
#         Visit.hash["path"] == "path['path']",
#
#         # And with non key condition
#         ((Visit.hash == "and") & (Visit.non_key == "non_key")),
#         # And with multiple hash conditions
#         ((Visit.hash == "first") & (Visit.hash == "second")),
#         # And with only non key condition
#         (Visit.non_key == "non_key")
#     ]
#
#     for condition in invalid:
#         with pytest.raises(ValueError):
#             q.key(condition)
#
#
# def test_hash_range_key(engine):
#     """key calls for a model with hash and range keys"""
#
#     class Visit(bloop.new_base()):
#         hash = bloop.Column(bloop.String, hash_key=True)
#         range = bloop.Column(bloop.Integer, range_key=True)
#         non_key = bloop.Column(bloop.Integer)
#     engine.bind(base=Visit)
#     q = engine.query(Visit)
#
#     valid = [
#         # Basic equality
#         Visit.hash == "==",
#         # And with single argument
#         bloop.condition.And(Visit.hash == "And(==)"),
#         # Hash and valid range
#         ((Visit.hash == "hash") & (Visit.range == "range")),
#
#         # Valid range conditions
#         ((Visit.hash == "hash") & (Visit.range < "<")),
#         ((Visit.hash == "hash") & (Visit.range <= "<=")),
#         ((Visit.hash == "hash") & (Visit.range > ">")),
#         ((Visit.hash == "hash") & (Visit.range >= ">=")),
#         ((Visit.hash == "hash") & (Visit.range.between("range", "between"))),
#         ((Visit.hash == "hash") & (Visit.range.begins_with("begins_with"))),
#     ]
#
#     for condition in valid:
#         q.key(condition)
#
#     invalid = [
#         # Range only
#         Visit.range == "range",
#         bloop.condition.And(Visit.range == "And(range)"),
#
#         # Valid hash, invalid range
#         ((Visit.hash == "hash") & (Visit.range != "!= range")),
#         ((Visit.hash == "hash") & (~(Visit.range == "~(==range)"))),
#         ((Visit.hash == "hash") & (Visit.range.is_(None))),
#         ((Visit.hash == "hash") & (Visit.range.is_not(None))),
#         ((Visit.hash == "hash") & (Visit.range.contains("range contains"))),
#         ((Visit.hash == "hash") & (Visit.range.in_(["range", "in"]))),
#
#         # Valid hash, non key condition
#         ((Visit.hash == "hash") & (Visit.non_key == "non_key")),
#         ((Visit.hash == "hash") &
#          (Visit.range == "range") &
#          (Visit.non_key == "non_key")),
#
#         # Multiple hash conditions
#         ((Visit.hash == "hash") & (Visit.hash == "also hash")),
#
#         # Multiple range conditions
#         ((Visit.hash == "hash") &
#          (Visit.range == "range") &
#          (Visit.range == "also range")),
#         ((Visit.range == "range") & (Visit.range == "also range")),
#     ]
#
#     for condition in invalid:
#         with pytest.raises(ValueError):
#             q.key(condition)
#
#
# def test_filter(engine):
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#     condition = User.email == "foo@domain.com"
#
#     result = q.filter(condition).all()
#     expected = {
#         "ScanIndexForward": True,
#         "ConsistentRead": False,
#         "Select": "ALL_ATTRIBUTES",
#         "TableName": "User",
#         "ExpressionAttributeValues": {
#             ":v1": {"S": "foo@domain.com"},
#             ":v3": {"S": str(user_id)}},
#         "ExpressionAttributeNames": {"#n2": "id", "#n0": "email"},
#         "KeyConditionExpression": "(#n2 = :v3)",
#         "FilterExpression": "(#n0 = :v1)"}
#     assert result.request == expected
#
#
# def test_iterative_filter(engine):
#     """ iterative .filter should replace arguents """
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#     pcondition = User.email == "foo@domain.com"
#     vcondition = User.age == 100
#
#     result = q.filter(pcondition).filter(vcondition).all()
#     expected = {
#         "ExpressionAttributeNames": {"#n0": "age", "#n2": "id"},
#         "FilterExpression": "(#n0 = :v1)",
#         "ConsistentRead": False,
#         "TableName": "User",
#         "KeyConditionExpression": "(#n2 = :v3)",
#         "Select": "ALL_ATTRIBUTES",
#         "ScanIndexForward": True,
#         "ExpressionAttributeValues": {
#             ":v3": {"S": str(user_id)}, ":v1": {"N": "100"}}}
#     assert result.request == expected
#
#
# def test_invalid_select(engine):
#     q = engine.query(User)
#
#     invalid = [
#         "all_",
#         None,
#         {"foo", User.email},
#         set()
#     ]
#
#     for select in invalid:
#         with pytest.raises(ValueError):
#             q.select(select)
#
#
# def test_select_projected(engine):
#     # Can't use "projected" on query against table
#     user_id = uuid.uuid4()
#     mq = engine.query(User).key(User.id == user_id)
#     iq = engine.query(User.by_email).key(User.email == "foo@domain.com")
#
#     with pytest.raises(ValueError):
#         mq.select("projected")
#
#     # Index query sets Select -> ALL_PROJECTED_ATTRIBUTES
#     results = iq.select("projected").all()
#     expected = {
#         "ExpressionAttributeNames": {"#n0": "email"},
#         "Select": "ALL_PROJECTED_ATTRIBUTES",
#         "ScanIndexForward": True,
#         "TableName": "User",
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "IndexName": "by_email",
#         "ExpressionAttributeValues": {":v1": {"S": "foo@domain.com"}},
#         "ConsistentRead": False}
#     assert results.request == expected
#
#
# def test_select_all_invalid_gsi(engine):
#     """
#     Select all query on GSI without "all" projection
#     """
#     class Visit(bloop.new_base()):
#         page = bloop.Column(bloop.String, hash_key=True)
#         visitor = bloop.Column(bloop.Integer)
#         date = bloop.Column(bloop.DateTime)
#
#         by_date = bloop.GlobalSecondaryIndex(hash_key="date",
#                                              projection=["visitor"])
#     engine.bind(base=Visit)
#
#     q = engine.query(Visit.by_date)
#
#     with pytest.raises(ValueError):
#         q.select("all")
#
#
# def test_select_strict_lsi(engine):
#     """ Select all/specific on LSI without "all" projection in strict mode """
#     q = engine.query(ComplexModel.by_joined)
#
#     with pytest.raises(ValueError):
#         q.select("all")
#
#     with pytest.raises(ValueError):
#         q.select([ComplexModel.not_projected])
#
#
# def test_select_all_gsi(engine):
#     """
#     Select all query on GSI with "all" projection
#     """
#     q = engine.query(ComplexModel.by_email).key(ComplexModel.email == "foo")
#     result = q.select("all").all()
#     expected = {
#         "ScanIndexForward": True,
#         "IndexName": "by_email",
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ConsistentRead": False,
#         "Select": "ALL_ATTRIBUTES",
#         "ExpressionAttributeValues": {":v1": {"S": "foo"}},
#         "TableName": "CustomTableName",
#         "ExpressionAttributeNames": {"#n0": "email"}}
#     assert result.request == expected
#
#
# def test_select_specific(engine):
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#
#     result = q.select([User.email, User.joined]).all()
#     expected = {
#         "Select": "SPECIFIC_ATTRIBUTES",
#         "ExpressionAttributeNames": {"#n0": "email", "#n1": "j", "#n2": "id"},
#         "ScanIndexForward": True,
#         "ExpressionAttributeValues": {":v3": {"S": str(user_id)}},
#         "TableName": "User",
#         "KeyConditionExpression": "(#n2 = :v3)",
#         "ProjectionExpression": "#n0, #n1",
#         "ConsistentRead": False}
#     assert result.request == expected
#
#
# def test_select_specific_gsi_projection(engine):
#     """
#     When specific attrs are requested on a GSI without all attrs projected,
#     validate that the specific attrs are available through the GSI
#     """
#     class Visit(bloop.new_base()):
#         page = bloop.Column(bloop.String, hash_key=True)
#         visitor = bloop.Column(bloop.Integer)
#         date = bloop.Column(bloop.String)
#         not_projected = bloop.Column(bloop.Integer)
#         by_date = bloop.GlobalSecondaryIndex(hash_key="date",
#                                              projection=["visitor"])
#     engine.bind(base=Visit)
#
#     q = engine.query(Visit.by_date).key(Visit.date == "now")
#
#     # Invalid select because `not_projected` isn't projected into the index
#     with pytest.raises(ValueError):
#         q.select([Visit.not_projected])
#
#     result = q.select([Visit.visitor]).all()
#     expected = {
#         "ExpressionAttributeNames": {"#n0": "visitor", "#n1": "date"},
#         "TableName": "Visit",
#         "IndexName": "by_date",
#         "KeyConditionExpression": "(#n1 = :v2)",
#         "ConsistentRead": False,
#         "Select": "SPECIFIC_ATTRIBUTES",
#         "ScanIndexForward": True,
#         "ExpressionAttributeValues": {":v2": {"S": "now"}},
#         "ProjectionExpression": "#n0"}
#     assert result.request == expected
#
#
# def test_select_specific_lsi(engine):
#     key_condition = ComplexModel.name == "name"
#     key_condition &= (ComplexModel.joined == "now")
#     q = engine.query(ComplexModel.by_joined).key(key_condition)
#
#     # Unprojected attributes expect a full load, strict by default
#     with pytest.raises(ValueError):
#         q.select([ComplexModel.not_projected]).all()
#     # Unprojected is fine
#     engine.config["strict"] = False
#     result = q.select([ComplexModel.not_projected]).all()
#     assert set(result.expected) == set(ComplexModel.Meta.columns)
#
#     # All attributes projected
#     result = q.select([ComplexModel.email]).all()
#     assert set(result.expected).issubset(
#         ComplexModel.by_joined.projection_attributes)
#
#
# def test_count(engine):
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#
#     expected = {
#         "TableName": "User",
#         "ConsistentRead": False,
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "Select": "COUNT",
#         "ScanIndexForward": True}
#
#     def respond(request):
#         item = User(id=user_id, age=5)
#         return {
#             "Count": 1,
#             "ScannedCount": 2,
#             "Items": [engine._dump(User, item)]}
#     engine.client.query.side_effect = respond
#     count = q.count()
#     assert count == {"count": 1, "scanned_count": 2}
#     engine.client.query.assert_called_once_with(expected)
#
#
# def test_first(engine):
#     q = engine.scan(User).filter(User.email == "foo@domain.com")
#     expected = {
#         "ConsistentRead": False,
#         "Select": "ALL_ATTRIBUTES",
#         "TableName": "User",
#         "FilterExpression": "(#n0 = :v1)",
#         "ExpressionAttributeNames": {"#n0": "email"},
#         "ExpressionAttributeValues": {":v1": {"S": "foo@domain.com"}}}
#
#     def respond(request):
#         return {
#             "Count": 1,
#             "ScannedCount": 2,
#             "Items": [engine._dump(User, User(email="foo@domain.com"))]}
#     engine.client.scan.side_effect = respond
#     first = q.first()
#     assert first.email == "foo@domain.com"
#     engine.client.scan.assert_called_once_with(expected)
#
#
# def test_atomic_load(atomic):
#     """Querying objects in an atomic context caches the loaded condition"""
#     user_id = uuid.uuid4()
#     q = atomic.scan(User).filter(User.email == "foo@domain.com")
#
#     def respond(request):
#         item = User(id=user_id, email="foo@domain.com")
#         return {
#             "Count": 1,
#             "ScannedCount": 1,
#             "Items": [atomic._dump(User, item)]}
#     atomic.client.scan = respond
#     obj = q.first()
#
#     expected_condition = (
#         (User.age.is_(None)) &
#         (User.email == {"S": "foo@domain.com"}) &
#         (User.id == {"S": str(user_id)}) &
#         (User.joined.is_(None)) &
#         (User.name.is_(None)))
#     actual_condition = bloop.tracking.get_snapshot(obj)
#     assert expected_condition == actual_condition
#
#
# def test_iter(engine):
#     q = engine.scan(User).filter(User.email == "foo@domain.com").consistent
#     expected = {
#         "ConsistentRead": True,
#         "Select": "ALL_ATTRIBUTES",
#         "TableName": "User",
#         "FilterExpression": "(#n0 = :v1)",
#         "ExpressionAttributeNames": {"#n0": "email"},
#         "ExpressionAttributeValues": {":v1": {"S": "foo@domain.com"}}}
#
#     def respond(request):
#         assert request == expected
#         item = User(email="foo@domain.com")
#         return {
#             "Count": 1,
#             "ScannedCount": 2,
#             "Items": [engine._dump(User, item)]}
#     engine.client.scan = respond
#
#     results = list(q)
#     assert len(results) == 1
#     assert results[0].email == "foo@domain.com"
#
#
# def test_properties(engine):
#     """ ascending, descending, consistent """
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#
#     # ascending
#     result = q.ascending.all()
#     expected = {
#         "Select": "ALL_ATTRIBUTES",
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "ScanIndexForward": True,
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "TableName": "User",
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ConsistentRead": False}
#     assert result.request == expected
#
#     # descending
#     result = q.descending.all()
#     expected = {
#         "Select": "ALL_ATTRIBUTES",
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "ScanIndexForward": False,
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "TableName": "User",
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ConsistentRead": False}
#     assert result.request == expected
#
#     # consistent
#     result = q.consistent.all()
#     expected = {
#         "Select": "ALL_ATTRIBUTES",
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "ScanIndexForward": True,
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "TableName": "User",
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ConsistentRead": True}
#     assert result.request == expected
#
#
# def test_query_no_key(engine):
#     q = engine.query(User)
#     with pytest.raises(ValueError):
#         q.all()
#
#
# def test_query_consistent_gsi(engine):
#     q = engine.query(User.by_email).key(User.email == "foo")
#     with pytest.raises(ValueError):
#         q.consistent
#
#
# def test_results_incomplete(engine):
#     q = engine.query(User).key(User.id == uuid.uuid4())
#
#     def respond(request):
#         return {"Count": 1, "ScannedCount": 2}
#     engine.client.query.side_effect = respond
#
#     results = q.all()
#     assert not results.complete
#
#     with pytest.raises(RuntimeError):
#         results.results
#
#     list(results)
#     assert results.complete
#     assert not results.results
#
#     # Multiple iterations don't re-call the client
#     list(results)
#     assert engine.client.query.call_count == 1
#
#
# def test_first_no_prefetch(engine):
#     """
#     When there's no prefetch and a pagination token is presented,
#     .first should return a result from the first page, without being marked
#     complete.
#     """
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#     expected = {
#         "TableName": "User",
#         "ConsistentRead": False,
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "Select": "ALL_ATTRIBUTES",
#         "ScanIndexForward": True}
#     continue_tokens = {None: "first", "first": "second", "second": None}
#
#     def respond(request):
#         token = request.pop("ExclusiveStartKey", None)
#         assert request == expected
#         item = User(id=user_id, name=None)
#         return {
#             "Count": 1,
#             "ScannedCount": 2,
#             "Items": [engine._dump(User, item)],
#             "LastEvaluatedKey": continue_tokens[token]
#         }
#     engine.client.query.side_effect = respond
#     results = q.all()
#
#     assert results.first.name is None
#     # Second call doesn't fetch
#     assert results.first.name is None
#     assert not results.complete
#     assert engine.client.query.call_count == 1
#
#
# def test_first_no_results(engine):
#     """
#     When there's no prefetch and a pagination token is presented,
#     .first should return a result from the first page, without being marked
#     complete.
#     """
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#
#     def respond(request):
#         return {"Count": 1, "ScannedCount": 2}
#     engine.client.query.side_effect = respond
#
#     results = q.all()
#     with pytest.raises(ValueError):
#         results.first
#     # Subsequent results skip the stepping
#     with pytest.raises(ValueError):
#         results.first
#     assert engine.client.query.call_count == 1
#
#
# def test_prefetch_all(engine):
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#     expected = {
#         "TableName": "User",
#         "ConsistentRead": False,
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "Select": "ALL_ATTRIBUTES",
#         "ScanIndexForward": True}
#     continue_tokens = {None: "first", "first": "second", "second": None}
#
#     def respond(request):
#         token = request.pop("ExclusiveStartKey", None)
#         assert request == expected
#         result = {
#             "Count": 1,
#             "ScannedCount": 2,
#             "Items": [engine._dump(User, User(id=user_id, name=token))],
#             "LastEvaluatedKey": continue_tokens[token]}
#         next_token = continue_tokens.get(token, None)
#         if next_token:
#             result["LastEvaluatedKey"] = next_token
#         return result
#     engine.client.query.side_effect = respond
#
#     results = q.all(prefetch="all")
#
#     assert results.count == 3
#     assert results.scanned_count == 6
#     assert engine.client.query.call_count == 3
#
#
# def test_invalid_prefetch(engine):
#     q = engine.query(User).key(User.id == uuid.uuid4())
#     with pytest.raises(ValueError):
#         q.all(prefetch=-1)
#     with pytest.raises(ValueError):
#         q.all(prefetch="none")
#
#
# def test_prefetch_first(engine):
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#     expected = {
#         "TableName": "User",
#         "ConsistentRead": False,
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "Select": "ALL_ATTRIBUTES",
#         "ScanIndexForward": True}
#     continue_tokens = {None: "first", "first": None}
#
#     def respond(request):
#         token = request.pop("ExclusiveStartKey", None)
#         assert request == expected
#         result = {
#             "Count": 1,
#             "ScannedCount": 2,
#             "Items": [engine._dump(User, User(id=user_id, name=token))],
#             "LastEvaluatedKey": continue_tokens[token]}
#         next_token = continue_tokens.get(token, None)
#         if next_token:
#             result["LastEvaluatedKey"] = next_token
#         return result
#     engine.client.query.side_effect = respond
#
#     results = q.all(prefetch=1)
#
#     # Not iterated, no fetches
#     assert engine.client.query.call_count == 0
#     # First call fetches twice, even though a result
#     # is in the first response.
#     results.first
#     assert engine.client.query.call_count == 2
#
#
# def test_prefetch_iter(engine):
#     user_id = uuid.uuid4()
#     q = engine.query(User).key(User.id == user_id)
#     expected = {
#         "TableName": "User",
#         "ConsistentRead": False,
#         "KeyConditionExpression": "(#n0 = :v1)",
#         "ExpressionAttributeValues": {":v1": {"S": str(user_id)}},
#         "ExpressionAttributeNames": {"#n0": "id"},
#         "Select": "ALL_ATTRIBUTES",
#         "ScanIndexForward": True}
#     continue_tokens = {None: "first", "first": "second", "second": None}
#
#     def respond(request):
#         token = request.pop("ExclusiveStartKey", None)
#         assert request == expected
#         result = {
#             "Count": 1,
#             "ScannedCount": 2,
#             "Items": [engine._dump(User, User(id=user_id, name=token))],
#             "LastEvaluatedKey": continue_tokens[token]}
#         next_token = continue_tokens.get(token, None)
#         if next_token:
#             result["LastEvaluatedKey"] = next_token
#         return result
#     engine.client.query.side_effect = respond
#
#     results = q.all(prefetch=1)
#
#     # Not iterated, no fetches
#     assert engine.client.query.call_count == 0
#     # Exhaust the results
#     assert len(list(results)) == 3
#     # Only two continue tokens
#     assert engine.client.query.call_count == 3
