"""BugsInPy extraction pipeline for huatuo.

Extracts buggy/fixed Python source file pairs from BugsInPy into a structured
directory with JSONL manifests containing pairing metadata.

Usage:
    python bugsinpy_extract.py --project thefuck

See HUA-2116-PRP for full specification.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ExtractionReport:
    """Summary statistics from a BugsInPy extraction run."""

    project: str = ""
    total_bugs: int = 0
    extracted_bugs: int = 0
    skipped_bugs: int = 0
    total_buggy_files: int = 0
    total_fixed_files: int = 0
    multi_file_bugs: int = 0
    test_files_excluded: int = 0
    skip_reasons: dict[int, str] = field(default_factory=dict)


@dataclass
class BugExtractionResult:
    """Result of extracting a single bug's file pairs."""

    bug_id: int = 0
    buggy_files: list[str] = field(default_factory=list)
    fixed_files: list[str] = field(default_factory=list)
    test_files_excluded: int = 0
    is_multi_file: bool = False


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


class BugsInPyExtractor:
    """Extracts buggy/fixed Python source files from BugsInPy.

    Clones the target project once, then uses git show to extract
    only the affected files for each bug. This avoids checking out
    the entire working tree per bug (which BugsInPy's own framework
    does, costing hundreds of MB per checkout).
    """

    # License mapping for known BugsInPy projects
    _PROJECT_LICENSES: dict[str, str] = {
        "thefuck": "MIT",
        "scrapy": "BSD-3-Clause",
        "httpie": "BSD-3-Clause",
        "black": "MIT",
        "cookiecutter": "BSD-3-Clause",
        "fastapi": "MIT",
        "keras": "Apache-2.0",
        "luigi": "Apache-2.0",
        "matplotlib": "PSF-based",
        "pandas": "BSD-3-Clause",
        "PySnooper": "MIT",
        "sanic": "MIT",
        "spacy": "MIT",
        "tornado": "Apache-2.0",
        "tqdm": "MIT",
        "youtube-dl": "Unlicense",
        "ansible": "GPL-3.0",
    }

    def __init__(
        self,
        bugsinpy_root: str = "data/BugsInPy",
        output_root: str = "data/bugsinpy",
        repos_root: str = "data/repos",
        project: str = "thefuck",
        exclude_tests: bool = True,
    ) -> None:
        self.bugsinpy_root = Path(bugsinpy_root)
        self.output_root = Path(output_root)
        self.repos_root = Path(repos_root)
        self.project = project
        self.exclude_tests = exclude_tests

        self._project_dir = self.bugsinpy_root / "projects" / project
        if not self._project_dir.exists():
            raise FileNotFoundError(f"BugsInPy project not found: {self._project_dir}")

    def extract_all(self) -> ExtractionReport:
        """Extract all bugs for the configured project.

        Returns:
            ExtractionReport with summary statistics.
        """
        report = ExtractionReport(project=self.project)

        # Clone or reuse the project repo
        repo_path = self._clone_or_reuse_project()

        # Discover bugs
        bugs_dir = self._project_dir / "bugs"
        if not bugs_dir.exists():
            return report

        bug_dirs = sorted(
            [d for d in bugs_dir.iterdir() if d.is_dir()],
            key=lambda d: int(d.name),
        )
        report.total_bugs = len(bug_dirs)

        # Prepare output directories
        project_output = self.output_root / self.project
        buggy_dir = project_output / "buggy"
        fixed_dir = project_output / "fixed"
        buggy_dir.mkdir(parents=True, exist_ok=True)
        fixed_dir.mkdir(parents=True, exist_ok=True)

        # Manifest entries
        buggy_manifest: list[dict] = []
        fixed_manifest: list[dict] = []

        license_str = self._PROJECT_LICENSES.get(self.project, "Unknown")

        for bug_dir in bug_dirs:
            bug_id = int(bug_dir.name)
            result = self._extract_bug(bug_id, bug_dir, repo_path)

            if result is None:
                report.skipped_bugs += 1
                continue

            report.extracted_bugs += 1
            report.total_buggy_files += len(result.buggy_files)
            report.total_fixed_files += len(result.fixed_files)
            report.test_files_excluded += result.test_files_excluded

            if result.is_multi_file:
                report.multi_file_bugs += 1

            # Read commit IDs for manifest
            bug_info = self._read_bug_info(bug_dir)
            buggy_commit = bug_info.get("buggy_commit_id", "")
            fixed_commit = bug_info.get("fixed_commit_id", "")

            # Build manifest entries (paths relative to manifest directory)
            for buggy_path in result.buggy_files:
                affected_file = self._extract_affected_file(buggy_path, bug_id, "buggy")
                rel_path = str(Path(buggy_path).relative_to(project_output))
                buggy_manifest.append(
                    {
                        "bug_id": bug_id,
                        "project": self.project,
                        "variant": "buggy",
                        "path": rel_path,
                        "source": "BugsInPy",
                        "license": license_str,
                        "buggy_commit": buggy_commit,
                        "fixed_commit": fixed_commit,
                        "affected_file": affected_file,
                    }
                )

            for fixed_path in result.fixed_files:
                affected_file = self._extract_affected_file(fixed_path, bug_id, "fixed")
                rel_path = str(Path(fixed_path).relative_to(project_output))
                fixed_manifest.append(
                    {
                        "bug_id": bug_id,
                        "project": self.project,
                        "variant": "fixed",
                        "path": rel_path,
                        "source": "BugsInPy",
                        "license": license_str,
                        "buggy_commit": buggy_commit,
                        "fixed_commit": fixed_commit,
                        "affected_file": affected_file,
                    }
                )

        # Write manifests
        self._write_manifest(buggy_manifest, project_output / "manifest_buggy.jsonl")
        self._write_manifest(fixed_manifest, project_output / "manifest_fixed.jsonl")

        # Report skip reasons
        report.skip_reasons = {
            bug_id: reason for bug_id, reason in report.skip_reasons.items()
        }

        return report

    def _clone_or_reuse_project(self) -> Path:
        """Clone the project repo or reuse an existing clone.

        Returns:
            Path to the cloned repo.
        """
        repo_path = self.repos_root / self.project
        if repo_path.exists() and (repo_path / ".git").exists():
            # Fetch latest to ensure we have all commits
            subprocess.run(
                ["git", "fetch", "--all"],
                cwd=str(repo_path),
                capture_output=True,
                timeout=120,
            )
            return repo_path

        # Read github_url from project.info
        project_info = self._project_dir / "project.info"
        github_url = ""
        if project_info.exists():
            for line in project_info.read_text().splitlines():
                if line.startswith("github_url="):
                    github_url = line.split("=", 1)[1].strip().strip('"')
                    break

        if not github_url:
            raise RuntimeError(f"Cannot find github_url for project {self.project}")

        # Clone
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", github_url, str(repo_path)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed for {self.project}: {result.stderr}")
        return repo_path

    def _read_bug_info(self, bug_dir: Path) -> dict[str, str]:
        """Parse bug.info file into a dict."""
        info: dict[str, str] = {}
        info_file = bug_dir / "bug.info"
        if not info_file.exists():
            return info
        for line in info_file.read_text().splitlines():
            line = line.strip()
            if "=" in line:
                key, value = line.split("=", 1)
                info[key.strip()] = value.strip().strip('"')
        return info

    def _get_affected_files(
        self, repo_path: Path, buggy_commit: str, fixed_commit: str
    ) -> list[str]:
        """Get list of affected Python files between two commits.

        Uses git diff --name-only to find changed files, then filters
        to .py files only. Excludes test files if configured.

        Returns:
            List of relative file paths (within the repo).
        """
        result = subprocess.run(
            ["git", "diff", "--name-only", buggy_commit, fixed_commit],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return []

        all_files = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]

        # Filter to .py files only
        py_files = [f for f in all_files if f.endswith(".py")]

        return py_files

    def _is_test_file(self, path: str) -> bool:
        """Check if a file path is a test file.

        Matches: test_*.py, *_test.py, paths containing /tests/
        """
        basename = Path(path).name
        if basename.startswith("test_") and basename.endswith(".py"):
            return True
        if basename.endswith("_test.py"):
            return True
        if "/tests/" in path or path.startswith("tests/"):
            return True
        return False

    def _extract_bug(
        self, bug_id: int, bug_dir: Path, repo_path: Path
    ) -> BugExtractionResult | None:
        """Extract a single bug's file pairs.

        Returns:
            BugExtractionResult on success, None if bug should be skipped.
        """
        bug_info = self._read_bug_info(bug_dir)
        buggy_commit = bug_info.get("buggy_commit_id", "")
        fixed_commit = bug_info.get("fixed_commit_id", "")

        if not buggy_commit or not fixed_commit:
            return None

        # Get affected files
        affected_files = self._get_affected_files(repo_path, buggy_commit, fixed_commit)

        if not affected_files:
            return None

        # Separate test and non-test files
        test_files_excluded = 0
        source_files = []
        for f in affected_files:
            if self.exclude_tests and self._is_test_file(f):
                test_files_excluded += 1
            else:
                source_files.append(f)

        if not source_files:
            return None

        # Extract each affected source file
        result = BugExtractionResult(
            bug_id=bug_id,
            test_files_excluded=test_files_excluded,
            is_multi_file=len(source_files) > 1,
        )

        project_output = self.output_root / self.project

        for src_file in source_files:
            # Extract buggy version
            buggy_path = self._extract_file_version(
                repo_path,
                buggy_commit,
                src_file,
                project_output / "buggy" / f"bug_{bug_id}",
            )
            # Extract fixed version
            fixed_path = self._extract_file_version(
                repo_path,
                fixed_commit,
                src_file,
                project_output / "fixed" / f"bug_{bug_id}",
            )

            if buggy_path is not None:
                result.buggy_files.append(buggy_path)
            if fixed_path is not None:
                result.fixed_files.append(fixed_path)

        # If no files were successfully extracted, skip
        if not result.buggy_files and not result.fixed_files:
            return None

        return result

    def _extract_file_version(
        self, repo_path: Path, commit: str, file_path: str, output_dir: Path
    ) -> str | None:
        """Extract a single file at a specific commit using git show.

        Returns:
            The output file path as string, or None if extraction failed.
        """
        git_result = subprocess.run(
            ["git", "show", f"{commit}:{file_path}"],
            cwd=str(repo_path),
            capture_output=True,
            timeout=30,
        )
        if git_result.returncode != 0:
            return None

        # Write to output
        out_file = output_dir / file_path
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(git_result.stdout)

        return str(out_file)

    def _extract_affected_file(
        self, output_path: str, bug_id: int, variant: str
    ) -> str:
        """Extract the affected_file relative path from a full output path.

        Given: data/bugsinpy/thefuck/buggy/bug_1/thefuck/rules/pip.py
        Returns: thefuck/rules/pip.py
        """
        marker = f"{variant}/bug_{bug_id}/"
        idx = output_path.find(marker)
        if idx >= 0:
            return output_path[idx + len(marker) :]
        return output_path

    def _write_manifest(self, entries: list[dict], path: Path) -> None:
        """Write manifest entries to a JSONL file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Extract buggy/fixed file pairs from BugsInPy"
    )
    parser.add_argument(
        "--project",
        default="thefuck",
        help="BugsInPy project name (default: thefuck)",
    )
    parser.add_argument(
        "--bugsinpy-root",
        default="data/BugsInPy",
        help="Path to BugsInPy repository (default: data/BugsInPy)",
    )
    parser.add_argument(
        "--output-root",
        default="data/bugsinpy",
        help="Output directory root (default: data/bugsinpy)",
    )
    parser.add_argument(
        "--repos-root",
        default="data/repos",
        help="Cached repo clones directory (default: data/repos)",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Include test files (default: exclude)",
    )

    args = parser.parse_args()

    extractor = BugsInPyExtractor(
        bugsinpy_root=args.bugsinpy_root,
        output_root=args.output_root,
        repos_root=args.repos_root,
        project=args.project,
        exclude_tests=not args.include_tests,
    )

    print(f"Extracting {args.project} bugs from BugsInPy...")
    report = extractor.extract_all()

    print(f"\nExtraction Report ({report.project}):")
    print(f"  Total bugs:            {report.total_bugs}")
    print(f"  Extracted bugs:        {report.extracted_bugs}")
    print(f"  Skipped bugs:          {report.skipped_bugs}")
    print(f"  Buggy files:           {report.total_buggy_files}")
    print(f"  Fixed files:           {report.total_fixed_files}")
    print(f"  Multi-file bugs:       {report.multi_file_bugs}")
    print(f"  Test files excluded:   {report.test_files_excluded}")

    if report.skip_reasons:
        print("\n  Skip reasons:")
        for bug_id, reason in sorted(report.skip_reasons.items()):
            print(f"    Bug {bug_id}: {reason}")


if __name__ == "__main__":
    main()
