from __future__ import annotations

import unittest

from extract_army_web import build_unit


class BuildUnitWeaponCountTests(unittest.TestCase):
    def test_ravenous_beasts_display_two_razor_claws_per_model(self) -> None:
        unit = {
            "name": "Ravenous Beasts",
            "size": 3,
            "cost": 155,
            "quality": 4,
            "defense": 4,
            "rules": [],
            "weapons": [
                {
                    "name": "Razor Claws",
                    "count": 6,
                    "range": None,
                    "attacks": 2,
                    "specialRules": [],
                    "label": "2x Razor Claws (A2)",
                }
            ],
            "items": [],
            "upgrades": [],
        }

        result = build_unit(unit, package_by_uid={}, game_system_slug="grimdark-future")

        self.assertEqual("2x Razor Claws", result["weapons"][0]["name"])


if __name__ == "__main__":
    unittest.main()
