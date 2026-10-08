# *******************************************************************************
# Copyright (c) 2026 Contributors to the Eclipse Foundation
#
# See the NOTICE file(s) distributed with this work for additional
# information regarding copyright ownership.
#
# This program and the accompanying materials are made available under the
# terms of the Apache License Version 2.0 which is available at
# https://www.apache.org/licenses/LICENSE-2.0
#
# SPDX-License-Identifier: Apache-2.0
# *******************************************************************************


from rust_dependency_audit.src.github_client import GitHubClient
from rust_dependency_audit.src.cli import main


def test_github_client_token_masking():
    token = "secret_github_token_value_xyz"
    client = GitHubClient(token=token)

    # Ensure repr or str never prints the token
    assert token not in str(client)
    assert token not in repr(client)
    assert "secret" not in repr(client)


def test_cli_local_scan_mode(tmp_path):
    # Setup mock local repo with Cargo.toml
    repo_dir = tmp_path / "test_repo"
    repo_dir.mkdir()
    cargo_toml = repo_dir / "Cargo.toml"
    cargo_toml.write_text("""
[package]
name = "test_pkg"
version = "0.1.0"

[dependencies]
clap = "4.5.4"
""")

    # Mock score-crates reference files
    ref_dir = tmp_path / "score-crates"
    ref_dir.mkdir()
    (ref_dir / "MODULE.bazel").write_text("""
crate.spec(
    package = "clap",
    version = "4.5.4",
)
""")
    (ref_dir / "BUILD").write_text("""
alias(name = "clap", actual = "@crate_index//:clap")
""")

    out_dir = tmp_path / "output"

    exit_code = main(
        [
            "--local-scan-dir",
            str(tmp_path),
            "--local-reference-dir",
            str(ref_dir),
            "--output-dir",
            str(out_dir),
            "--org",
            "test-org",
        ]
    )

    assert exit_code == 0
    assert (out_dir / "index.html").exists()
    assert (out_dir / "rust_dependency_audit.json").exists()
    assert (out_dir / "rust_dependency_audit.md").exists()

    html_content = (out_dir / "index.html").read_text()
    assert "test_pkg" in html_content or "test_repo" in html_content
    assert "clap" in html_content
