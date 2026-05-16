"""Run gosom/google-maps-scraper either as a native binary or via Docker.

Upstream docs:
- https://github.com/gosom/google-maps-scraper
- https://github.com/gosom/google-maps-scraper/blob/main/skills/google-maps-scraper/SKILL.md
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PLAYWRIGHT_CACHE_VOLUME = "gmaps-playwright-cache"


def _candidate_binaries() -> list[Path]:
    paths: list[Path] = []
    env_bin = os.getenv("GOSOM_BIN")
    if env_bin:
        paths.append(Path(env_bin))
    which = shutil.which("google-maps-scraper")
    if which:
        paths.append(Path(which))
    gobin = os.getenv("GOBIN")
    if gobin:
        paths.append(Path(gobin) / "google-maps-scraper")
    gopath = os.getenv("GOPATH") or str(Path.home() / "go")
    paths.append(Path(gopath) / "bin" / "google-maps-scraper")
    paths.append(Path.home() / "go" / "bin" / "google-maps-scraper")
    seen: set[Path] = set()
    out: list[Path] = []
    for p in paths:
        try:
            p = p.expanduser().resolve()
        except OSError:
            continue
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def find_native_binary() -> Path | None:
    for p in _candidate_binaries():
        if p.is_file() and os.access(p, os.X_OK):
            return p
    return None


def docker_available() -> bool:
    return shutil.which("docker") is not None


def _build_flags(
    *,
    depth: int,
    lang: str,
    extra_reviews: bool,
    exit_on_inactivity: str,
    email: bool,
    proxies: str | None,
    geo: str | None,
    zoom: int | None,
    radius: int | None,
    concurrency: int | None,
    grid_bbox: str | None,
    grid_cell: float | None,
    fast_mode: bool,
    extra_args: list[str] | None,
    input_path: str,
    results_path: str,
) -> list[str]:
    cmd = [
        "-input", input_path,
        "-results", results_path,
        "-json",
        "-exit-on-inactivity", exit_on_inactivity,
        "-lang", lang,
        "-depth", str(depth),
    ]
    if extra_reviews:
        cmd.append("-extra-reviews")
    if email:
        cmd.append("-email")
    if fast_mode:
        cmd.append("-fast-mode")
    if proxies:
        cmd.extend(["-proxies", proxies])
    if geo:
        cmd.extend(["-geo", geo])
    if zoom is not None:
        cmd.extend(["-zoom", str(zoom)])
    if radius is not None:
        cmd.extend(["-radius", str(radius)])
    if concurrency is not None:
        cmd.extend(["-c", str(concurrency)])
    if grid_bbox:
        cmd.extend(["-grid-bbox", grid_bbox])
    if grid_cell is not None:
        cmd.extend(["-grid-cell", str(grid_cell)])
    if extra_args:
        cmd.extend(extra_args)
    return cmd


def run_native(
    queries_file: Path,
    results_json: Path,
    *,
    binary: Path,
    depth: int = 5,
    lang: str = "en",
    extra_reviews: bool = True,
    exit_on_inactivity: str = "8m",
    email: bool = False,
    proxies: str | None = None,
    geo: str | None = None,
    zoom: int | None = None,
    radius: int | None = None,
    concurrency: int | None = None,
    grid_bbox: str | None = None,
    grid_cell: float | None = None,
    fast_mode: bool = False,
    extra_args: list[str] | None = None,
    log_file: Path | None = None,
) -> None:
    qpath = queries_file.resolve()
    if not qpath.is_file():
        raise FileNotFoundError(f"Queries file not found: {qpath}")
    results_json.parent.mkdir(parents=True, exist_ok=True)
    results_json.touch(exist_ok=True)
    rpath = results_json.resolve()

    flags = _build_flags(
        depth=depth,
        lang=lang,
        extra_reviews=extra_reviews,
        exit_on_inactivity=exit_on_inactivity,
        email=email,
        proxies=proxies,
        geo=geo,
        zoom=zoom,
        radius=radius,
        concurrency=concurrency,
        grid_bbox=grid_bbox,
        grid_cell=grid_cell,
        fast_mode=fast_mode,
        extra_args=extra_args,
        input_path=str(qpath),
        results_path=str(rpath),
    )
    cmd = [str(binary), *flags]

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("w", encoding="utf-8") as lf:
            subprocess.run(cmd, check=True, stdout=lf, stderr=subprocess.STDOUT)
    else:
        subprocess.run(cmd, check=True)


def run_docker(
    queries_file: Path,
    results_json: Path,
    *,
    image: str = "gosom/google-maps-scraper",
    depth: int = 5,
    lang: str = "en",
    extra_reviews: bool = True,
    exit_on_inactivity: str = "8m",
    email: bool = False,
    pull: bool = False,
    proxies: str | None = None,
    geo: str | None = None,
    zoom: int | None = None,
    radius: int | None = None,
    concurrency: int | None = None,
    grid_bbox: str | None = None,
    grid_cell: float | None = None,
    fast_mode: bool = False,
    extra_args: list[str] | None = None,
) -> None:
    if not docker_available():
        raise RuntimeError(
            "Docker not found in PATH. Install Docker Desktop and ensure it is running, "
            "or install the native binary (see README)."
        )

    qpath = queries_file.resolve()
    if not qpath.is_file():
        raise FileNotFoundError(f"Queries file not found: {qpath}")
    results_json.parent.mkdir(parents=True, exist_ok=True)
    results_json.touch(exist_ok=True)
    rpath = results_json.resolve()

    if pull:
        subprocess.run(["docker", "pull", image], check=False)

    flags = _build_flags(
        depth=depth,
        lang=lang,
        extra_reviews=extra_reviews,
        exit_on_inactivity=exit_on_inactivity,
        email=email,
        proxies=proxies,
        geo=geo,
        zoom=zoom,
        radius=radius,
        concurrency=concurrency,
        grid_bbox=grid_bbox,
        grid_cell=grid_cell,
        fast_mode=fast_mode,
        extra_args=extra_args,
        input_path="/queries.txt",
        results_path="/results.json",
    )
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{PLAYWRIGHT_CACHE_VOLUME}:/opt",
        "-v", f"{qpath}:/queries.txt:ro",
        "-v", f"{rpath}:/results.json",
        image,
        *flags,
    ]
    subprocess.run(cmd, check=True)


def run_auto(
    queries_file: Path,
    results_json: Path,
    *,
    prefer: str = "auto",  # "auto" | "binary" | "docker"
    image: str = "gosom/google-maps-scraper",
    pull: bool = False,
    log_file: Path | None = None,
    **kwargs,
) -> str:
    """
    Choose runner based on `prefer` and what's installed. Returns the runner name used.
    """
    prefer = (prefer or "auto").lower()

    if prefer == "binary":
        bin_path = find_native_binary()
        if not bin_path:
            raise RuntimeError(
                "Native gosom binary not found. Install with:\n"
                "  brew install go && go install github.com/gosom/google-maps-scraper@latest\n"
                "Then re-run, or pass --runner docker if Docker is installed."
            )
        run_native(queries_file, results_json, binary=bin_path, log_file=log_file, **kwargs)
        return f"binary:{bin_path}"

    if prefer == "docker":
        run_docker(
            queries_file, results_json, image=image, pull=pull, **kwargs
        )
        return f"docker:{image}"

    bin_path = find_native_binary()
    if bin_path:
        run_native(queries_file, results_json, binary=bin_path, log_file=log_file, **kwargs)
        return f"binary:{bin_path}"
    if docker_available():
        run_docker(
            queries_file, results_json, image=image, pull=pull, **kwargs
        )
        return f"docker:{image}"
    raise RuntimeError(
        "Neither the native gosom binary nor Docker is available.\n"
        "Install one of:\n"
        "  • brew install go && go install github.com/gosom/google-maps-scraper@latest\n"
        "  • Docker Desktop (https://www.docker.com/products/docker-desktop/)"
    )
