import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

import bot


class FrozenDateTime:
    current = datetime(2026, 10, 30, 0, 1, tzinfo=bot.LAGOS)

    @classmethod
    def now(cls, tz=None):
        value = cls.current
        return value if tz is None else value.astimezone(tz)


class OrionTapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp.name, "test.sqlite3")
        self.db_patch = patch.object(bot, "DB_PATH", bot.Path(self.db_path))
        self.db_patch.start()
        bot.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_player_and_tap_persist_with_energy(self):
        p = bot.get_player(101, "testuser", "Test")
        self.assertEqual(p["points"], 0)
        self.assertEqual(p["energy"], 500)
        res = bot.do_tap(101)
        self.assertTrue(res["ok"])
        self.assertEqual(res["player"]["points"], 1)
        self.assertEqual(res["player"]["energy"], 499)

    def test_energy_depletion_and_refill(self):
        bot.get_player(202)
        with bot.connect() as db:
            db.execute("UPDATE players SET energy=0, energy_updated_at=? WHERE user_id=202", (int(bot.time.time())-60,))
        result=bot.do_tap(202)
        self.assertTrue(result["ok"])
        self.assertEqual(result["player"]["energy"], 0)
        self.assertEqual(result["player"]["points"], 1)

    def test_daily_bonus_once_per_lagos_day(self):
        with patch.object(bot, "datetime", FrozenDateTime):
            first=bot.claim_daily(303)
            second=bot.claim_daily(303)
        self.assertTrue(first["claimed"])
        self.assertFalse(second["claimed"])
        self.assertEqual(second["player"]["points"], 25)
        self.assertEqual(second["player"]["streak"], 1)

    def test_referral_rewards_both_once(self):
        bot.get_player(404)
        p=bot.get_player(405, referrer_id=404)
        bot.get_player(405, referrer_id=404)
        with bot.connect() as db:
            self.assertEqual(db.execute("SELECT points FROM players WHERE user_id=404").fetchone()[0],50)
            self.assertEqual(db.execute("SELECT points FROM players WHERE user_id=405").fetchone()[0],50)
        self.assertEqual(p["referred_by"],404)

    def test_api_health_and_auth_boundary(self):
        client=bot.api.test_client()
        self.assertEqual(client.get("/api/health").status_code,200)
        self.assertEqual(client.get("/api/me").status_code,401)
        self.assertEqual(client.post("/api/tap").status_code,401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
