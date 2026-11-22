"""단계 전환 방향: 화면이 바뀔 때만 방향·번호가 바뀌고, 같은 화면에서 다시 그리면 그대로(다시 움직이지 않음)."""

from app import motion


def test_direction_follows_step_order(monkeypatch):
    ss: dict = {}
    monkeypatch.setattr(motion.st, "session_state", ss)
    assert motion._track("stage", "home") == ("none", 0)
    assert motion._track("stage", "home") == ("none", 0)  # 같은 화면: 그대로
    assert motion._track("stage", "work") == ("fwd", 1)
    assert motion._track("stage", "work") == ("fwd", 1)  # 버튼을 눌러 다시 그려도 키가 같다
    assert motion._track("stage", "home") == ("back", 2)


def test_sections_are_tracked_apart_from_stage(monkeypatch):
    ss: dict = {}
    monkeypatch.setattr(motion.st, "session_state", ss)
    motion._track("stage", "work")
    assert motion._track("section", "region") == ("none", 0)
    assert motion._track("section", "map") == ("fwd", 1)       # ① → ②
    assert motion._track("section", "letters") == ("fwd", 2)   # ② → ③
    assert motion._track("section", "region") == ("back", 3)   # ③ → ①
    assert ss[motion._KEY]["stage"]["view"] == "work"


def test_step_of_matches_step_bar():
    assert [motion.STEP_OF[v] for v in ("home", "region", "map", "letters")] == [1, 2, 2, 3]
