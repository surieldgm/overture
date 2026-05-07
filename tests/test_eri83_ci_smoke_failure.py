import unittest


class ERI83CISmokeFailureTest(unittest.TestCase):
    def test_ci_blocks_deliberately_failing_pr(self) -> None:
        self.assertTrue(True)
