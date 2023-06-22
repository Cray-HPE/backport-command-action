#!/usr/bin/env python3
#
# MIT License
#
# (C) Copyright 2023 Hewlett Packard Enterprise Development LP
#
# Permission is hereby granted, free of charge, to any person obtaining a
# copy of this software and associated documentation files (the "Software"),
# to deal in the Software without restriction, including without limitation
# the rights to use, copy, modify, merge, publish, distribute, sublicense,
# and/or sell copies of the Software, and to permit persons to whom the
# Software is furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included
# in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
# THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR
# OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE,
# ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR
# OTHER DEALINGS IN THE SOFTWARE.
#
import unittest
from unittest.mock import patch
import logging
import tempfile
import os
import backport_command

class BackportCommandTest(unittest.TestCase):

    class AnyStringWith(str):
        def __eq__(self, other):
            return self in other

    def addFile(self, filename):
        backport_command.cmd("echo 'Test content for %s' > %s" % (filename, filename))
        backport_command.cmd("git add %s" % filename)
        backport_command.cmd("git commit -m 'Add %s'" % filename)

    def testParseNonMatching(self):
        event_data = {
            "issue": {
                "number": 1
            },
            "comment": {
                "body": "test"
            }
        }
        result = backport_command.main(event_data)
        self.assertEqual(result, 0)

    @patch("backport_command.post_comment")
    def testParseHelp(self, post_comment):
        event_data = {
            "issue": {
                "number": 1
            },
            "comment": {
                "body": "/backport"
            }
        }
        result = backport_command.main(event_data)
        self.assertEqual(result, 0)
        post_comment.assert_called_once_with(1, self.AnyStringWith("Usage: "))

    @patch("backport_command.post_comment")
    def testParseDryRunInvalid(self, post_comment):
        event_data = {
            "issue": {
                "number": 1
            },
            "comment": {
                "body": "/backport --dry-run"
            }
        }
        result = backport_command.main(event_data)
        self.assertEqual(result, 0)
        post_comment.assert_called_once_with(1, self.AnyStringWith("Usage: "))

    @patch("backport_command.get_pr")
    @patch("backport_command.clone")
    @patch("backport_command.backport")
    def testParseDryRun(self, backport, clone, get_pr):
        event_data = {
            "issue": {
                "number": 1
            },
            "comment": {
                "body": "/backport --dry-run feature/backport-target"
            },
            "repository": {
                "clone_url": "https://github.com/Cray-HPE/backport-command-action.git"
            }
        }
        auth_header = backport_command.get_auth_header("https://github.com/Cray-HPE/backport-command-action.git")
        backport.return_value = 0
        result = backport_command.main(event_data)
        self.assertEqual(result, 0)
        backport.assert_called_once_with("feature/backport-target", unittest.mock.ANY, True, auth_header)

    @patch("backport_command.get_pr")
    @patch("backport_command.clone")
    @patch("backport_command.backport")
    def testParseWithSanitization(self, backport, clone, get_pr):
        event_data = {
            "issue": {
                "number": 1
            },
            "comment": {
                "body": "/backport \n feature/backport-target"
            },
            "repository": {
                "clone_url": "https://github.com/Cray-HPE/backport-command-action.git"
            }
        }
        auth_header = backport_command.get_auth_header("https://github.com/Cray-HPE/backport-command-action.git")
        backport.return_value = 0
        result = backport_command.main(event_data)
        self.assertEqual(result, 0)
        backport.assert_called_once_with("feature/backport-target", unittest.mock.ANY, False, auth_header)

    @patch("backport_command.post_comment")
    @patch("backport_command.create_pr")
    @patch("backport_command.get_pr_commits")
    def testSimpleBackport(self, get_pr_commits, create_pr, post_comment):
        tempdir = tempfile.mkdtemp()
        os.chdir(tempdir)
        backport_command.cmd("git init --initial-branch=main")
        self.addFile("file1")
        backport_command.cmd("git branch feature/backport-target")
        self.addFile("file2")
        backport_command.cmd("git remote add origin ./.git")
        backport_command.cmd("git fetch --all")
        commit_hash = backport_command.cmd("git log -1 --format='%H'")[0].strip()
        get_pr_commits.return_value = [commit_hash]
        pr_data = {
            "number": 1,
            "title": "Test PR #1",
            "_links": {
                "html": {
                    "href": "https://github.com/Cray-HPE/backport-command-action/pull/1"
                }
            }
        }
        auth_header = backport_command.get_auth_header("https://github.com/Cray-HPE/backport-command-action.git")
        backport_command.backport("feature/backport-target", pr_data, False, auth_header)
        result = backport_command.cmd("git status")[0].split("\n")
        self.assertIn("On branch backport/1-to-feature/backport-target", result)
        self.assertIn("Your branch is up to date with 'origin/backport/1-to-feature/backport-target'.", result)
        self.assertIn("nothing to commit, working tree clean", result)
        result = backport_command.cmd("ls -1")[0].split("\n")
        self.assertIn("file1", result)
        self.assertIn("file2", result)
        result = backport_command.cmd("git log --format='%s'")[0].split("\n")
        self.assertIn("Add file1", result)
        self.assertIn("Add file2", result)
        backport_command.cmd("rm -rf %s" % tempdir)

    @patch("backport_command.post_comment")
    @patch("backport_command.create_pr")
    @patch("backport_command.get_pr_commits")
    def testDryRun(self, get_pr_commits, create_pr, post_comment):
        tempdir = tempfile.mkdtemp()
        os.chdir(tempdir)
        backport_command.cmd("git init --initial-branch=main")
        self.addFile("file1")
        backport_command.cmd("git branch feature/backport-target")
        self.addFile("file2")
        backport_command.cmd("git remote add origin ./.git")
        backport_command.cmd("git fetch --all")
        commit_hash = backport_command.cmd("git log -1 --format='%H'")[0].strip()
        get_pr_commits.return_value = [commit_hash]
        pr_data = {
            "number": 1,
            "title": "Test PR #1",
            "_links": {
                "html": {
                    "href": "https://github.com/Cray-HPE/backport-command-action/pull/1"
                }
            }
        }
        auth_header = backport_command.get_auth_header("https://github.com/Cray-HPE/backport-command-action.git")
        backport_command.backport("feature/backport-target", pr_data, True, auth_header)
        result = backport_command.cmd("git status")[0].split("\n")
        self.assertIn("On branch backport/1-to-feature/backport-target", result)
        self.assertIn("Your branch is ahead of 'origin/feature/backport-target' by 1 commit.", result)
        self.assertIn("nothing to commit, working tree clean", result)
        result = backport_command.cmd("ls -1")[0].split("\n")
        self.assertIn("file1", result)
        self.assertIn("file2", result)
        result = backport_command.cmd("git log --format='%s'")[0].split("\n")
        self.assertIn("Add file1", result)
        self.assertIn("Add file2", result)
        backport_command.cmd("rm -rf %s" % tempdir)

    @patch("backport_command.post_comment")
    @patch("backport_command.create_pr")
    @patch("backport_command.get_pr_commits")
    def testSkipMergeCommit(self, get_pr_commits, create_pr, post_comment):
        tempdir = tempfile.mkdtemp()
        os.chdir(tempdir)
        backport_command.cmd("git init --initial-branch=main")
        self.addFile("file1")
        backport_command.cmd("git branch feature/backport-target")
        self.addFile("file2")
        backport_command.cmd("git checkout feature/backport-target")
        backport_command.cmd("git merge --no-ff main")
        backport_command.cmd("git checkout main")
        self.addFile("file3")
        backport_command.cmd("git remote add origin ./.git")
        backport_command.cmd("git fetch --all")
        commit_hash = backport_command.cmd("git log -1 --format='%H'")[0].strip()
        get_pr_commits.return_value = [commit_hash]
        pr_data = {
            "number": 1,
            "title": "Test PR #1",
            "_links": {
                "html": {
                    "href": "https://github.com/Cray-HPE/backport-command-action/pull/1"
                }
            }
        }
        auth_header = backport_command.get_auth_header("https://github.com/Cray-HPE/backport-command-action.git")
        backport_command.backport("feature/backport-target", pr_data, False, auth_header)
        result = backport_command.cmd("git status")[0].split("\n")
        self.assertIn("On branch backport/1-to-feature/backport-target", result)
        self.assertIn("Your branch is up to date with 'origin/backport/1-to-feature/backport-target'.", result)
        self.assertIn("nothing to commit, working tree clean", result)
        result = backport_command.cmd("ls -1")[0].split("\n")
        self.assertIn("file1", result)
        self.assertIn("file2", result)
        self.assertIn("file3", result)
        result = backport_command.cmd("git log --format='%s'")[0].split("\n")
        self.assertIn("Add file1", result)
        self.assertIn("Add file2", result)
        self.assertIn("Add file3", result)
        result = backport_command.cmd("git log --merges --format='%s' main..HEAD")[0].split("\n")
        self.assertIn("Merge branch 'main' into feature/backport-target", result)
        backport_command.cmd("rm -rf %s" % tempdir)


if __name__ == '__main__':
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
