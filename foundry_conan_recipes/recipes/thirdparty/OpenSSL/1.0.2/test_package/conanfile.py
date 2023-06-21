# SPDX-License-Identifier: Apache-2.0
# Copyright 2023 The Foundry Visionmongers Ltd

from os import path
from conans import ConanFile, CMake, errors


class TestPackage(ConanFile):
    settings = "os", "arch", "compiler", "build_type"

    generators = ["cmake_paths"]

    def configure(self):
        del self.settings.compiler.libcxx

    def test(self):
        cmake = CMake(self)
        if not self.deps_cpp_info["OpenSSL"].libs:
            raise errors.ConanException("The recipe must export at least these libraries: crypto, ssl. Others are required, depending upon the platform, e.g. dl & pthread.")
        cmake.definitions["CMAKE_PROJECT_PackageTest_INCLUDE"] = path.join(
            self.install_folder, "conan_paths.cmake"
        )
        cmake.definitions["shared_openssl"] = self.options["OpenSSL"].shared
        cmake.configure()
        cmake.build()
        cmake.test(output_on_failure=True)
