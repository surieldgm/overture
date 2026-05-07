import unittest


class CiFailureProofTest(unittest.TestCase):
    def test_ci_reports_failure(self):
        self.fail("temporary CI failure proof for ERI-80")
