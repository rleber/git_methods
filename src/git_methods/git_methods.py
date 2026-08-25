"""
Work with Git repositories
"""

import os
import re
import subprocess
from pathlib import Path

import git


class GitError(RuntimeError):
    pass


class GitNotRepo(GitError):
    pass


class GitRemoteError(GitError):
    pass


class GitRemoteMissing(GitRemoteError):
    pass


class GitRemoteUpstreamAlreadySet(GitRemoteError):
    pass


class GitRemoteChangeDefaultError(GitRemoteError):
    pass


class GitMoveError(GitError):
    pass


class GitMoveMissingBranchError(GitMoveError):
    pass


class GitMoveBranchCollisionError(GitMoveError):
    pass


class Repo:
    def __init__(
        self, repo_path: Path | str, dry_run: bool = False, verbose: bool = False
    ):
        self.repo_path = Path(repo_path)
        self.dry_run = dry_run
        self.verbose = verbose
        self.repo = self.get_repo(repo_path)

    @classmethod
    def is_repo(cls, path):
        return cls.get_repo(path, fail=False)

    @classmethod
    def get_repo(cls, repo_path, fail=True):
        try:
            # Open the local repository
            repo = git.Repo(repo_path)
        except git.exc.NoSuchPathError as e:
            if fail:
                raise e  # noqa
            else:
                return None
        except git.exc.InvalidGitRepositoryError as e:
            if fail:
                raise e  # noqa
            else:
                return None
        return repo

    def __str__(self):
        return str(self.repo_path)

    def remote_parts(self):
        url = self.upstream_url()
        match = re.search(r"(.*)/([^/]+)/([^/]+)$", url)
        if match:
            return {"host": match[1], "owner": match[2], "repo": match[3]}
        else:
            return None

    def remote_host(self):
        parts = self.remote_parts()
        if parts:
            return parts["host"]
        else:
            return None

    def remote_owner(self):
        parts = self.remote_parts()
        if parts:
            return parts["owner"]
        else:
            return None

    def remote_repo(self):
        parts = self.remote_parts()
        if parts:
            return parts["repo"]
        else:
            return None

    def remote_owner_and_repo(self):
        parts = self.remote_parts()
        if parts:
            return f"{parts['repo']}/{parts['repo']}"
        else:
            return None

    def branch_exists(self, branch):
        return branch in self.local_branches()

    def local_branches(self):
        return [branch.name for branch in self.repo.heads]

    def move_local_branch(self, old, new):
        if not (old in self.local_branches()):
            raise GitMoveMissingBranchError(
                f"Can't find branch {old} in repo {self.repo_path}"
            )
        self.log(f"Move local branch {old} to {new}")
        if self.enabled():
            try:
                os.chdir(self.repo_path)
                # Run the git branch -m command
                subprocess.run(
                    ["git", "branch", "-m", old, new],
                    capture_output=True,
                    text=True,
                    check=True,
                )

            except subprocess.CalledProcessError as e:
                msg = e.stderr.strip()
                if "Can't find branch" in msg:
                    raise GitMoveMissingBranchError(f"Can't find branch {old}")
                if "already exists" in msg:
                    raise GitMoveBranchCollisionError(f"Branch {new} already exists")
                raise GitMoveError(f"Error renaming branch: {msg}")

    def change_upstream_branch(self, local, new_upstream):
        current_upstream = self.get_upstream_branch(local)
        if current_upstream == new_upstream:
            raise GitRemoteUpstreamAlreadySet(
                f"Upstream branch is already {new_upstream}"
            )
        if self.remote_branch_exists(new_upstream):
            raise GitMoveBranchCollisionError(
                f"Upstream branch {new_upstream} already exists"
            )
        self.log(
            f"Move upstream branch of {local} from {current_upstream} to {new_upstream}"
        )
        if self.enabled():
            local_branch = self.repo.heads[local]
            origin = self.repo.remotes.origin
            self.repo.git.push(
                "--set-upstream", origin, f"{local_branch.name}:{new_upstream}"
            )

    def delete_remote_branch(self, upstream):
        self.log(f"Delete remote branch {upstream}")
        if self.enabled():
            print("gitmethods.Repo#delete_remote_branch unimplemented")
            # This does not work:
            # origin = self.repo.remotes.origin
            # origin.push(refspec=f":{upstream}") # Apparently, this deletes the remote branch

    def change_remote_default_branch(self, upstream):
        self.log(f"Change remote default branch to {upstream}")
        if self.enabled():
            result = subprocess.run(
                [
                    "gh",
                    "repo",
                    "edit",
                    self.remote_owner_and_repo(),
                    "--default-branch",
                    upstream,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
            # Return True if the exit code is 0 (the reference exists)
            if result.returncode != 0:
                raise GitRemoteChangeDefaultError(
                    "Unable to change remote default branch"
                )

    def remote_branch_exists(self, upstream):
        """Checks if a branch exists in a remote Git repository without cloning."""
        # Format reference for exact branch match (e.g., refs/heads/main)
        ref_path = f"refs/heads/{upstream}"

        # Run git ls-remote to query only that specific branch reference
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", self.upstream_url(), ref_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        # Return True if the exit code is 0 (the reference exists)
        return result.returncode == 0

    def get_upstream_branch(self, local_branch):
        try:
            # Fetch the specific local branch object
            local_branch = self.repo.heads[local_branch]

            # Get the remote tracking reference
            upstream = local_branch.tracking_branch()

            # Returns 'origin/main' format if it exists
            if not upstream:
                return None
            qualified_name = upstream.name
            if match := re.fullmatch(r".*/(.*)", qualified_name):
                return match[1]
            else:
                return qualified_name

        except (KeyError, AttributeError):
            return None

    def get_remote_default_branch(self, remote_name="origin"):
        remote_info = self.repo.git.remote("show", "origin")

        # Extract the default branch name from the output text
        match = re.search(r"\s*HEAD branch:\s*(.*)", remote_info)
        if match:
            return match.group(1)
        else:
            return None

    def upstream_url(self, remote_name="origin"):
        try:
            # Access the specific remote and extract its URL
            return self.repo.remote(name=remote_name).url
        except git.exc.InvalidGitRepositoryError:
            raise GitNotRepo(f"Error: {self.repo_path} is not a valid Git repository.")
        except ValueError:
            raise GitRemoteMissing(
                f"Error: Remote '{remote_name}' does not exist in {self.repo_path}"
            )

    def logging(self):
        return self.verbose or self.dry_run

    def log(self, message):
        if self.logging():
            print(f"{self.repo_path}: {message}")

    def enabled(self):
        return not (self.dry_run)
