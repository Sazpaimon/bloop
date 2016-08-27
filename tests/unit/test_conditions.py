import operator
import pytest

from bloop.conditions import (
    ComparisonMixin,
    BaseCondition,
    Condition,
    AndCondition,
    OrCondition,
    NotCondition,
    BeginsWithCondition,
    BetweenCondition,
    ComparisonCondition,
    ContainsCondition,
    InCondition,
    InvalidCondition,
    get_marked,
    get_snapshot,
    iter_conditions,
    object_deleted,
    object_loaded,
    object_saved
)

from ..helpers.models import User


class MockColumn(ComparisonMixin):
    """Has a repr for testing condition reprs"""
    def __init__(self, name):
        self.model_name = name
        # Mock model so this can render as M.name
        self.model = type("M", tuple(), {})
        super().__init__()

    def _repr_with_path(self, path):
        return self.model_name

c = MockColumn("c")
d = MockColumn("d")


def condition_for(operation):
    return conditions_for(operation)[0]


def conditions_for(*operations):
    column = MockColumn("c")
    value = 0
    values = [1, 2]
    conditions = []
    if None in operations:
        conditions.append(Condition())
    if "and" in operations:
        left = ComparisonCondition("==", column, value)
        right = ComparisonCondition("!=", column, value)
        conditions.append(AndCondition(left, right))
    if "or" in operations:
        left = ComparisonCondition("==", column, value)
        right = ComparisonCondition("!=", column, value)
        conditions.append(OrCondition(left, right))
    if "not" in operations:
        inner = ComparisonCondition("==", column, value)
        conditions.append(NotCondition(inner))
    if "begins_with" in operations:
        conditions.append(BeginsWithCondition(column, value))
    if "between" in operations:
        conditions.append(BetweenCondition(column, *values))
    if "contains" in operations:
        conditions.append(ContainsCondition(column, value))
    if "in" in operations:
        conditions.append(InCondition(column, values))
    for operation in ("<", "<=", ">", ">=", "!=", "=="):
        if operation in operations:
            conditions.append(ComparisonCondition(operation, column, value))
    return conditions


def non_meta_conditions():
    return conditions_for(
        "begins_with", "between", "contains", "in",
        ">", "<", ">=", "<=", "==", "!="
    )


def meta_conditions():
    return conditions_for("and", "or", "not")


def empty_conditions():
    return [Condition(), AndCondition(), OrCondition(), NotCondition(Condition())]


# NEW CONDITION ======================================================================================== NEW CONDITION


def test_abstract_base():
    """BaseCondition requires 4 methods for subclasses"""
    condition = BaseCondition(None)
    with pytest.raises(NotImplementedError):
        len(condition)
    with pytest.raises(NotImplementedError):
        repr(condition)
    with pytest.raises(NotImplementedError):
        condition.iter_columns()
    with pytest.raises(NotImplementedError):
        condition.render(None)


def test_empty_condition():
    assert Condition().operation is None


@pytest.mark.parametrize("condition", empty_conditions())
def test_len_empty(condition):
    assert len(condition) == 0


def test_iter_empty():
    condition = Condition()
    assert next(condition.iter_columns(), None) is None


def test_render_empty():
    condition = Condition()
    with pytest.raises(InvalidCondition):
        condition.render(None)


@pytest.mark.parametrize("condition", non_meta_conditions())
def test_len_non_empty(condition):
    assert len(condition) == 1


@pytest.mark.parametrize("condition", non_meta_conditions())
def test_len_non_meta(condition):
    """Non-meta conditions *must* have exactly 1 condition"""
    assert len(condition) == 1


@pytest.mark.parametrize("condition", meta_conditions())
def test_len_meta(condition):
    if condition.operation == "not":
        assert len(condition) == 1
    else:
        assert len(condition) == 2


def test_len_cyclic():
    """Cyclic conditions count the cyclic reference"""
    # Here's the structure to create:
    #   root
    #  /    \
    # a      b
    #      /   \
    #     c   root
    root = AndCondition()
    a = ComparisonCondition("<", MockColumn("a"), 3)
    b = OrCondition()
    c = ComparisonCondition(">", MockColumn("c"), 3)
    root.values.extend([a, b])
    b.values.extend([c, root])

    assert len(root) == 4


def test_len_unpack_not():
    """Even though not(not(x)) -> x shouldn't exist, its length should be the inner length"""
    lt, gt = conditions_for("<", ">")
    outer = NotCondition(lt)
    condition = NotCondition(outer)
    assert len(condition) == len(outer) == 1

    # Swap inner for an AND with length 2
    and_ = AndCondition(lt, gt)
    outer.values[0] = and_
    assert len(condition) == len(outer) == len(and_) == 2


@pytest.mark.parametrize("condition", non_meta_conditions())
def test_iter_non_meta(condition):
    """These conditions aren't and/or/not, so they can't yield any inner conditions"""
    assert next(iter_conditions(condition), None) is None


@pytest.mark.parametrize("condition", meta_conditions())
def test_iter_non_cyclic_meta(condition):
    """Yield the inner conditions for each of these meta conditions"""
    expected = condition.values
    actual = list(iter_conditions(condition))
    assert actual == expected


def test_iter_cyclic():
    """Cyclic conditions can be iterated safely"""
    # Here's the structure to create:
    #   root
    #  /    \
    # a      b
    #      /   \
    #     c   root
    root = AndCondition()
    a = ComparisonCondition("<", MockColumn("a"), 3)
    b = OrCondition()
    c = ComparisonCondition(">", MockColumn("c"), 3)
    root.values.extend([a, b])
    b.values.extend([c, root])

    expected = {root, a, b, c}
    actual = set(iter_conditions(root))
    assert actual == expected


@pytest.mark.parametrize("condition", conditions_for(
    "begins_with", "between", "contains", "in",
    ">", "<", ">=", "<=", "==", "!=",
    "and", "or"))
def test_invert_wraps(condition):
    """everything but not and () are wrapped in a not"""
    wrapped = ~condition
    assert wrapped.operation == "not"
    assert wrapped.values[0] is condition


def test_invert_empty():
    """~() -> ()"""
    empty = Condition()
    assert (~empty) is empty


def test_invert_simplifies():
    """~~x -> x"""
    condition = ComparisonCondition(">", MockColumn("c"), 3)
    assert (~~condition) is condition


def test_invert_empty_not():
    """~not() -> ()"""
    condition = condition_for("not")
    assert (~condition).operation == condition.values[0].operation


# NEW CONDITION AND/IAND ====================================================================== NEW CONDITION AND/IAND


@pytest.mark.parametrize("empty", empty_conditions())
def test_and_empty_conditions(empty):
    """When conditions are falsey (literal empty or meta with no inner value), simplify instead of nesting:
    ()_1 & ()_2 -> ()_1
    x & () -> x
    () & x -> x
    """
    also_empty = Condition()
    not_empty = condition_for(">")

    assert (empty & not_empty) is not_empty
    assert (not_empty & empty) is not_empty
    assert (empty & also_empty) is empty
    assert (also_empty & empty) is also_empty


def test_and_both_and():
    """(a & b) & (c & d) -> (a & b & c & d)"""
    a, b, c, d = [condition_for(">") for _ in range(4)]
    left = AndCondition(a, b)
    right = AndCondition(c, d)

    assert (left & right).operation == "and"

    assert (left & right).values == [a, b, c, d]
    assert (right & left).values == [c, d, a, b]


@pytest.mark.parametrize("other", non_meta_conditions())
def test_and_simplifies(other):
    """When only one condition is an and, the other is put in a new and, in the correct place
    (a & b) & (c > 2) -> (a & b & (c > 2))
    (a > 2) & (b & c) -> ((a > 2) & b & c)
    """
    a, b, = [condition_for(">"), condition_for("<")]
    and_condition = AndCondition(a, b)

    assert (and_condition & other).operation == "and"

    assert (and_condition & other).values == [a, b, other]
    assert (other & and_condition).values == [other, a, b]


def test_and_basic():
    a = condition_for(">")
    b = condition_for("<")

    assert (a & b).operation == "and"
    assert (a & b).values == [a, b]
    assert (b & a).values == [b, a]


@pytest.mark.parametrize("empty", empty_conditions())
def test_iand_empty_conditions(empty):
    """Similar to and, empty values don't change the non-empty values.  LHS always wins if both empty."""
    also_empty = Condition()
    not_empty = condition_for(">")

    # None of the following modify the object

    original_empty = empty
    empty &= also_empty
    assert empty is original_empty

    original_also_empty = also_empty
    also_empty &= empty
    assert also_empty is original_also_empty

    original_not_empty = not_empty
    not_empty &= empty
    assert not_empty is original_not_empty

    # The only modifying __iand__
    empty &= not_empty
    assert empty is not_empty


def test_iand_both_and():
    """other's conditions are appended to self's conditions"""
    a, b, c, d = [condition_for(">") for _ in range(4)]
    left = AndCondition(a, b)
    right = AndCondition(c, d)

    original_left = left
    left &= right
    assert left is original_left
    assert left.values == [a, b, c, d]
    assert right.values == [c, d]


@pytest.mark.parametrize("other", non_meta_conditions())
def test_iand_simplifies(other):
    """Similar to and, other value is pushed into the and (on LHS) or front of a new and (on RHS)"""
    a, b, = [condition_for(">"), condition_for("<")]
    and_condition = AndCondition(a, b)

    original_other = other
    other &= and_condition
    assert other is not original_other
    assert other.values == [original_other, a, b]

    original_and_condition = and_condition
    and_condition &= original_other
    assert and_condition is original_and_condition
    assert and_condition.values == [a, b, original_other]


def test_iand_basic():
    a = condition_for(">")
    b = condition_for("<")

    original_a = a
    original_b = b

    a &= original_b
    assert a is not original_a
    assert a.operation == "and"
    assert a.values == [original_a, original_b]

    b &= original_a
    assert b is not original_b
    assert b.operation == "and"
    assert b.values == [original_b, original_a]


# NEW CONDITION OR/IOR ========================================================================== NEW CONDITION OR/IOR


@pytest.mark.parametrize("empty", empty_conditions())
def test_or_empty_conditions(empty):
    """When conditions are falsey (literal empty or meta with no inner value), simplify instead of nesting:
    ()_1 | ()_2 -> ()_1
    x | () -> x
    () | x -> x
    """
    also_empty = Condition()
    not_empty = condition_for(">")

    assert (empty | not_empty) is not_empty
    assert (not_empty | empty) is not_empty
    assert (empty | also_empty) is empty
    assert (also_empty | empty) is also_empty


def test_or_both_or():
    """(a | b) | (c | d) -> (a | b | c | d)"""
    a, b, c, d = [condition_for(">") for _ in range(4)]
    left = OrCondition(a, b)
    right = OrCondition(c, d)

    assert (left | right).operation == "or"

    assert (left | right).values == [a, b, c, d]
    assert (right | left).values == [c, d, a, b]


@pytest.mark.parametrize("other", non_meta_conditions())
def test_or_simplifies(other):
    """When only one condition is an or, the other is put in a new or, in the correct place
    (a | b) | (c > 2) -> (a | b | (c > 2))
    (a > 2) | (b | c) -> ((a > 2) | b | c)
    """
    a, b, = [condition_for(">"), condition_for("<")]
    or_condition = OrCondition(a, b)

    assert (or_condition | other).operation == "or"

    assert (or_condition | other).values == [a, b, other]
    assert (other | or_condition).values == [other, a, b]


def test_or_basic():
    a = condition_for(">")
    b = condition_for("<")

    assert (a | b).operation == "or"
    assert (a | b).values == [a, b]
    assert (b | a).values == [b, a]


@pytest.mark.parametrize("empty", empty_conditions())
def test_ior_empty_conditions(empty):
    """Similar to or, empty values don't change the non-empty values.  LHS always wins if both empty."""
    also_empty = Condition()
    not_empty = condition_for(">")

    # None of the following modify the object

    original_empty = empty
    empty |= also_empty
    assert empty is original_empty

    original_also_empty = also_empty
    also_empty |= empty
    assert also_empty is original_also_empty

    original_not_empty = not_empty
    not_empty |= empty
    assert not_empty is original_not_empty

    # The only modifying __ior__
    empty |= not_empty
    assert empty is not_empty


def test_ior_both_or():
    """other's conditions are appended to self's conditions"""
    a, b, c, d = [condition_for(">") for _ in range(4)]
    left = OrCondition(a, b)
    right = OrCondition(c, d)

    original_left = left
    left |= right
    assert left is original_left
    assert left.values == [a, b, c, d]
    assert right.values == [c, d]


@pytest.mark.parametrize("other", non_meta_conditions())
def test_ior_simplifies(other):
    """Similar to or, other value is pushed into the or (on LHS) or front of a new or (on RHS)"""
    a, b, = [condition_for(">"), condition_for("<")]
    or_condition = OrCondition(a, b)

    original_other = other
    other |= or_condition
    assert other is not original_other
    assert other.values == [original_other, a, b]

    original_or_condition = or_condition
    or_condition |= original_other
    assert or_condition is original_or_condition
    assert or_condition.values == [a, b, original_other]


def test_ior_basic():
    a = condition_for(">")
    b = condition_for("<")

    original_a = a
    original_b = b

    a |= original_b
    assert a is not original_a
    assert a.operation == "or"
    assert a.values == [original_a, original_b]

    b |= original_a
    assert b is not original_b
    assert b.operation == "or"
    assert b.values == [original_b, original_a]


# NEW CONDITION REPR ============================================================================== NEW CONDITION REPR


@pytest.mark.parametrize("condition, expected", [
    # and
    (AndCondition(), "( & )"),
    (AndCondition("foo"), "('foo' &)"),
    (AndCondition("a", "b", "c"), "('a' & 'b' & 'c')"),

    # or
    (OrCondition(), "( | )"),
    (OrCondition("foo"), "('foo' |)"),
    (OrCondition("a", "b", "c"), "('a' | 'b' | 'c')"),

    # not
    (NotCondition("a"), "(~'a')"),

    # comparisons
    (ComparisonCondition("<", column=c, value=3), "(M.c < 3)"),
    (ComparisonCondition(">", column=c, value=3), "(M.c > 3)"),
    (ComparisonCondition("<=", column=c, value=3), "(M.c <= 3)"),
    (ComparisonCondition(">=", column=c, value=3), "(M.c >= 3)"),
    (ComparisonCondition("==", column=c, value=3), "(M.c == 3)"),
    (ComparisonCondition("!=", column=c, value=3), "(M.c != 3)"),

    # begins_with, contains
    (BeginsWithCondition(column=c, value=2), "begins_with(M.c, 2)"),
    (ContainsCondition(column=c, value=2), "contains(M.c, 2)"),

    # between
    (BetweenCondition(column=c, lower=2, upper=3), "(M.c between [2, 3])"),

    # in
    (InCondition(column=c, values=[]), "(M.c in [])"),
    (InCondition(column=c, values=[2, 3]), "(M.c in [2, 3])"),
    (InCondition(column=c, values=[MockColumn("d"), 3]), "(M.c in [d, 3])"),

    # empty
    (Condition(), "()")
])
def test_repr(condition, expected):
    assert repr(condition) == expected


# NEW CONDITION EQUALITY ====================================================================== NEW CONDITION EQUALITY


def test_eq_empty():
    empty = Condition()
    assert empty == empty

    also_empty = Condition()
    assert empty is not also_empty
    assert empty == also_empty


def test_eq_wrong_type():
    """AttributeError returns False"""
    assert not (Condition() == object())


@pytest.mark.parametrize("other", [
    BaseCondition("op", values=list("xy"), column=c, path=["wrong", "path"]),
    BaseCondition("??", values=list("xy"), column=c, path=["foo", "bar"]),
    BaseCondition("op", values=list("xy"), column=None, path=["foo", "bar"]),
    BaseCondition("op", values=list("xyz"), column=c, path=["foo", "bar"]),
    BaseCondition("op", values=list("yx"), column=c, path=["foo", "bar"]),
])
def test_eq_one_wrong_field(other):
    """All four of operation, value, column, and path must match"""
    self = BaseCondition("op", values=list("xy"), column=c, path=["foo", "bar"])
    assert not (self == other)


@pytest.mark.parametrize("other", [
    BaseCondition("op", values=[c]),
    BaseCondition("op", values=["x"]),
    BaseCondition("op", values=[c, c]),
    BaseCondition("op", values=["x", "x"]),
    BaseCondition("op", values=["x", c]),
    BaseCondition("op", values=[d, "x"]),
])
def test_eq_values_mismatch(other):
    condition = BaseCondition("op", values=[c, "x"])
    assert not (condition == other)


# END NEW CONDITION ================================================================================ END NEW CONDITION


# TRACKING SIGNALS ================================================================================== TRACKING SIGNALS


# Columns are sorted by model name
empty_user_condition = (
    User.age.is_(None) &
    User.email.is_(None) &
    User.id.is_(None) &
    User.joined.is_(None) &
    User.name.is_(None)
)


def test_on_deleted(engine):
    """When an object is deleted, the snapshot expects all columns to be empty"""
    user = User(age=3, name="foo")
    object_deleted.send(engine, obj=user)
    assert get_snapshot(user) == empty_user_condition

    # It doesn't matter if the object had non-empty values saved from a previous sync
    object_saved.send(engine, obj=user)
    assert get_snapshot(user) == (
        User.age.is_({"N": "3"}) &
        User.name.is_({"S": "foo"})
    )

    # The deleted signal still clears everything
    object_deleted.send(engine, obj=user)
    assert get_snapshot(user) == empty_user_condition

    # But the current values aren't replaced
    assert user.age == 3
    assert user.name == "foo"


def test_on_loaded_partial(engine):
    """When an object is loaded, the state after loading is snapshotted for future atomic calls"""
    # Creating an instance doesn't snapshot anything
    user = User(age=3, name="foo")
    assert get_snapshot(user) == empty_user_condition

    # Pretend the user was just loaded.  Because only
    # age and name are marked, they will be the only
    # columns included in the snapshot.  A normal load
    # would set the other values to None, and the
    # snapshot would expect those.
    object_loaded.send(engine, obj=user)

    # Values are stored dumped.  Since the dumped flag isn't checked as
    # part of equality testing, we can simply construct the dumped
    # representations to compare.
    assert get_snapshot(user) == (
        User.age.is_({"N": "3"}) &
        User.name.is_({"S": "foo"})
    )


def test_on_loaded_full(engine):
    """Same as the partial test, but with explicit Nones to simulate a real engine.load"""
    user = User(age=3, email=None, id=None, joined=None, name="foo")
    object_loaded.send(engine, obj=user)
    assert get_snapshot(user) == (
        User.age.is_({"N": "3"}) &
        User.email.is_(None) &
        User.id.is_(None) &
        User.joined.is_(None) &
        User.name.is_({"S": "foo"})
    )


def test_on_modified():
    """When an object's values are set or deleted, those columns are marked for tracking"""

    # Creating an instance doesn't mark anything
    user = User()
    assert get_marked(user) == set()

    user.id = "foo"
    assert get_marked(user) == {User.id}

    # Deleting the value does not clear it from the set of marked columns
    del user.id
    assert get_marked(user) == {User.id}

    # Even when the delete fails, the column is marked.
    # We're tracking intention, not state change.
    with pytest.raises(AttributeError):
        del user.age
    assert get_marked(user) == {User.id, User.age}


def test_on_saved(engine):
    """Saving is equivalent to loading w.r.t. tracking.

    The state after saving is snapshotted for future atomic operations."""
    user = User(name="foo", age=3)
    object_saved.send(engine, obj=user)

    # Since "name" and "age" were the only marked columns saved to DynamoDB,
    # they are the only columns that must match for an atomic save.  The
    # state of the other columns wasn't specified, so it's not safe to
    # assume the intended value (missing vs empty)
    assert get_snapshot(user) == (
        User.age.is_({"N": "3"}) &
        User.name.is_({"S": "foo"})
    )


# END TRACKING SIGNALS ========================================================================== END TRACKING SIGNALS


# NEW COMPARISON MIXIN ========================================================================== NEW COMPARISON MIXIN


def test_mixin_repr():
    """repr without non-proxy objects"""
    self = ComparisonMixin()
    assert repr(self) == "<ComparisonMixin>"

    inner_is_mixin = ComparisonMixin(proxied=MockColumn("foobar"))
    assert repr(inner_is_mixin) == "foobar"


def test_mixin_getattr_delegates():
    """getattr points to the proxied object (unless it's self)"""
    self = ComparisonMixin()
    # Can't delegate, proxied object is self (infinite recursion)
    with pytest.raises(AttributeError):
        getattr(self, "foo")

    class Foo:
        getattr_calls = 0

        def __getattr__(self, item):
            self.getattr_calls += 1
            return "foo"

    obj = Foo()
    proxy = ComparisonMixin(proxied=obj)
    assert proxy.whatever == "foo"

    assert obj.getattr_calls == 1
    assert proxy.getattr_calls == 1


def test_mixin_path_chaining():
    """No depth limit to the chained path"""
    self = ComparisonMixin()

    for i in range(10):
        self = self[i]
        self = self[str(i)]

    # Render to condition to inspect the path attribute
    condition = self.is_(None)
    assert len(condition.path) == 20


@pytest.mark.parametrize("op, expected", [
    (operator.eq, "=="),
    (operator.ne, "!="),
    (operator.lt, "<"),
    (operator.gt, ">"),
    (operator.le, "<="),
    (operator.ge, ">="),
])
def test_mixin_magic_comparisons(op, expected):
    """==, !=, <, >, <=, >= create condition objects with the corresponding operation"""
    condition = op(c, 3)
    assert condition.operation == expected
    assert condition.column is c
    assert condition.values == [3]


def test_mixin_begins_with():
    condition = c.begins_with(3)
    assert condition.operation == "begins_with"
    assert condition.column is c
    assert condition.values == [3]


def test_mixin_between():
    condition = c.between(3, 4)
    assert condition.operation == "between"
    assert condition.column is c
    assert condition.values == [3, 4]


def test_mixin_contains():
    condition = c.contains(3)
    assert condition.operation == "contains"
    assert condition.column is c
    assert condition.values == [3]


def test_mixin_in_():
    condition = c.in_(3, 4)
    assert condition.operation == "in"
    assert condition.column is c
    assert condition.values == [3, 4]


def test_mixin_is_():
    condition = c.is_(3)
    assert condition.operation == "=="
    assert condition.column is c
    assert condition.values == [3]

    condition = c.is_not(3)
    assert condition.operation == "!="
    assert condition.column is c
    assert condition.values == [3]
