"""Tests for scheduler: dependency waves, sprint execution loop."""

from daemon.models import SprintContract
from daemon.scheduler import dependency_waves


def test_no_dependencies_single_wave():
    sprints = [
        SprintContract(id="s1", description="Task 1", depends_on=[]),
        SprintContract(id="s2", description="Task 2", depends_on=[]),
        SprintContract(id="s3", description="Task 3", depends_on=[]),
    ]
    waves = dependency_waves(sprints)
    assert len(waves) == 1
    assert len(waves[0]) == 3


def test_linear_chain():
    sprints = [
        SprintContract(id="s1", depends_on=[]),
        SprintContract(id="s2", depends_on=["s1"]),
        SprintContract(id="s3", depends_on=["s2"]),
    ]
    waves = dependency_waves(sprints)
    assert len(waves) == 3
    assert waves[0][0].id == "s1"
    assert waves[1][0].id == "s2"
    assert waves[2][0].id == "s3"


def test_diamond_dependency():
    sprints = [
        SprintContract(id="s1", depends_on=[]),
        SprintContract(id="s2", depends_on=["s1"]),
        SprintContract(id="s3", depends_on=["s1"]),
        SprintContract(id="s4", depends_on=["s2", "s3"]),
    ]
    waves = dependency_waves(sprints)
    assert len(waves) == 3
    assert waves[0][0].id == "s1"
    wave1_ids = {s.id for s in waves[1]}
    assert wave1_ids == {"s2", "s3"}
    assert waves[2][0].id == "s4"


def test_mixed_dependencies():
    sprints = [
        SprintContract(id="s1", depends_on=[]),
        SprintContract(id="s2", depends_on=[]),
        SprintContract(id="s3", depends_on=["s1"]),
        SprintContract(id="s4", depends_on=["s2"]),
        SprintContract(id="s5", depends_on=["s3", "s4"]),
    ]
    waves = dependency_waves(sprints)
    assert len(waves) == 3
    wave0_ids = {s.id for s in waves[0]}
    assert wave0_ids == {"s1", "s2"}


def test_deadlock_handling():
    """Circular dependency should still produce waves (forced)."""
    sprints = [
        SprintContract(id="s1", depends_on=["s2"]),
        SprintContract(id="s2", depends_on=["s1"]),
    ]
    waves = dependency_waves(sprints)
    assert len(waves) >= 1
    # All sprints should be in some wave
    all_ids = set()
    for wave in waves:
        all_ids.update(s.id for s in wave)
    assert all_ids == {"s1", "s2"}


def test_empty_sprints():
    waves = dependency_waves([])
    assert waves == []


def test_single_sprint():
    sprints = [SprintContract(id="s1", depends_on=[])]
    waves = dependency_waves(sprints)
    assert len(waves) == 1
    assert len(waves[0]) == 1
