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

import pytest
from rust_dependency_audit.src.cargo_parser import (
    CargoTomlPackage,
    CargoLockPackage,
    DeclaredDependency,
)
from rust_dependency_audit.src.score_crates import (
    ScoreCratesReference,
    ScoreCrateSpec,
)
from rust_dependency_audit.src.auditor import (
    RepositoryAuditData,
    CrateStatus,
    audit_repository,
    audit_organization,
)


@pytest.fixture
def sample_score_crates():
    crates = {
        "clap": ScoreCrateSpec(package="clap", version="4.5.4"),
        "tokio": ScoreCrateSpec(package="tokio", version="1.47.1"),
        "log": ScoreCrateSpec(package="log", version="0.4.27"),
    }
    aliases = {"clap": "@crate_index//:clap"}
    return ScoreCratesReference(crates=crates, aliases=aliases)


def test_audit_repository_managed_and_unmanaged(sample_score_crates):
    pkg1 = CargoTomlPackage(
        name="my_crate",
        version="0.1.0",
        path="crates/my_crate/Cargo.toml",
        dependencies=[
            DeclaredDependency(name="clap", version_req="4.5.4"),
            DeclaredDependency(name="tokio", version_req="1.30.0"),  # mismatch
            DeclaredDependency(
                name="custom_external", version_req="0.9.0"
            ),  # unmanaged
            DeclaredDependency(name="local_helper", is_path=True),  # internal path dep
        ],
    )

    lock1 = CargoLockPackage(
        name="clap",
        version="4.5.4",
    )
    lock2 = CargoLockPackage(
        name="tokio",
        version="1.30.0",
    )
    lock3 = CargoLockPackage(
        name="custom_external",
        version="0.9.0",
    )

    repo_data = RepositoryAuditData(
        name="eclipse-score/my_repo",
        is_archived=False,
        cargo_tomls=[pkg1],
        cargo_locks=[lock1, lock2, lock3],
    )

    result = audit_repository(repo_data, sample_score_crates)

    assert result.repo_name == "eclipse-score/my_repo"
    assert len(result.crates) == 3  # local_helper excluded

    crates_by_name = {c.crate_name: c for c in result.crates}

    assert crates_by_name["clap"].status == CrateStatus.MANAGED
    assert crates_by_name["clap"].score_crates_version == "4.5.4"

    assert crates_by_name["tokio"].status == CrateStatus.VERSION_MISMATCH
    assert crates_by_name["tokio"].requested_version == "1.30.0"
    assert crates_by_name["tokio"].score_crates_version == "1.47.1"

    assert crates_by_name["custom_external"].status == CrateStatus.UNMANAGED
    assert crates_by_name["custom_external"].score_crates_version is None


def test_audit_organization_aggregation(sample_score_crates):
    repo1 = RepositoryAuditData(
        name="eclipse-score/repo1",
        cargo_tomls=[
            CargoTomlPackage(
                name="c1",
                path="Cargo.toml",
                dependencies=[DeclaredDependency(name="clap", version_req="4.5.4")],
            )
        ],
    )
    repo2 = RepositoryAuditData(
        name="eclipse-score/repo2",
        cargo_tomls=[
            CargoTomlPackage(
                name="c2",
                path="Cargo.toml",
                dependencies=[
                    DeclaredDependency(name="clap", version_req="4.5.4"),
                    DeclaredDependency(name="serde_unknown", version_req="1.0.0"),
                ],
            )
        ],
    )

    report = audit_organization([repo1, repo2], sample_score_crates)

    assert report.total_repositories == 2
    assert report.rust_repositories_count == 2
    assert report.total_distinct_crates == 2
    assert report.managed_crates_count == 1
    assert report.unmanaged_crates_count == 1
    assert "clap" in report.crate_usage_summary
    assert len(report.crate_usage_summary["clap"].used_in_repos) == 2
