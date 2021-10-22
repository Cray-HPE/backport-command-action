#!/usr/bin/python
import os
import subprocess
import json
import re
import requests
import shutil
import sys
import base64

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
        print("::debug::Executing HTTP %s to %s" % (method, full_url))
        print("::debug::Headers:")
        for header in headers:
            print("::debug::    %s: %s" % (header, headers[header]))
        if data is not None:
            print("::debug::Request:")
            print("::debug::    %s" % json.dumps(data))
    if method == "GET":
        response = requests.get(full_url, headers = headers)
    elif method == "POST":
        response = requests.post(full_url, headers = headers, data = json.dumps(data))
    else:
        raise Exception("Unsupported HTTP method %s" % method)
    if os.environ.get("RUNNER_DEBUG") == "1":
        print("::debug::Response:")
        for line in response.text.split("\n"):
            print("::debug::    %s" % line)
    response.raise_for_status()
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
        print("::debug::Running command:")
        print("::debug::    %s" % cmd)
        print("::debug::Stdout:")
        print("\n".join(map(lambda x: "::debug::    %s" % x, result.stdout.strip().split("\n"))))
        print("::debug::Stderr:")
        print("\n".join(map(lambda x: "::debug::    %s" % x, result.stderr.strip().split("\n"))))
        print("::debug::Return code: %d" % result.returncode)
    if result.returncode != 0:
        raise(CommandException("\n".join([cmd, result.stdout, result.stderr])))
    return (result.stdout.strip(), result.stderr.strip())

def clone(url, pr_number):
    dir = os.path.basename(os.environ["GITHUB_REPOSITORY"])
    auth_token = base64.b64encode(("x-access-token:%s" % os.environ["GITHUB_TOKEN"]).encode()).decode()
    # GitHub automatically masks GITHUB_TOKEN, but not in base64-encoded form
    print("::add-mask::%s" % auth_token)
    print("Cleaning up directory %s" % dir)
    shutil.rmtree(dir, ignore_errors=True)
    print("Cloning repository %s into directory %s"  % (url, dir))
    cmd("git -c \"http.https://github.com.extraheader=Authorization: basic %s\" clone -q %s %s" % (auth_token, url, dir))
    os.chdir(dir)
    cmd("git config --local http.https://github.com.extraheader \"Authorization: basic %s\"" % auth_token)
    # Github stores refs to pr commits in refs/pull/<pr_number>/head for 90 days
    cmd("git fetch origin refs/pull/%d/head" % pr_number)

def is_merge_commit(commit):
    commit_data = cmd("git show %s --compact-summary" % commit)
    return True if re.search("^Merge:", commit_data[0], re.MULTILINE) else False

def backport(branch, pr_data, dry_run):
    pr_number = pr_data["number"]
    return_code = 0
    action = "Dry run backporting" if dry_run else "Backporting"
    print("::group::%s PR #%d into branch %s" % (action, pr_number, branch))
    try:
        backport_branch = "backport/%d-to-%s" % (pr_number, branch)
        if ("origin/%s" % backport_branch) in re.split("\s+", cmd("git branch -r")[0]):
            raise CommandException(("Branch `%s` already exists. It looks like backporting of this PR into branch\n" + \
                "`%s` had already been performed. To repeat backporting, you'll need to cleanup previous attempt first\n" + \
                "by deleting branch `%s`. If backport PR had already been created, it will be closed\n" +
                "automatically when branch is deleted.") % (backport_branch, branch, backport_branch))
        print("Checking out branch %s from origin/%s" % (backport_branch, branch))
        cmd("git checkout -b %s -t origin/%s" % (backport_branch, branch))
        print("Fetching list of PR commits to cherry-pick")
        commits = get_pr_commits(pr_number)
        for commit in commits:
            if is_merge_commit(commit):
                print("Ommitting merge commit %s" % commit)
            else:
                print("Cherry-picking commit %s" % commit)
                user_name = cmd("git log -1 --format=\"%%an\" %s" % commit)[0]
                user_email = cmd("git log -1 --format=\"%%ae\" %s" % commit)[0]
                cmd("git -c user.name=\"%s\" -c user.email=\"%s\" cherry-pick %s -x" % \
                    (user_name, user_email, commit))
        if dry_run:
            print("Skip pushing branches and creating backport PRs in dry run mode")
            post_comment(pr_number, "Dry run backporting into branch %s was successful." % branch)
        else:
            print("Pushing branch %s" % backport_branch)
            cmd("git push origin --set-upstream %s" % backport_branch)
            print("Creating new PR for backport into branch %s" % branch)
            new_pr_data = create_pr(backport_branch, branch, "[Backport %s] %s" % ( branch, pr_data["title"]), \
                "Backport of %s" % pr_data["_links"]["html"]["href"])
            print("Created PR #%d" % new_pr_data["number"])
            post_comment(pr_number, ("Backporting into branch %s was successful. New PR: %s") % (branch, new_pr_data["html_url"]))
    except CommandException as e:
        print("::error::Error occurred while %s into branch %s" % (action.lower(), branch))
        print(e.message)
        post_comment(pr_number, ("Error occured while %s into branch %s." +
                "\n\n<details><summary>Error</summary><pre>%s</pre></details>") % (action.lower(), branch, e.message))
        return_code = 1
    print("::endgroup::")
    return return_code

def main():
    with open(os.environ["GITHUB_EVENT_PATH"]) as f:
        event_data = json.load(f)
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
            sys.exit(0)
        clone(event_data["repository"]["clone_url"], pr_number)
        pr_data = get_pr(pr_number)
        return_code = 0
        for branch in branches:
            return_code += backport(branch, pr_data, dry_run)
        sys.exit(return_code)

main()
