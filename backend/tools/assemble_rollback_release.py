"""Build an old-application release that understands the additive 0016 schema."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tarfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
COMPAT_FILES = (
    Path("app/main.py"),
    Path("app/config.py"),
    Path("app/migrations.py"),
    Path("alembic/env.py"),
)


def _git(*args: str) -> str:
    completed = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return completed.stdout.strip()


def assemble(base_ref: str, output_dir: Path) -> Path:
    if output_dir.exists():
        raise ValueError("Output directory already exists; choose a new empty path.")
    base_commit = _git("rev-parse", "--verify", f"{base_ref}^{{commit}}")
    migration_files = sorted((BACKEND / "alembic" / "versions").glob("*.py"))
    if not any(path.name.startswith("0016_") for path in migration_files):
        raise ValueError("The current source tree does not contain migration 0016.")

    output_dir.mkdir(parents=True)
    archive = output_dir / "base-backend.tar"
    try:
        _git("archive", "--format=tar", "--output", str(archive), base_commit, "backend")
        with tarfile.open(archive, "r") as bundle:
            bundle.extractall(output_dir, filter="data")
        target = output_dir / "backend"
        for relative in COMPAT_FILES:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(BACKEND / relative, destination)
        versions = target / "alembic" / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        for source in migration_files:
            shutil.copy2(source, versions / source.name)
        archive.unlink()
        (target / "ROLLBACK_RELEASE.md").write_text(
            "# Migration-compatible rollback backend\n\n"
            f"Application source: `{base_commit}`\n"
            "Migration graph: current release, including additive revision 0016.\n\n"
            "Set `JOURNALME_AUTO_MIGRATE=false` and `JOURNALME_BOOTSTRAP_LOCAL_DATA=false`. "
            "The API startup checks the installed revision without applying migrations or seeding hosted data. "
            "Keep revision 0016 installed; do not run a downgrade.\n",
            encoding="utf-8",
        )
        return target
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", required=True, help="Prior working backend commit or tag.")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    target = assemble(args.base_ref, args.output_dir.resolve())
    print(f"Rollback build context ready: {target}")
    print(
        f"Build with: docker build -f {target / 'Dockerfile'} -t journalme-backend-rollback {target}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
