# backport-command-action
Github action which performs backporting of changes in current PR to another branch, by cherry-picking every commit and creating a PR. Backporting is invoked by adding a command-style comment (`/backport`) to PR.

## Installation
Add this to `.github/workflow/backport.yaml`:

    name: backport

    on:
      issue_comment:
        types:
          - created

    jobs:
      backport:
        runs-on: ubuntu-latest
        steps:
          - uses: Cray-HPE/backport-command-action@v1

## Usage
For a quck usage instruction, add a comment consisting of single `/backport` command to a PR. GitHub Bot will respond with a comment:

    /backport
    Usage: /backport [--dry-run] <branch1> [<branch2> ...]
    
For dry run, try backporting into some branch with `--dry-run` option. This will fork a new branch named `backport/<pr_number>-to-<target_branch>` from target branch (locally on a runner), and cherry-pick all commits from current PR into this branch. In dry run mode, backport branch will not be pushed to repository. Result (successful cherry-pick or merge conflict report) will be added as next comment:

    /backport --dry-run release/1.0
    Dry run backporting into branch release/1.0 was successful.

To perform backport, invoke command without `--dry-run` option. This will fork a new branch named `backport/<pr_number>-to-<target_branch>` from target branch, cherry-pick all commits from current PR into this branch, push the backport branch to the repo, and generate a new PR, proposing to merge backport branch into target branch. Result will be reported as comment. Additionally, since new PR will mention original PR, a note about this will be added:

    /backport release/1.0
    github-actions bot mentioned this pull request now
        [Backport release/1.0] Original PR suject #2
    Backporting into branch release/1.0 was successful. New PR: #2

## Usage Notes
* Backporting can be performed at any stage - on unmerged PR's, or on PR's merged via 'Merge Commit', 'Squash' or 'Rebase' strategy.
* If backporting is done on unmerged PR, and changes were added later to the PR, backporting needs to be re-done. To do this, cleanup previous backport by deleting a branch named `backport/<pr_number>-to-<target_branch>` from repository. This will automatically close a PR generated for this branch.
* Commits from current PR are cherry-picked one by one, in the order they are added to original PR. However, merge commits are ommitted (in order to filter out original PR synchronizations with base branch).
