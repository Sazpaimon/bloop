import bloop.condition
import pytest


def test_render(engine, User):
    ''' render modes: condition, filter, key '''

    condition = User.age >= 3
    expected = {'ConditionExpression': '(#n0 >= :v1)',
                'ExpressionAttributeNames': {'#n0': 'age'},
                'ExpressionAttributeValues': {':v1': {'N': '3'}}}
    rendered = bloop.condition.render(engine, condition, "condition")
    assert expected == rendered


def test_duplicate_name_refs(renderer, User):
    ''' name refs are re-used for the same name '''
    assert renderer.name_ref(User.age) == renderer.name_ref(User.age) == "#n0"


def test_no_refs(renderer):
    '''
    when name/value refs are missing, ExpressionAttributeNames/Values
    aren't populated '''
    condition = bloop.condition.And()
    expected = {'ConditionExpression': '()'}
    assert renderer.render(condition, 'condition') == expected


def test_condition_ops(User):
    age, name = (User.age >= 3), (User.name == 'foo')

    and_condition = age & name
    assert and_condition.conditions == (age, name)
    assert isinstance(and_condition, bloop.condition.And)

    or_condition = age | name
    assert or_condition.conditions == (age, name)
    assert isinstance(or_condition, bloop.condition.Or)

    not_condition = ~age
    assert not_condition.condition is age
    assert isinstance(not_condition, bloop.condition.Not)

    assert len(age) == len(name) == 1


def test_condition_len(User):
    age, name = (User.age >= 3), (User.name == 'foo')
    and_condition = age & name
    or_condition = bloop.condition.And(age, name, age)
    not_condition = ~age

    assert len(or_condition) == 3
    assert len(and_condition) == 2
    assert len(age) == len(name) == len(not_condition) == 1


def test_multi_shortcut(renderer, User):
    ''' And or Or with single conditions render as their sole condition '''
    age = User.age >= 3
    condition = bloop.condition.And(age)
    expected = {'ConditionExpression': '(#n0 >= :v1)',
                'ExpressionAttributeNames': {'#n0': 'age'},
                'ExpressionAttributeValues': {':v1': {'N': '3'}}}
    assert renderer.render(condition, 'condition') == expected


def test_not(renderer, User):
    age = ~(User.age >= 3)
    condition = bloop.condition.And(age)
    expected = {'ConditionExpression': '(NOT (#n0 >= :v1))',
                'ExpressionAttributeNames': {'#n0': 'age'},
                'ExpressionAttributeValues': {':v1': {'N': '3'}}}
    assert renderer.render(condition, 'condition') == expected


def test_invalid_comparator(User):
    with pytest.raises(ValueError):
        bloop.condition.Comparison(User.age, 'foo', 5)


def test_attribute_exists(renderer, User):
    exists = User.age.is_not(None)
    not_exists = User.age.is_(None)

    expected_exists = {'ConditionExpression': '(attribute_exists(#n0))',
                       'ExpressionAttributeNames': {'#n0': 'age'}}
    expected_not_exists = {
        'ConditionExpression': '(attribute_not_exists(#n0))',
        'ExpressionAttributeNames': {'#n0': 'age'}}

    assert renderer.render(exists, 'condition') == expected_exists
    assert renderer.render(not_exists, 'condition') == expected_not_exists


def test_begins_with(renderer, User):
    condition = User.name.begins_with('foo')
    expected = {'ConditionExpression': '(begins_with(#n0, :v1))',
                'ExpressionAttributeNames': {'#n0': 'name'},
                'ExpressionAttributeValues': {':v1': {'S': 'foo'}}}
    assert renderer.render(condition, 'condition') == expected


def test_contains(renderer, User):
    condition = User.name.contains('foo')
    expected = {'ConditionExpression': '(contains(#n0, :v1))',
                'ExpressionAttributeNames': {'#n0': 'name'},
                'ExpressionAttributeValues': {':v1': {'S': 'foo'}}}
    assert renderer.render(condition, 'condition') == expected


def test_between(renderer, User):
    condition = User.name.between('bar', 'foo')
    expected = {'ConditionExpression': '(#n0 BETWEEN :v1 AND :v2)',
                'ExpressionAttributeNames': {'#n0': 'name'},
                'ExpressionAttributeValues': {':v1': {'S': 'bar'},
                                              ':v2': {'S': 'foo'}}}
    assert renderer.render(condition, 'condition') == expected


def test_in(renderer, User):
    condition = User.name.in_(['bar', 'foo'])
    expected = {'ConditionExpression': '(#n0 IN (:v1, :v2))',
                'ExpressionAttributeNames': {'#n0': 'name'},
                'ExpressionAttributeValues': {':v1': {'S': 'bar'},
                                              ':v2': {'S': 'foo'}}}
    assert renderer.render(condition, 'condition') == expected