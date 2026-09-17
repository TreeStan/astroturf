import datetime as dt
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("astroturf", Path(__file__).resolve().parent.parent / "astroturf.py")
at = importlib.util.module_from_spec(spec)
spec.loader.exec_module(at)

NOW = dt.datetime(2026, 9, 16, 12, 0, 0)


def user(created: str, followers=5, following=5, repos=3, starred=20):
    return {"login": "x", "createdAt": created, "followers": {"totalCount": followers},
            "following": {"totalCount": following}, "repositories": {"totalCount": repos},
            "starredRepositories": {"totalCount": starred}}


def organic_profiles(n=100):
    return [user(f"20{15 + i % 10}-0{1 + i % 9}-1{i % 10}T00:00:00Z", followers=i % 7, repos=1 + i % 9) for i in range(n)]


def farm_profiles(n=100):
    return [user("2026-09-14T00:00:00Z", followers=0, following=0, repos=0, starred=2) for _ in range(n)]


class Signals(unittest.TestCase):
    def test_new_accounts_organic_vs_farm(self):
        s_org, i_org = at.signal_new_accounts(organic_profiles(), NOW)
        s_farm, i_farm = at.signal_new_accounts(farm_profiles(), NOW)
        self.assertEqual(s_org, 0.0)
        self.assertEqual(s_farm, 1.0)
        self.assertEqual(i_farm["under_7d"], 1.0)
        self.assertLess(i_org["under_30d"], 0.01)

    def test_same_day_and_empty(self):
        self.assertEqual(at.signal_same_day(farm_profiles())[0], 1.0)
        self.assertEqual(at.signal_same_day(organic_profiles())[0], 0.0)
        self.assertEqual(at.signal_empty_profiles(farm_profiles())[0], 1.0)
        self.assertEqual(at.signal_empty_profiles(organic_profiles())[0], 0.0)

    def test_empty_sample_is_neutral(self):
        for fn in (at.signal_same_day, at.signal_empty_profiles):
            self.assertEqual(fn([])[0], 0.0)
        self.assertEqual(at.signal_new_accounts([], NOW)[0], 0.0)

    def test_steady_drip_flat_young_repo_scores_high(self):
        flat = [1000] * 90
        s, info = at.signal_steady_drip(flat, age_days=90)
        self.assertEqual(s, 1.0)
        self.assertAlmostEqual(info["cv"], 0.0)

    def test_steady_drip_decaying_launch_scores_low(self):
        decay = [int(5000 / (1 + i)) for i in range(90)]  # organic: big launch, long tail
        s, info = at.signal_steady_drip(decay, age_days=90)
        self.assertEqual(s, 0.0)
        self.assertIn("note", info)  # median falls below the 200/day floor

    def test_steady_drip_high_variance_scores_low(self):
        noisy = [200 + (i % 2) * 1800 for i in range(90)]
        s, info = at.signal_steady_drip(noisy, age_days=90)
        self.assertLess(s, 0.35)
        self.assertGreater(info["cv"], 0.8)

    def test_steady_drip_not_applied_to_old_repos(self):
        self.assertEqual(at.signal_steady_drip([300] * 400, age_days=1500)[0], 0.0)

    def test_watchers_ratio(self):
        self.assertAlmostEqual(at.signal_watchers_ratio({"stargazers_count": 100000, "subscribers_count": 200, "forks_count": 1})[0], 1.0)
        self.assertEqual(at.signal_watchers_ratio({"stargazers_count": 100000, "subscribers_count": 600, "forks_count": 1})[0], 0.0)
        self.assertEqual(at.signal_watchers_ratio({"stargazers_count": 100, "subscribers_count": 0})[0], 0.0)

    def test_burst_now(self):
        actors = [("u", f"2026-09-16T{h:02d}:00:00Z") for h in range(0, 10) for _ in range(30)]  # 300 in 9h
        s, info = at.signal_burst_now(actors, [24 * 5] * 7)  # 5/h last week
        self.assertGreater(info["ratio"], 5)
        self.assertGreater(s, 0)
        self.assertEqual(at.signal_burst_now(actors[:5], [1] * 7)[0], 0.0)

    def test_score_weights_sum_to_100(self):
        self.assertEqual(sum(at.WEIGHTS.values()), 100)
        self.assertEqual(at.score({k: 1.0 for k in at.WEIGHTS}), 100.0)
        self.assertEqual(at.score({k: 0.0 for k in at.WEIGHTS}), 0.0)

    def test_labels_monotonic(self):
        self.assertEqual(at.label(5), "looks organic")
        self.assertEqual(at.label(25), "some signals")
        self.assertEqual(at.label(50), "strong signals")
        self.assertEqual(at.label(80), "very strong signals")


class Assemble(unittest.TestCase):
    def repo(self, created="2026-06-01T00:00:00Z", stars=50000, subs=100):
        return {"created_at": created, "stargazers_count": stars, "subscribers_count": subs, "forks_count": 1000, "open_issues_count": 10}

    def test_farm_pattern_scores_high_and_organic_low(self):
        farm = at.assemble("o/farm", self.repo(), [900] * 100, [("u", "2026-09-16T10:00:00Z")] * 60, farm_profiles(), NOW)
        org = at.assemble("o/org", self.repo(subs=400), [int(4000 / (1 + i)) for i in range(100)],
                          [("u", "2026-09-16T10:00:00Z")] * 60, organic_profiles(), NOW)
        self.assertGreater(farm["score"], 80)
        self.assertLess(org["score"], 20)
        self.assertEqual(farm["label"], "very strong signals")
        self.assertEqual(org["label"], "looks organic")

    def test_old_repo_note(self):
        r = at.assemble("o/old", self.repo(created="2020-01-01T00:00:00Z"), [100] * 100, [("u", "2026-09-16T10:00:00Z")] * 60, farm_profiles(), NOW)
        self.assertTrue(any("camouflage" in n for n in r["notes"]))

    def test_render_and_leaderboard_do_not_crash(self):
        r = at.assemble("o/r", self.repo(), [900] * 100, [("u", "2026-09-16T10:00:00Z")] * 60, farm_profiles(), NOW)
        text = at.render_check(r)
        self.assertIn("score", text)
        md = at.render_leaderboard([r, at.assemble("o/s", self.repo(), [], [], [], NOW)], "q", NOW)
        self.assertIn("| adj | raw |", md)
        self.assertIn("o/r", md)


class History(unittest.TestCase):
    def test_history_trims_and_orders(self):
        class FakeGH:
            def get(self, path, ok404=False):
                if "page=1" in path:
                    return [{"week": 200, "total": 5, "days": [1, 2, 2, 0, 0, 0, 0]}, {"week": 100, "total": 3, "days": [0, 0, 1, 1, 1, 0, 0]}]
                return []
        days = at.fetch_history(FakeGH(), "o/r")
        self.assertEqual(days, [1, 1, 1, 0, 0, 1, 2, 2])


if __name__ == "__main__":
    unittest.main()
