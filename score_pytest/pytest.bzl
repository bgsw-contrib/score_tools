# *******************************************************************************
# Copyright (c) 2025 Contributors to the Eclipse Foundation
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
"""Bazel interface for running pytest"""

load("@rules_python//python:defs.bzl", "py_test")
load("@score_pytest_pip//:requirements.bzl", "all_requirements")

def score_pytest(name, srcs, args = [], data = [], deps = [], env = {}, plugins = [], pytest_config = None, **kwargs):
    if not pytest_config:
        pytest_config = Label("@score_tools//score_pytest:pytest.ini")
        #fail("$(location %s)" % pytest_config)

    if not srcs:
        fail("No source files provided for %s! (Is your glob empty?)" % name)

    plugins = ["-p attribute_plugin"] + ["-p %s" % plugin for plugin in plugins]

    py_test(
        name = name,
        srcs = srcs,
        main_module = "pytest",
        args = [
                   "-c $(location %s)" % pytest_config,
                   "-p no:cacheprovider",

                   # XML_OUTPUT_FILE: Location to which test actions should write a test
                   # result XML output file. Otherwise, Bazel generates a default XML
                   # output file wrapping the test log as part of the test action. The XML
                   # schema is based on the JUnit test result schema.
                   "--junitxml=$$XML_OUTPUT_FILE",
               ] +
               args +
               ["-o", "junit_family=xunit1"] +
               plugins +
               ["$(locations %s)" % x for x in srcs],
        deps = ["@score_tools//score_pytest:attribute_plugin"] + all_requirements + deps,
        data = [
            pytest_config,
        ] + data,
        env = env | {
            "PYTHONDONOTWRITEBYTECODE": "1",
        },
        **kwargs
    )
