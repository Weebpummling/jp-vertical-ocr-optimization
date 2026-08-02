"""Tests for how the workstation knows who is writing.

The project's identity model is one sentence long: a worker types the id code
they were issued, and everything they record is attributed to it
(docs/decision-workstation-auth.md). Because it is that small, the ways it can
quietly break are specific, and each one gets a test here:

* a code that is *not* recognized must be refused - the header cannot become
  advisory;
* the code must not come back out - not in a 401 body, not in `whoami`, and not
  in the observations listing, which every other worker on the page can see;
* minted codes must actually be unguessable, because if the workstation ever
  leaves this machine the code is the only thing in front of the database.

Roles are deliberately absent: they gate nothing by decision, so there is
nothing to test.
"""

import math
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "scripts"))

import api  # noqa: E402
import db  # noqa: E402
import issue_access_code as issuer  # noqa: E402

from test_write_path import AVAILABLE  # noqa: E402


class MintTests(unittest.TestCase):
    """Codes are generated, never chosen."""

    def test_shape_is_readable_aloud(self):
        code = issuer.mint()
        head, *groups = code.split("-")
        self.assertEqual(head, "JP")
        self.assertEqual(len(groups), issuer.GROUPS)
        self.assertTrue(all(len(g) == issuer.GROUP_LEN for g in groups))

    def test_alphabet_excludes_confusable_characters(self):
        for bad in "OIL01B8":
            self.assertNotIn(bad, issuer.ALPHABET)

    def test_codes_do_not_repeat(self):
        """A weak generator shows up here long before it shows up in the data."""
        codes = {issuer.mint() for _ in range(500)}
        self.assertEqual(len(codes), 500)

    def test_entropy_is_enough_to_survive_being_exposed(self):
        """~57 bits. This number is what makes a network deployment defensible."""
        bits = (issuer.GROUPS * issuer.GROUP_LEN) * math.log2(len(issuer.ALPHABET))
        self.assertGreater(bits, 55)


class CurrentUserTests(unittest.TestCase):
    """The dependency every write endpoint hangs off."""

    def test_missing_code_is_refused(self):
        with self.assertRaises(api.HTTPException) as caught:
            api.current_user(None)
        self.assertEqual(caught.exception.status_code, 401)

    def test_unknown_code_is_refused_without_echoing_it(self):
        """A 401 body is exactly where a secret gets copied into a log."""
        secret = "JP-ZZZZ-ZZZZ-ZZZZ"
        with mock.patch.object(db, "find_user", return_value=None):
            with self.assertRaises(api.HTTPException) as caught:
                api.current_user(secret)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertNotIn(secret, str(caught.exception.detail))
        self.assertNotIn("ZZZZ", str(caught.exception.detail))

    def test_surrounding_whitespace_is_tolerated(self):
        """Codes get pasted. A trailing space is not a different worker."""
        seen = {}

        def spy(code):
            seen["code"] = code
            return {"user_id": uuid.uuid4(), "login": code, "display_name": "A"}

        with mock.patch.object(db, "find_user", spy):
            api.current_user("  JP-AAAA-BBBB-CCCC \n")
        self.assertEqual(seen["code"], "JP-AAAA-BBBB-CCCC")

    def test_whoami_does_not_return_the_code(self):
        user = {"user_id": uuid.uuid4(), "login": "JP-SECR-ETCO-DE00",
                "display_name": "Alice"}
        payload = api.whoami(user)
        self.assertEqual(payload["display_name"], "Alice")
        self.assertNotIn("login", payload)
        self.assertNotIn("JP-SECR-ETCO-DE00", str(payload))

    def test_whoami_names_an_unnamed_worker_rather_than_falling_back_to_the_code(self):
        user = {"user_id": uuid.uuid4(), "login": "JP-SECR-ETCO-DE00",
                "display_name": None}
        payload = api.whoami(user)
        self.assertEqual(payload["display_name"], "(unnamed)")
        self.assertNotIn("JP-SECR-ETCO-DE00", str(payload))


@unittest.skipUnless(AVAILABLE, "no database (set JPOCR_DSN or POSTGRES_PASSWORD)")
class ListingAttributionTests(unittest.TestCase):
    """Attribution is the whole point; leaking the code alongside it is not.

    Runs the shipped query inside a transaction that is rolled back.
    """

    def setUp(self):
        self.conn = db.connect()
        self.conn.autocommit = False
        self.addCleanup(self.conn.close)
        self.addCleanup(self.conn.rollback)
        self.cur = self.conn.cursor()
        suffix = uuid.uuid4().hex[:8]
        self.code = f"JP-TEST-{suffix[:4].upper()}-{suffix[4:].upper()}"
        self.cur.execute(
            "INSERT INTO app_user (login, display_name, role) "
            "VALUES (%s, %s, 'annotator') RETURNING user_id",
            (self.code, "Alice Tanaka"))
        user_id = self.cur.fetchone()["user_id"]
        self.cur.execute(
            "INSERT INTO source_volume (title, pid, edition_date) "
            "VALUES ('t', %s, DATE '1933-09-01') RETURNING volume_id", (f"test-{suffix}",))
        vol = self.cur.fetchone()["volume_id"]
        self.cur.execute(
            "INSERT INTO source_page (volume_id, frame_no) VALUES (%s, 1) RETURNING page_id",
            (vol,))
        self.page_id = self.cur.fetchone()["page_id"]
        self.cur.execute(
            "INSERT INTO roster_cell (page_id, row_index, crop_bbox) "
            "VALUES (%s, 0, %s) RETURNING cell_id", (self.page_id, [1, 2, 3, 4]))
        cell = self.cur.fetchone()["cell_id"]
        self.cur.execute(
            "INSERT INTO observation (page_id, cell_id, name_raw, as_of_date, author_user_id) "
            "VALUES (%s, %s, '平岩棟一', DATE '1933-09-01', %s)",
            (self.page_id, cell, user_id))

    def test_work_is_attributed_to_the_person(self):
        rows = db.observations_for_page(str(self.page_id), cur=self.cur)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["author"], "Alice Tanaka")

    def test_the_listing_never_carries_the_id_code(self):
        rows = db.observations_for_page(str(self.page_id), cur=self.cur)
        self.assertNotIn(self.code, str(rows[0]))


if __name__ == "__main__":
    unittest.main()
