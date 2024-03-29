#!/usr/bin/python3
#
# MIT License
#
# (C) Copyright [2021] Hewlett Packard Enterprise Development LP
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
import logging
import os
import subprocess
import json
import re
import requests
import shutil
import sys
import base64
import urllib

class CommandException(Exception):
    def __init__(self, message):
        self.message = message

def http_call(url, method = "GET", data = None):
    full_url = "%s/%s" % (os.environ["GITHUB_API_URL"], url)
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": "Bearer %s" % os.environ["GITHUB_TOKEN"],
        "Content-Type": "application/json"
    }
    if os.environ.get("RUNNER_DEBUG") == "1":
        logging.debug("::debug::Executing HTTP %s to %s" % (method, full_url))
        logging.debug("::debug::Headers:")
        for header in headers:
            logging.debug("::debug::    %s: %s" % (header, headers[header]))
        if data is not None:
            logging.debug("::debug::Request:")
            logging.debug("::debug::    %s" % json.dumps(data))
    if method == "GET":
        response = requests.get(full_url, headers = headers)
    elif method == "POST":
        response = requests.post(full_url, headers = headers, data = json.dumps(data))
    else:
        raise CommandException("Unsupported HTTP method %s" % method)
    if os.environ.get("RUNNER_DEBUG") == "1":
        logging.debug("::debug::Response:")
        for line in response.text.split("\n"):
            logging.debug("::debug::    %s" % line)
    try:
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise(CommandException(str(e)))
    return json.loads(response.text)

def post_comment(pr_number, comment):
    return http_call(
        "repos/%s/issues/%d/comments" % (os.environ["GITHUB_REPOSITORY"], pr_number),
        "POST",
        {"body": comment}
    )

def create_pr(head, base, title, body):
    return http_call(
        "repos/%s/pulls" % os.environ["GITHUB_REPOSITORY"],
        "POST",
        {"head": head, "base": base, "title": title, "body": body}
    )

def get_pr(pr_number):
    return http_call("repos/%s/pulls/%d" % (os.environ["GITHUB_REPOSITORY"], pr_number))

def get_pr_commits(pr_number):
    return map(lambda x: x["sha"], http_call("repos/%s/pulls/%d/commits" % (os.environ["GITHUB_REPOSITORY"], pr_number)))

def cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, check=False, text=True)
    if os.environ.get("RUNNER_DEBUG"):
        logging.debug("::debug::Running command:")
        logging.debug("::debug::    %s" % cmd)
        logging.debug("::debug::Stdout:")
        logging.debug("\n".join(map(lambda x: "::debug::    %s" % x, result.stdout.strip().split("\n"))))
        logging.debug("::debug::Stderr:")
        logging.debug("\n".join(map(lambda x: "::debug::    %s" % x, result.stderr.strip().split("\n"))))
        logging.debug("::debug::Return code: %d" % result.returncode)
    if result.returncode != 0:
        raise(CommandException("\n".join([cmd, result.stdout, result.stderr])))
    return (result.stdout.strip(), result.stderr.strip())

def clone(url, branches, pr_number, auth_header):
    try:
        dir = os.path.basename(os.environ["GITHUB_REPOSITORY"])
        git = "git -c \"%s\"" % auth_header
        logging.info("Cleaning up directory %s" % dir)
        shutil.rmtree(dir, ignore_errors=True)
        logging.info("Cloning repository %s into directory %s"  % (url, dir))
        # Make a shallow clone (depth=1) of single default branch
        cmd("%s clone --depth=1 -q %s %s" % (git, url, dir))
        os.chdir(dir)
        # Fetch backport target branches, so that we can checkout them later
        branch_list = " ".join(branches)
        cmd("%s remote set-branches origin %s" % (git, branch_list))
        cmd("%s fetch --depth=1 origin %s" % (git, branch_list))
        # Github stores refs to pr commits in refs/pull/<pr_number>/head for 90 days.
        # Fetching it to cherry-pick individual commits from it later.
        cmd("%s fetch origin refs/pull/%d/head" % (git, pr_number))
    except CommandException as e:
        logging.error("::error::Error occurred while cloning repo %s" % url)
        logging.error(e.message)
        post_comment(pr_number, ("Error occured while cloning repo %s." +
                "\n\n<details><summary>Error</summary><pre>%s</pre></details>") % (url, e.message))

def is_merge_commit(commit):
    commit_data = cmd("git show %s --compact-summary" % commit)
    return True if re.search("^Merge:", commit_data[0], re.MULTILINE) else False

def backport(branch, pr_data, dry_run, auth_header):
    pr_number = pr_data["number"]
    return_code = 0
    action = "Dry run backporting" if dry_run else "Backporting"
    logging.info("::group::%s PR #%d into branch %s" % (action, pr_number, branch))
    try:
        backport_branch = "backport/%d-to-%s" % (pr_number, branch)
        if ("origin/%s" % backport_branch) in re.split("\s+", cmd("git branch -r")[0]):
            raise CommandException(("Branch `%s` already exists. It looks like backporting of this PR into branch\n" + \
                "`%s` had already been performed. To repeat backporting, you'll need to cleanup previous attempt first\n" + \
                "by deleting branch `%s`. If backport PR had already been created, it will be closed\n" +
                "automatically when branch is deleted.") % (backport_branch, branch, backport_branch))
        logging.info("Checking out branch %s from origin/%s" % (backport_branch, branch))
        cmd("git checkout -b %s -t origin/%s" % (backport_branch, branch))
        logging.info("Fetching list of PR commits to cherry-pick")
        commits = get_pr_commits(pr_number)
        for commit in commits:
            if is_merge_commit(commit):
                logging.info("Ommitting merge commit %s" % commit)
            else:
                logging.info("Cherry-picking commit %s" % commit)
                user_name = cmd("git log -1 --format=\"%%an\" %s" % commit)[0]
                user_email = cmd("git log -1 --format=\"%%ae\" %s" % commit)[0]
                cmd("git -c user.name=\"%s\" -c user.email=\"%s\" cherry-pick %s -x" % \
                    (user_name, user_email, commit))
        if dry_run:
            logging.info("Skip pushing branches and creating backport PRs in dry run mode")
            post_comment(pr_number, "Dry run backporting into branch %s was successful." % branch)
        else:
            logging.info("Pushing branch %s" % backport_branch)
            cmd("git -c \"%s\" push origin --set-upstream %s" % (auth_header, backport_branch))
            logging.info("Creating new PR for backport into branch %s" % branch)
            new_pr_data = create_pr(backport_branch, branch, "[Backport %s] %s" % ( branch, pr_data["title"]), \
                "Backport of %s" % pr_data["_links"]["html"]["href"])
            logging.info("Created PR #%d" % new_pr_data["number"])
            post_comment(pr_number, ("Backporting into branch %s was successful. New PR: %s") % (branch, new_pr_data["html_url"]))
    except CommandException as e:
        logging.error("::error::Error occurred while %s into branch %s" % (action.lower(), branch))
        logging.error(e.message)
        post_comment(pr_number, ("Error occured while %s into branch %s." +
                "\n\n<details><summary>Error</summary><pre>%s</pre></details>") % (action.lower(), branch, e.message))
        return_code = 1
    logging.info("::endgroup::")
    return return_code

def get_auth_header(url):
    auth_token = base64.b64encode(("x-access-token:%s" % os.environ["GITHUB_TOKEN"]).encode()).decode()
    # GitHub automatically masks GITHUB_TOKEN, but not in base64-encoded form
    logging.info("::add-mask::%s" % auth_token)
    parse_result = urllib.parse.urlparse(url)
    return "http.%s://%s.extraheader=Authorization: basic %s" % (parse_result.scheme, parse_result.hostname, auth_token)

def main(event_data):
    dry_run = False
    pr_number = event_data["issue"]["number"]
    # Sanitize multiline string - leave only chars allowed in branch names
    comment_body = re.sub("[^0-9a-zA-Z/\\-\\. ]", "", event_data["comment"]["body"])
    branches = re.split(" +", comment_body)
    if len(branches) > 0 and branches[0] == "/backport":
        branches = branches[1:]
        if len(branches) > 0 and branches[0] == "--dry-run":
            dry_run = True
            branches = branches[1:]
        if len(branches) == 0:
            post_comment(pr_number, "<pre>Usage: /backport [--dry-run] &lt;branch1&gt; [&lt;branch2&gt; ...]</pre>")
            return 0
        url = event_data["repository"]["clone_url"]
        auth_header = get_auth_header(url)
        clone(url, branches, pr_number, auth_header)
        pr_data = get_pr(pr_number)
        return_code = 0
        for branch in branches:
            return_code += backport(branch, pr_data, dry_run, auth_header)
        return return_code
    else:
        return 0

if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)
    with open(os.environ["GITHUB_EVENT_PATH"]) as f:
        return_code = main(json.load(f))
    sys.exit(return_code)
