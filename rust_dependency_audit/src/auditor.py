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

"""Auditor engine cross-referencing repository crates with score-crates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .cargo_parser import CargoLockPackage, CargoTomlPackage
from .score_crates import ScoreCratesReference


class CrateStatus(str, Enum):
    """Classification of crate dependency against score-crates."""

    MANAGED = "MANAGED"
    VERSION_MISMATCH = "VERSION_MISMATCH"
    UNMANAGED = "UNMANAGED"


@dataclass
class AuditedCrate:
    """Represents an audited crate used within a repository."""

    crate_name: str
    status: CrateStatus
    requested_version: str | None = None
    resolved_version: str | None = None
    score_crates_version: str | None = None
    features: list[str] = field(default_factory=list)
    dep_types: list[str] = field(default_factory=list)
    manifest_paths: list[str] = field(default_factory=list)


@dataclass
class RepositoryAuditData:
    """Input data for a repository collected from GitHub."""

    name: str
    is_archived: bool = False
    cargo_tomls: list[CargoTomlPackage] = field(default_factory=list)
    cargo_locks: list[CargoLockPackage] = field(default_factory=list)


@dataclass
class AuditedRepository:
    """Result of auditing a single repository."""

    repo_name: str
    is_archived: bool = False
    project_paths: list[str] = field(default_factory=list)
    crates: list[AuditedCrate] = field(default_factory=list)
    managed_crates_count: int = 0
    mismatch_crates_count: int = 0
    unmanaged_crates_count: int = 0


@dataclass
class CrateUsage:
    """Summary of usage for a single crate across the organization."""

    crate_name: str
    status: CrateStatus
    score_crates_version: str | None = None
    used_in_repos: list[str] = field(default_factory=list)
    versions_seen: set[str] = field(default_factory=set)


@dataclass
class OrganizationAuditReport:
    """Consolidated organization-wide audit report."""

    organization: str = ""
    total_repositories: int = 0
    rust_repositories_count: int = 0
    total_distinct_crates: int = 0
    managed_crates_count: int = 0
    mismatch_crates_count: int = 0
    unmanaged_crates_count: int = 0
    repositories: list[AuditedRepository] = field(default_factory=list)
    crate_usage_summary: dict[str, CrateUsage] = field(default_factory=dict)


def _versions_match(req_ver: str | None, ref_ver: str | None) -> bool:
    """Compares a requested version with score-crates version."""
    if not req_ver or not ref_ver:
        return True

    clean_req = req_ver.lstrip("=^~ ")
    clean_ref = ref_ver.lstrip("=^~ ")

    # Direct match or major.minor match
    if clean_req == clean_ref:
        return True

    return False


def audit_repository(
    repo_data: RepositoryAuditData, score_crates_ref: ScoreCratesReference
) -> AuditedRepository:
    """Audits a single repository against score-crates."""
    project_paths: list[str] = []
    internal_crate_names: set[str] = set()

    for toml in repo_data.cargo_tomls:
        if toml.path and toml.path not in project_paths:
            project_paths.append(toml.path)
        if toml.name and toml.name not in ("workspace_root", "unknown"):
            internal_crate_names.add(toml.name)

    # Build lockfile lookup: crate_name -> version
    lock_versions: dict[str, str] = {}
    for lock in repo_data.cargo_locks:
        lock_versions[lock.name] = lock.version

    # Map crate_name -> collected info
    collected_crates: dict[str, dict] = {}

    for toml in repo_data.cargo_tomls:
        for dep in toml.dependencies:
            # Exclude internal path dependencies
            if dep.is_path or dep.name in internal_crate_names:
                continue

            crate_name = dep.name
            if crate_name not in collected_crates:
                collected_crates[crate_name] = {
                    "version_req": dep.version_req,
                    "features": set(dep.features),
                    "dep_types": {dep.dep_type},
                    "manifests": {toml.path} if toml.path else set(),
                }
            else:
                entry = collected_crates[crate_name]
                if dep.version_req and not entry["version_req"]:
                    entry["version_req"] = dep.version_req
                entry["features"].update(dep.features)
                entry["dep_types"].add(dep.dep_type)
                if toml.path:
                    entry["manifests"].add(toml.path)

    # If there are crates in lockfile not in toml (e.g. transitive or lockfile-only)
    # We focus on directly declared crates from tomls as primary, but if no tomls (only lockfile),
    # include lockfile crates
    if not collected_crates and repo_data.cargo_locks:
        for lock in repo_data.cargo_locks:
            if lock.name in internal_crate_names:
                continue
            collected_crates[lock.name] = {
                "version_req": lock.version,
                "features": set(),
                "dep_types": {"locked"},
                "manifests": {"Cargo.lock"},
            }

    audited_crates: list[AuditedCrate] = []
    managed_count = 0
    mismatch_count = 0
    unmanaged_count = 0

    for crate_name, info in sorted(collected_crates.items()):
        resolved_ver = lock_versions.get(crate_name)
        requested_ver = info["version_req"] or resolved_ver
        score_ver = score_crates_ref.get_version(crate_name)

        if not score_crates_ref.contains_crate(crate_name):
            status = CrateStatus.UNMANAGED
            unmanaged_count += 1
        elif (
            score_ver
            and requested_ver
            and not _versions_match(requested_ver, score_ver)
        ):
            status = CrateStatus.VERSION_MISMATCH
            mismatch_count += 1
        else:
            status = CrateStatus.MANAGED
            managed_count += 1

        audited_crates.append(
            AuditedCrate(
                crate_name=crate_name,
                status=status,
                requested_version=requested_ver,
                resolved_version=resolved_ver,
                score_crates_version=score_ver,
                features=sorted(info["features"]),
                dep_types=sorted(info["dep_types"]),
                manifest_paths=sorted(info["manifests"]),
            )
        )

    return AuditedRepository(
        repo_name=repo_data.name,
        is_archived=repo_data.is_archived,
        project_paths=project_paths,
        crates=audited_crates,
        managed_crates_count=managed_count,
        mismatch_crates_count=mismatch_count,
        unmanaged_crates_count=unmanaged_count,
    )


def audit_organization(
    repos_data: list[RepositoryAuditData], score_crates_ref: ScoreCratesReference
) -> OrganizationAuditReport:
    """Audits multiple repositories and produces an aggregated organization report."""
    audited_repos: list[AuditedRepository] = []
    crate_usage: dict[str, CrateUsage] = {}

    for repo_data in repos_data:
        audited_repo = audit_repository(repo_data, score_crates_ref)
        if audited_repo.crates or audited_repo.project_paths:
            audited_repos.append(audited_repo)

        for c in audited_repo.crates:
            if c.crate_name not in crate_usage:
                crate_usage[c.crate_name] = CrateUsage(
                    crate_name=c.crate_name,
                    status=c.status,
                    score_crates_version=c.score_crates_version,
                    used_in_repos=[audited_repo.repo_name],
                    versions_seen={c.requested_version}
                    if c.requested_version
                    else set(),
                )
            else:
                usage = crate_usage[c.crate_name]
                if audited_repo.repo_name not in usage.used_in_repos:
                    usage.used_in_repos.append(audited_repo.repo_name)
                if c.requested_version:
                    usage.versions_seen.add(c.requested_version)
                # Escalate status if any mismatch
                if c.status == CrateStatus.VERSION_MISMATCH:
                    usage.status = CrateStatus.VERSION_MISMATCH

    total_managed = sum(
        1 for u in crate_usage.values() if u.status == CrateStatus.MANAGED
    )
    total_mismatch = sum(
        1 for u in crate_usage.values() if u.status == CrateStatus.VERSION_MISMATCH
    )
    total_unmanaged = sum(
        1 for u in crate_usage.values() if u.status == CrateStatus.UNMANAGED
    )

    return OrganizationAuditReport(
        organization="",
        total_repositories=len(repos_data),
        rust_repositories_count=len(audited_repos),
        total_distinct_crates=len(crate_usage),
        managed_crates_count=total_managed,
        mismatch_crates_count=total_mismatch,
        unmanaged_crates_count=total_unmanaged,
        repositories=audited_repos,
        crate_usage_summary=crate_usage,
    )
