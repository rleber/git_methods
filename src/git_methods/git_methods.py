"""
Work with Git repositories
"""

import os
import re
import subprocess
from pathlib import Path

import git
from rich import print


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
        self,
        repo_path: Path | str,
        dry_run: bool = False,
        verbose: bool = False,
        rich: bool = False,
    ):
        self.repo_path = Path(repo_path)
        self.dry_run = dry_run
        self.verbose = verbose
        self.repo = self.get_repo(repo_path)
        self._rich = rich

    @property
    def rich(self):
        return self._rich

    @rich.setter
    def rich(self, value: bool):
        self._rich = value

    @classmethod
    def is_repo(cls, path: Path) -> bool:
        """Is the specified path a Git repo"""
        return bool(cls.get_repo(path, fail=False))

    @classmethod
    def get_repo(cls, repo_path: Path, fail: bool = True) -> git.repo.base.Repo | None:
        """Get a Git repo object; handle failure"""
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

    def __str__(self) -> str:
        """Str representation"""
        return str(self.repo_path)

    # TODO change this to return a NamedTuple or dataclass
    def remote_parts(self, upstream: str = "origin") -> dict[str, str] | None:
        """Get the url of an upstream remote repository parsed into sections"""
        url = self.upstream_url(upstream)
        match = re.search(r"(.*)/([^/]+)/([^/]+)$", url)
        if match:
            return {"host": match[1], "owner": match[2], "repo": match[3]}
        else:
            return None

    def remote_host(self, upstream: str = "origin") -> str | None:
        """Get the host name of an upstream remote repo"""
        parts = self.remote_parts(upstream)
        if parts:
            return parts["host"]
        else:
            return None

    def remote_owner(self, upstream: str = "origin") -> str | None:
        """Get the owner name of a remote upstream repository"""
        parts = self.remote_parts(upstream)
        if parts:
            return parts["owner"]
        else:
            return None

    def remote_repo(self, upstream: str = "origin") -> str:
        """Get the repository name of a remote upstream repository"""
        parts = self.remote_parts(upstream)
        if parts:
            return parts["repo"]
        else:
            return None

    def remote_owner_and_repo(self, upstream="origin") -> str | None:
        """Get the owner/repo of a remote upstream repository"""
        parts = self.remote_parts(upstream)
        if parts:
            return f"{parts['owner']}/{parts['repo']}"
        else:
            return None

    def branch_exists(self, branch: str) -> bool:
        """Does a local branch exist?"""
        return branch in self.local_branches()

    def local_branches(self) -> list[str]:
        """Return a list of the names of all local branches"""
        return [branch.name for branch in self.repo.heads]

    def move_local_branch(self, old: str, new: str) -> None:
        """
        Move (i.e. rename) a local branch
        May raise GitMoveMissingBranchError, GitMoveBranchCollisionError,
        or GitMoveError
        """
        if not (old in self.local_branches()):
            raise GitMoveMissingBranchError(
                f"Can't find branch {old} in repo {self.repo_path}"
            )
        self.log(f"[green]Moved local branch {old} to {new}[/green]")
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

    def change_upstream_branch(self, local: str, new_upstream_branch: str) -> None:
        """
        Change the name of the upstream branch for a local branch
        May raise GitRemoteUpstreamAlreadySet or GitMoveBranchCollisionError
        """
        upstream_repo = self.get_upstream_repository(local)
        current_upstream_branch = self.get_upstream_branch(local)
        if current_upstream_branch == new_upstream_branch:
            raise GitRemoteUpstreamAlreadySet(
                f"Upstream branch is already {new_upstream_branch}"
            )
        if self.remote_branch_exists(new_upstream_branch, upstream=upstream_repo):
            raise GitMoveBranchCollisionError(
                f"Upstream branch {upstream_repo}/{new_upstream_branch} already exists"
            )
        self.log(
            f"[green]Moved upstream branch of {local} from {upstream_repo}/{current_upstream_branch} to {upstream_repo}/{new_upstream_branch}[/green]"
        )
        if self.enabled():
            local_branch = self.repo.heads[local]
            self.repo.git.push(
                "--set-upstream",
                upstream_repo,
                f"{local_branch.name}:{new_upstream_branch}",
            )

    # TODO Implement this
    def delete_remote_branch(
        self, upstream_branch: str, upstream: str = "origin"
    ) -> None:
        """
        Delete a branch on an upstream repo
        NOT IMPLEMENTED
        """
        self.log(f"[green]Deleted remote branch {upstream}/{upstream_branch}[green]")
        if self.enabled():
            self.log(
                "[red]gitmethods.Repo#delete_remote_branch is not implemented[/red]"
            )
            # This does not work:
            # origin = self.repo.remotes.origin
            # origin.push(refspec=f":{upstream}") # Apparently, this deletes the remote branch

    def change_remote_default_branch(
        self, upstream_branch: str, upstream: str = "origin"
    ) -> None:
        """
        Change remote default branch for an upstream repo
        May raise GitRemoteChangeDefaultError
        """
        self.log(
            f"[green]Changed remote default branch to {upstream}/{upstream_branch}[/green]"
        )
        if self.enabled():
            result = subprocess.run(
                [
                    "gh",
                    "repo",
                    "edit",
                    self.remote_owner_and_repo(upstream=upstream),
                    "--default-branch",
                    upstream_branch,
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

    def remote_branch_exists(
        self, upstream_branch: str, upstream: str = "origin"
    ) -> bool:
        """Checks if a branch exists in a remote Git repository without cloning."""
        # Format reference for exact branch match (e.g., refs/heads/main)
        ref_path = f"refs/heads/{upstream_branch}"

        # Run git ls-remote to query only that specific branch reference
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", self.upstream_url(upstream), ref_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        # Return True if the exit code is 0 (the reference exists)
        return result.returncode == 0

    def remotes(self) -> list[git.Remote]:
        return self.repo.remotes

    def get_upstream_branch(self, local_branch: str) -> str | None:
        """Get the name of the upstream branch for a local branch"""
        parts = self.get_upstream_branch_parts(local_branch)
        if not parts:
            res = None
        res = parts["branch"]
        return res

    def get_upstream_repository(self, local_branch: str) -> str | None:
        """Get the repository name of the upstream branch for a local branch"""
        parts = self.get_upstream_branch_parts(local_branch)
        if not parts:
            return None
        return parts["remote"]

    def get_upstream_branch_parts(self, local_branch: str) -> dict[str, str] | None:
        """
        Get the parts of the qualified upstream branch ref for a local branch
        Returns a dict: {"remote": str, "branch": str}
        """
        qualified_name = self.get_qualified_upstream_branch(local_branch)
        if not qualified_name:
            return None
        if match := re.fullmatch(r"(.*)/(.*)", qualified_name):
            res = {"remote": match[1], "branch": match[2]}
            return res
        else:
            raise GitRemoteError(f"Unable to parse upstream branch {qualified_name}")

    def get_qualified_upstream_branch(self, local_branch: str) -> str:
        """
        Get the qualified name of the upstream branch for a local branch
        e.g., "origin/develop"
        """
        try:
            # Fetch the specific local branch object
            local_branch = self.repo.heads[local_branch]

            # Get the remote tracking reference
            upstream_branch = local_branch.tracking_branch()

            # Returns 'origin/main' format if it exists
            if not upstream_branch:
                return None
            return upstream_branch.name

        except (KeyError, AttributeError):
            return None

    def get_remote_default_branch(self, remote_name: str = "origin") -> str | None:
        """Return the default branch name of a remote repository"""
        remote_info = self.repo.git.remote("show", remote_name)

        # Extract the default branch name from the output text
        match = re.search(r"\s*HEAD branch:\s*(.*)", remote_info)
        if match:
            return match.group(1)
        else:
            return None

    def upstream_url(self, remote_name: str = "origin") -> str:
        """
        Return the url of a remote repository
        May raise GitNotRepo or GitRemoteMissing
        """
        try:
            # Access the specific remote and extract its URL
            return self.repo.remote(name=remote_name).url
        except git.exc.InvalidGitRepositoryError:
            raise GitNotRepo(f"Error: {self.repo_path} is not a valid Git repository.")
        except ValueError:
            raise GitRemoteMissing(
                f"Error: Remote '{remote_name}' does not exist in {self.repo_path}"
            )

    def set_upstream_url(self, url: str, upstream: str = "origin") -> None:
        """Change the url of an upstream"""
        remote = self.repo.remote(name=upstream)
        remote.set_url(url)

    def logging(self) -> bool:
        """Should we be logging things?"""
        return self.verbose or self.dry_run

    def log(self, message: str, mandatory=False) -> None:
        """Print things to the log if we're being verbose"""
        message = f"[white]{self.repo_path}:[/white] " + message
        if not self.rich:
            message = re.sub(r"\[/?\w+\]", "", message)

        if mandatory or self.logging():
            print(message)

    def enabled(self) -> None:
        """Are we actually executing changes, or just doing a dry run?"""
        return not (self.dry_run)
