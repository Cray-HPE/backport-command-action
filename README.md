# backport-command-action
Github action which performs backporting of changes in current PR to another branch, by cherry-picking every commit and creating a PR. Backporting is invoked by adding a command-style comment (`/backport`) to PR.

## Requirements
* Workflow should have permissions set to 'Read and Write'
* In case of using self-hosted runner, it needs to have Python 3 with `requests` module installed.

## Installation
Add this to `.github/workflow/backport.yaml`:

    name: backport

    on:
      issue_comment:
        types:
          - created

    jobs:
      backport:
        runs-on: self-hosted
        if: github.event.issue.pull_request
        steps:
          - uses: Cray-HPE/backport-command-action@main

## Usage
For a quck usage instruction, add a comment consisting of single `/backport` command to a PR. GitHub Bot will respond with a comment:

![image](https://user-images.githubusercontent.com/320082/140014292-9bcb5c13-d77f-436a-bafa-14a6210f4035.png)
    
For dry run, try backporting into some branch with `--dry-run` option. This will fork a new branch named `backport/<pr_number>-to-<target_branch>` from target branch (locally on a runner), and cherry-pick all commits from current PR into this branch. In dry run mode, backport branch will not be pushed to repository. Result (successful cherry-pick or merge conflict report) will be added as next comment:

![image](https://user-images.githubusercontent.com/320082/140014344-e7447501-b470-4a00-8971-ad99522a040e.png)

To perform backport, invoke command without `--dry-run` option. This will fork a new branch named `backport/<pr_number>-to-<target_branch>` from target branch, cherry-pick all commits from current PR into this branch, push the backport branch to the repo, and generate a new PR, proposing to merge backport branch into target branch. Result will be reported as comment. Additionally, since new PR will mention original PR, a note about this will be added:

![image](https://user-images.githubusercontent.com/320082/140014413-2a09d2f9-71a8-4caf-8c75-42798146bb00.png)

## Usage Notes
* Backporting can be performed at any stage - on unmerged PR's, or on PR's merged via 'Merge Commit', 'Squash' or 'Rebase' strategy.
* If backporting is done on unmerged PR, and changes were added later to the PR, backporting needs to be re-done. To do this, cleanup previous backport by deleting a branch named `backport/<pr_number>-to-<target_branch>` from repository. This will automatically close a PR generated for this branch.
* Commits from current PR are cherry-picked one by one, in the order they are added to original PR. However, merge commits are ommitted (in order to filter out original PR synchronizations with base branch).
* Backported commits can not include changes to workflow files, due to security limitation. Thus, backport command functionality can not be used to propagate itself . It needs to be done manually.

