import unittest


class BranchProtectionRedCheckProbe(unittest.TestCase):
    def test_intentional_failure_for_branch_protection_probe(self) -> None:
        self.fail("intentional ERI-82 branch protection validation failure")
