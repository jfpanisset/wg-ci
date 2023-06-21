# SPDX-License-Identifier: Apache-2.0
# Copyright 2023 The Foundry Visionmongers Ltd

import os
from conans import ConanFile, CMake, tools

class SymbolicTestConan(ConanFile):
    settings = "os", "compiler", "build_type", "arch"
    generators = "cmake_paths"

    def build(self):
        cmake = CMake(self)
        cmake.definitions["CMAKE_PROJECT_TestPackage_INCLUDE"] = os.path.join(self.install_folder, "conan_paths.cmake")
        cmake.configure()
        cmake.build()
        cmake.test()

    def test(self):
        pass
