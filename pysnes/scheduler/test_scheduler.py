import pytest

from .scheduler import Scheduler


@pytest.fixture
def s():
    return Scheduler()


# --- add / run_to ---


def test_single_event_fires(s):
    fired = []
    s.add(100, lambda: fired.append(1))
    s.run_to(100)
    assert fired == [1]


def test_event_does_not_fire_before_its_time(s):
    fired = []
    s.add(100, lambda: fired.append(1))
    s.run_to(99)
    assert fired == []


def test_master_clock_advances_to_event_time(s):
    s.add(42, lambda: None)
    s.run_to(42)
    assert s.master_clock == 42


def test_master_clock_does_not_exceed_target(s):
    s.add(200, lambda: None)
    s.run_to(100)
    assert s.master_clock == 0  # no event fired, clock unchanged


def test_multiple_events_fire_in_order(s):
    order = []
    s.add(30, lambda: order.append("a"))
    s.add(10, lambda: order.append("b"))
    s.add(20, lambda: order.append("c"))
    s.run_to(30)
    assert order == ["b", "c", "a"]


def test_only_events_up_to_target_fire(s):
    fired = []
    s.add(10, lambda: fired.append(10))
    s.add(20, lambda: fired.append(20))
    s.add(30, lambda: fired.append(30))
    s.run_to(20)
    assert fired == [10, 20]


def test_events_scheduled_by_handlers_fire_in_same_run_to(s):
    """A handler that schedules a new event within the same window should fire."""
    fired = []

    def first():
        fired.append("first")
        s.add(5, lambda: fired.append("second"))

    s.add(10, first)
    s.run_to(15)
    assert fired == ["first", "second"]


def test_master_clock_is_correct_inside_handler(s):
    seen = []
    s.add(77, lambda: seen.append(s.master_clock))
    s.run_to(100)
    assert seen == [77]


# --- simultaneous events: FIFO by insertion order ---


def test_simultaneous_events_fire_in_insertion_order(s):
    order = []
    s.add(0, lambda: order.append(1))
    s.add(0, lambda: order.append(2))
    s.add(0, lambda: order.append(3))
    s.run_to(0)
    assert order == [1, 2, 3]


# --- peek ---


def test_peek_returns_next_event_time(s):
    s.add(50, lambda: None)
    s.add(10, lambda: None)
    assert s.peek() == 10


def test_peek_returns_sentinel_when_empty(s):
    assert s.peek() == 0xFFFFFFFFFFFFFFFF


def test_peek_does_not_fire_event(s):
    fired = []
    s.add(10, lambda: fired.append(1))
    s.peek()
    assert fired == []


# --- run_one ---


def test_run_one_fires_earliest_event(s):
    fired = []
    s.add(20, lambda: fired.append(20))
    s.add(10, lambda: fired.append(10))
    s.run_one()
    assert fired == [10]


def test_run_one_advances_master_clock(s):
    s.add(55, lambda: None)
    s.run_one()
    assert s.master_clock == 55


def test_run_one_leaves_remaining_events(s):
    fired = []
    s.add(10, lambda: fired.append(10))
    s.add(20, lambda: fired.append(20))
    s.run_one()
    assert fired == [10]
    assert s.peek() == 20


# --- delay=0 (schedule for "now") ---


def test_delay_zero_fires_at_current_clock(s):
    s.master_clock = 100
    fired = []
    s.add(0, lambda: fired.append(s.master_clock))
    s.run_to(100)
    assert fired == [100]


# --- large event counts ---


def test_many_events_all_fire(s):
    fired = []
    for i in range(1000):
        s.add(i, lambda i=i: fired.append(i))
    s.run_to(999)
    assert len(fired) == 1000
    assert fired == list(range(1000))
